"""One isolated calculation. The parent worker alone commits terminal job state."""
import json
import sys
import traceback
from uuid import UUID
from pathlib import Path
from ctfm_api.storage import Store, encode, sha256
from .exports import export_result

def execute(job_id):
    store=Store();job=store.get_job(job_id)
    if job["state"]!="running" or job["cancel_requested"]:
        raise ValueError("Job is not executable")
    output=store.job_dir(job_id)
    item=store.get_entity(job["kind"],job["entity_id"]);request=item["request"]
    progress=lambda stage,completed,total:store.progress(job_id,"parsing" if stage=="download" else stage,completed,total)
    if job["kind"]=="analysis":
        from ctfm.measurement import parse_table, analyze
        from ctfm_api.contracts import AnalysisRequest
        from ctfm_api.recognition import verify_recognized_request
        recognition = verify_recognized_request(store, AnalysisRequest.model_validate(request)) if request.get("recognition_id") else None
        datasets=[]
        for index,meta in enumerate(request["inputs"]):
            record=store.get_entity("file",meta["file_id"])
            data=store.managed_path(record["relative_path"]).read_bytes()
            if sha256(data)!=record["sha256"]:raise ValueError("Source hash mismatch")
            if request["kind"]=="c2c_detrended":
                from ctfm.measurement.c2c import analyze_c2c_file, to_analysis_record
                raw=analyze_c2c_file(data,record["name"],sheet=meta.get("sheet"),device_id=meta["device_id"],condition_id=meta["condition_id"],
                                     measurement_conditions=meta.get("measurement_conditions"))
                result=to_analysis_record(raw);result["analysis_id"]=item["id"]
                progress("parsing",1,1)
                break
            selection=meta.get("selection")
            if selection:
                from ctfm.measurement.layouts import iv_dataset, retention_dataset
                common=dict(device_id=meta["device_id"],condition_id=meta["condition_id"],file_id=meta["file_id"],sha256=record["sha256"],sheet=meta.get("sheet"),units=meta["units"])
                if selection["type"]=="iv_block":
                    dataset=iv_dataset(data,record["name"],block=selection["block"],segment=selection["segment"],branch=meta["branch"],
                                       sweep_amplitude_v=meta["sweep_amplitude_v"],vds_v=meta["vds_v"],read_vgs_v=meta.get("read_vgs_v",0.0),**common)
                else:
                    dataset=retention_dataset(data,record["name"],columns=selection["columns"],source_label=meta["source_label"],
                                              read_vgs_v=meta["read_vgs_v"],header_read_vgs_v=meta.get("header_read_vgs_v"),vds_v=meta["vds_v"],**common)
                datasets.append(dataset);progress("parsing",index+1,len(request["inputs"]));continue
            parsed=parse_table(data,record["name"],meta.get("sheet"))
            pairs=[(r,n) for r,n in zip(parsed["rows"],parsed["source_rows"]) if (meta.get("row_start") is None or n>=meta["row_start"]) and (meta.get("row_end") is None or n<=meta["row_end"])]
            if not pairs:raise ValueError("Selected row range is empty")
            rows,source_rows=zip(*pairs)
            datasets.append(dict(meta,rows=list(rows),source_rows=list(source_rows),filename=record["name"],sha256=record["sha256"]))
            progress("parsing",index+1,len(request["inputs"]))
        if request["kind"]!="c2c_detrended":
            result=analyze(request["kind"],datasets,request["settings"])
            result["analysis_id"]=item["id"]
    else:
        from ctfm_contracts.check_experiment_contract import validate_request
        from ctfm_contracts.product_policy import validate_product_scope
        from ctfm.simulation import run_experiment
        validate_request(request)
        validate_product_scope(request)
        comparison=bool(item.get("comparison_id"))
        profiles=[]
        snapshot=store.get_entity("comparison",item["comparison_id"])["snapshot"] if comparison else None
        for ref in request["profile_refs"]:
            try:
                profile=store.get_profile(ref["id"],ref["revision"])
                if comparison:
                    frozen=next(m for m in snapshot["profiles"] if m["profile_id"]==ref["id"] and m["revision"]==ref["revision"])
                    if profile["manifest"]["profile_hash"]!=frozen["profile_hash"]: raise ValueError("Published profile differs from the run snapshot")
                c2c=ref.get("c2c") if request["effects"]["c2c"] else None
                if c2c and c2c["source"]=="measured_detrended":
                    from ctfm.measurement.c2c import result_pin
                    analysis=store.get_entity("analysis",c2c["analysis_id"])
                    if analysis.get("status")!="succeeded" or result_pin(analysis)!=c2c["provenance"]["analysis_result_sha256"]:
                        raise ValueError("Measured C2C differs from the pinned analysis")
            except (ValueError,KeyError) as exc:
                if not comparison: raise
                # Keep identity and frozen provenance; core records this profile's reason.
                frozen=next(m for m in snapshot["profiles"] if m["profile_id"]==ref["id"] and m["revision"]==ref["revision"])
                profile=dict(manifest=frozen,states=[],comparison_error=str(exc))
            profiles.append(profile)
        checkpoint_path=None
        if request["checkpoint_id"]:
            record=store.get_entity("checkpoint",str(UUID(request["checkpoint_id"])))
            checkpoint_path=store.managed_path(record["relative_path"])
            if sha256(checkpoint_path.read_bytes())!=record["sha256"]:raise ValueError("Checkpoint hash mismatch")
        # Latest spec07 takes precedence: the requested seed controls splitting.
        result=run_experiment(request,profiles,output,cache_dir=store.root/"cache",
                              checkpoint_path=checkpoint_path,progress=progress,split_seed=request["seed"],comparison=comparison)
        result["experiment_id"]=item["id"];result["design_version"]="1.1.0"
        requested=len(request["profile_refs"])*len(request["pools"])*len(request["mappings"])*int(request["arrays"])*int(request["n_reprogram"])*len(request["years"])
        actual=[r for r in result["runs"] if r.get("kind")=="ALL"]
        completed=sum(r["status"]=="succeeded" for r in actual)
        failed=sum(r["status"] in ("invalid","failed") for r in actual)
        skipped=requested-len(actual)
        result["summary"].update(requested=requested,completed=completed,failed=failed,skipped=skipped)
        result["status"]="succeeded" if completed==requested else "partial"
    if job["kind"] == "analysis" and recognition:
        result["recognition"] = recognition
    progress("exporting",0,1)
    export_result(result,output)
    (output/"worker-result.json").write_text(encode(result),encoding="utf-8")
    progress("exporting",1,1)

if __name__=="__main__":
    job_id=sys.argv[1]
    try:
        from .lifecycle import guard_parent
        guard_parent()
        execute(job_id)
    except Exception as exc:
        traceback.print_exc()
        store=Store();output=store.job_dir(job_id)
        message=str(exc) if isinstance(exc,ValueError) else "Calculation failed; inspect the worker log artifact."
        (output/"worker-error.json").write_text(encode({"code":"calculation_failed","message":message}),encoding="utf-8")
        sys.exit(1)
