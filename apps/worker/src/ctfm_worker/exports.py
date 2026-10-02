"""Downloadable numeric tables and plots; strings never become spreadsheet formulas.

Everything written to the job folder stays there for reproduction and recovery. Only files
written under ``user/`` are what the device team downloads (role=user, see Store.register_artifact):
one result table and one graph per analysis, named by analysis kind and condition."""
import csv
import json
from pathlib import Path

USER_DIR = "user"
KIND_LABELS = {"pulse_states": "LTP-LTD", "iv": "Vth-MW", "d2d": "D2D", "retention": "Retention",
               "c2c_sweep": "C2C", "c2c_detrended": "C2C-PE"}


def scalar(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False) if isinstance(value,(dict,list)) else value

def safe_csv(value):
    value=scalar(value)
    if isinstance(value,str) and value.lstrip().startswith(("=","+","-","@")):
        return "'"+value
    return value

def write_csv(path, rows):
    columns=list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(columns)
        writer.writerows([[safe_csv(row.get(key)) for key in columns] for row in rows])

def export_result(result, output_dir):
    from openpyxl import Workbook
    output_dir=Path(output_dir)
    (output_dir/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    tables=dict(result.get("tables",{}))
    if result.get("runs"):
        tables["runs"]=result["runs"]
    tables["exclusions"]=result.get("exclusions",[])
    workbook=Workbook();workbook.remove(workbook.active)
    for name,rows in tables.items():
        if not rows: continue
        columns=list(dict.fromkeys(key for row in rows for key in row))
        # Core owns names; prevent accidentally constructing a file path from data.
        name="".join(c for c in name if c.isalnum() or c in "_-")[:40] or "table"
        write_csv(output_dir/(name+".csv"),rows)
        sheet=workbook.create_sheet(name[:31])
        # sheet.max_row scans every cell, which made this loop quadratic on 24k-row tables.
        for index,values in enumerate([columns]+[[scalar(row.get(key)) for key in columns] for row in rows],start=1):
            sheet.append(values)
            for column,value in enumerate(values,start=1):
                if isinstance(value,str): sheet.cell(index,column).data_type="s"
        sheet.freeze_panes="A2";sheet.auto_filter.ref=sheet.dimensions
    if not workbook.worksheets:
        sheet=workbook.create_sheet("summary");sheet.append(["status","No tabular rows"])
    workbook.save(output_dir/"tables.xlsx")
    if result.get("kind") in KIND_LABELS:
        user=output_dir/USER_DIR;user.mkdir(exist_ok=True)
        stem="".join(c for c in f"{result.get('condition_id') or '조건미상'}_{KIND_LABELS[result['kind']]}" if c.isalnum() or c in "_-")
        rows=user_rows(result)
        if rows: write_csv(user/f"{stem}_결과.csv",rows)
        plot_result(result,user/f"{stem}_그래프.png")
    else:
        plot_result(result,output_dir/"plot.png")
    lines=["# Computation result","", "Measurement evidence and modeling assumptions are recorded in summary.json.",""]
    if result.get("summary"):lines.append(json.dumps(result["summary"],ensure_ascii=False,indent=2,allow_nan=False))
    for warning in result.get("warnings",[]):lines.append("- "+warning)
    (output_dir/"summary.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def _recognition_exclusions(result):
    return [dict(i, file=s["name"]) for s in (result.get("recognition") or {}).get("sources", []) for i in s.get("issues", [])
            if i.get("code") == "d2d_condition_excluded"]


def user_rows(result):
    """The one table the device team needs per analysis: units, method and conditions stay in the table."""
    kind=result["kind"];tables=result.get("tables",{})
    if kind=="c2c_sweep":
        method=result["method"]
        return [{"구간":p["label"],"원본 셀 범위":p.get("cell_range"),"사이클 수 N":p["n"],
                 "평균 전류 (uA)":None if p.get("mean_a") is None else p["mean_a"]*1e6,
                 "표본 SD (uA)":None if p.get("sd_a") is None else p["sd_a"]*1e6,
                 "전체 변동 CV (%)":p.get("cv_overall_percent"),
                 "추세 제거 후 상대 잔차 표준편차 (%)":p.get("cv_residual_percent"),
                 "선형 추세 기울기 (uA/cycle)":None if p.get("trend_slope_a_per_cycle") is None else p["trend_slope_a_per_cycle"]*1e6,
                 "잔차 lag-1 상관":p.get("residual_lag1_correlation"),
                 "상태":p["status"],"사유":p.get("reason") or p.get("residual_reason") or p.get("overall_reason"),
                 "전체 변동 계산식":method["overall"],"추세 제거 계산식":method["residual"],
                 "원본 파일":result["provenance"]["filename"]} for p in result["summaries"]["points"]]
    if kind=="d2d":
        names={p["file_id"]:p["filename"] for p in result.get("provenance",[])}
        rows=[]
        for c in tables.get("d2d_conditions",[]):
            row={"진폭 (V)":c["sweep_amplitude_v"],"분기":c["branch"]}
            for n,device in enumerate(c["device_values"],1):
                row[f"소자{n}"]=device and device["device_id"];row[f"소자{n} 파일"]=device and names.get(device["file_id"])
                row[f"소자{n} Id@Vg=0V (A)"]=device and device["id_a"];row[f"소자{n} G=Id/VDS (S)"]=device and device["conductance_s"]
            row.update({"평균 G (S)":c["mean_g_s"],"표본 SD G (S)":c["std_g_s"],"CV (%)":None if c["cv"] is None else 100*c["cv"],
                        "포함":c["included"],"사유":c["reason"]})
            rows.append(row)
        for e in _recognition_exclusions(result):
            rows.append({"분기":"인식 단계 제외","소자1 파일":e["file"],"포함":False,"사유":e["detail"]})
        summary=result["summaries"]
        rows.append({"진폭 (V)":"대표값","분기":"RMS","CV (%)":None if summary.get("cv") is None else 100*summary["cv"],
                     "포함":summary.get("status")=="available",
                     "사유":f"K={summary.get('matched_conditions')} 조건 RMS = sqrt(mean(CV_k^2)); VDS=0.1 V; 선택한 물리 소자 2개 기준"})
        return rows
    if kind=="retention":
        fits=tables.get("retention_fit",[]);extra=tables.get("retention_extrapolation",[])
        rows=[{"구분":"실측","방향":r["direction"],"시간 (s)":r["time_s"],"측정 Id (A)":r["id_a"],"적합 Id (A)":r["fit_id_a"],"모델 유효":None} for r in fits]
        for r in extra:
            if r["region"]!="extrapolated":continue
            for d in ("program","erase"):
                rows.append({"구분":"외삽(모델)","방향":d,"시간 (s)":r["time_s"],"시간 (년)":r["years"],"측정 Id (A)":None,
                             "적합 Id (A)":r[d+"_fit_a"],"모델 유효":r[d+"_valid"]})
        return rows
    if kind=="iv":
        rows=[{"구분":"Vth","소자":r["device_id"],"진폭 (V)":r["sweep_amplitude_v"],"분기":r["branch"],"Vth (V)":r["vth_v"],"상태":r["status"]} for r in tables.get("vth",[])]
        rows+=[{"구분":"MW","소자":r["device_id"],"진폭 (V)":r["sweep_amplitude_v"],"MW (V)":r["mw_v"],"상태":r["status"]} for r in tables.get("memory_window",[])]
        return rows
    if kind=="pulse_states":
        return [{"방향":s["direction"],"추출 순서":s["extraction_index"],"원본 행":s["source_row"],"시간 (s)":s["time_s"],
                 "Id (A)":s["id_a"],"G=Id/VDS (S)":s["conductance_s"],"채택":s["selected"],"제외 사유":s["exclusion_reason"]} for s in result.get("states",[])]
    if kind=="c2c_detrended":
        return [{"분기":b,**result["summaries"][b]} for b in ("program","erase")]
    return []


def plot_result(result, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(8,4.5),layout="constrained")
    kind=result.get("kind")
    rows=result.get("tables",{}).get("raw",[])
    if kind=="pulse_states":
        for direction in ("ltp","ltd"):
            states=[s for s in result["states"] if s["direction"]==direction]
            ax.plot([s["extraction_index"] for s in states],[s["conductance_s"] for s in states],"o-",label=direction)
        ax.set(xlabel="Observed extraction index",ylabel="Absolute conductance (S)",title="Observed pulse states")
    elif kind=="d2d":
        conditions=[c for c in result["tables"].get("d2d_conditions",[])]
        for branch,marker in (("program","o"),("erase","s")):
            subset=[c for c in conditions if c["branch"]==branch and c["cv"] is not None]
            ax.plot([c["sweep_amplitude_v"] for c in subset],[100*c["cv"] for c in subset],marker,ls="-",label=branch)
        if result["summaries"].get("cv") is not None:
            ax.axhline(100*result["summaries"]["cv"],color="k",ls="--",lw=1,label=f"RMS {100*result['summaries']['cv']:.2f}%")
        ax.set(xlabel="Sweep amplitude (V)",ylabel="Two-device CV of G at Vg=0 V (%)",title="D2D per matched condition")
    elif kind=="iv":
        for file_id in dict.fromkeys(row["file_id"] for row in rows):
            series=[r for r in rows if r["file_id"]==file_id]
            ax.plot([r["vgs_v"] for r in series],[r["id_a"] for r in series],label=file_id[:8])
        ax.set(xlabel="VGS (V)",ylabel="ID (A)",title="Measured IV curves")
    elif kind=="c2c_sweep":
        cycles=result["tables"]["cycles"]
        for (key,label),color in zip((("initial_0v","initial 0 V"),("ascending_0v","ascending 0 V"),("descending_0v","descending 0 V")),("tab:gray","tab:blue","tab:red")):
            if key+"_current_a" not in cycles[0]:continue
            ax.plot([c["cycle"] for c in cycles],[c[key+"_current_a"]*1e6 for c in cycles],"o",ms=3,color=color,label=label)
            ax.plot([c["cycle"] for c in cycles],[c[key+"_trend_a"]*1e6 for c in cycles],"-",color=color,lw=1)
        ax.set(xlabel="Cycle",ylabel="Id at Vg = 0 V (uA)",title="Repeated sweep: measured current and linear trend")
    elif kind=="c2c_detrended":
        cycles=result["tables"]["cycles"]
        for branch,color in (("program","tab:blue"),("erase","tab:red")):
            ax.plot([c["cycle"] for c in cycles],[c[branch+"_current"] for c in cycles],".",ms=2,color=color,alpha=.5,label=branch+" raw")
            ax.plot([c["cycle"] for c in cycles],[c[branch+"_trend"] for c in cycles],"-",color=color,label=branch+" cubic trend")
        ax.set(xlabel="Cycle",ylabel="Read current ("+result["provenance"]["unit"]+")",title="Repeated P/E read current and cubic trend (not iid C2C)")
    elif kind=="retention":
        extra=result["tables"].get("retention_extrapolation",[])
        info=result["summaries"].get("extrapolation") or {}
        for direction,color in (("program","tab:blue"),("erase","tab:red")):
            series=sorted([r for r in result["tables"].get("retention_fit",[]) if r["direction"]==direction],key=lambda r:r["time_s"])
            ax.scatter([r["time_s"] for r in series],[r["id_a"] for r in series],s=10,color=color,label=direction+" measured")
            measured=[r for r in extra if r["region"]=="measured"];future=[r for r in extra if r["region"]=="extrapolated"]
            ax.plot([r["time_s"] for r in measured],[r[direction+"_fit_a"] for r in measured],"-",color=color,label=direction+" fit (measured range)")
            if measured and future:
                ax.plot([measured[-1]["time_s"]]+[r["time_s"] for r in future],[measured[-1][direction+"_fit_a"]]+[r[direction+"_fit_a"] for r in future],"--",color=color,label=direction+" extrapolation (model)")
        if info:
            ax.axvline(info["measured_end_s"],color="k",lw=.8,ls=":",label="end of measurement")
            ax.axvline(info["horizon_s"],color="gray",lw=.8,ls="-.",label="10 years")
        ax.axhline(0,color="k",lw=.6)
        ax.set(xscale="log",xlabel="Time (s)",ylabel="Id (A)",title="Retention: measured (solid) vs log-linear extrapolation (dashed)")
    elif result.get("runs"):
        runs=[r for r in result["runs"] if r.get("kind")=="ALL" and r["status"]=="succeeded"]
        for candidate in dict.fromkeys(r["candidate_id"] for r in runs):
            subset=[r for r in runs if r["candidate_id"]==candidate]
            years=sorted({r["years"] for r in subset})
            ax.plot(years,[sum(r["accuracy"] for r in subset if r["years"]==y)/sum(r["years"]==y for r in subset) for y in years],"o-",label=candidate)
        ax.set(xlabel="Years (extrapolation when beyond measured interval)",ylabel="Accuracy (fraction)",title="Valid inference runs only",ylim=(0,1))
    else:
        plt.close(fig);return
    handles,labels=ax.get_legend_handles_labels()
    if handles:ax.legend(fontsize=8)
    ax.grid(alpha=.2)
    fig.savefig(path,dpi=160);plt.close(fig)
