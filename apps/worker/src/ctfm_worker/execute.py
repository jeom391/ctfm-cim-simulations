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
        datasets=[]
        for index,meta in enumerate(request["inputs"]):
            record=store.get_entity("file",meta["file_id"])
            data=store.managed_path(record["relative_path"]).read_bytes()
            if sha256(data)!=record["sha256"]:raise ValueError("Source hash mismatch")
            parsed=parse_table(data,record["name"],meta.get("sheet"))
            pairs=[(r,n) for r,n in zip(parsed["rows"],parsed["source_rows"]) if (meta.get("row_start") is None or n>=meta["row_start"]) and (meta.get("row_end") is None or n<=meta["row_end"])]
            if not pairs:raise ValueError("Selected row range is empty")
            rows,source_rows=zip(*pairs)
            datasets.append(dict(meta,rows=list(rows),source_rows=list(source_rows),filename=record["name"],sha256=record["sha256"]))
            progress("parsing",index+1,len(request["inputs"]))
        result=analyze(request["kind"],datasets,request["settings"])
        result["analysis_id"]=item["id"]
    else:
        from ctfm.simulation import run_experiment
        profiles=[store.get_profile(r["id"],r["revision"]) for r in request["profile_refs"]]
        checkpoint_path=None
        if request["checkpoint_id"]:
            record=store.get_entity("checkpoint",str(UUID(request["checkpoint_id"])))
            checkpoint_path=store.managed_path(record["relative_path"])
            if sha256(checkpoint_path.read_bytes())!=record["sha256"]:raise ValueError("Checkpoint hash mismatch")
        # Latest spec07 takes precedence: the requested seed controls splitting.
        result=run_experiment(request,profiles,output,cache_dir=store.root/"cache",
                              checkpoint_path=checkpoint_path,progress=progress,split_seed=request["seed"])
        result["experiment_id"]=item["id"];result["design_version"]="1.1.0"
        requested=len(request["profile_refs"])*len(request["pools"])*len(request["mappings"])*int(request["arrays"])*int(request["n_reprogram"])*len(request["years"])
        actual=[r for r in result["runs"] if r.get("kind")=="ALL"]
        completed=sum(r["status"]=="succeeded" for r in actual)
        failed=sum(r["status"] in ("invalid","failed") for r in actual)
        skipped=requested-len(actual)
        result["summary"].update(requested=requested,completed=completed,failed=failed,skipped=skipped)
        result["status"]="succeeded" if completed==requested else "partial"
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
