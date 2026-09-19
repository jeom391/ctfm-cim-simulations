"""Exercise the running application with explicitly synthetic device data."""
import argparse
import json
from pathlib import Path
import time
import httpx

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url",default="http://127.0.0.1:8000")
    parser.add_argument("--timeout",type=int,default=900)
    parser.add_argument("--engine",default="torch_reference",choices=("torch_reference","aihwkit_ideal"),
                        help="accuracy engine; must be advertised as available by this server")
    parser.add_argument("--checkpoint-id",default=None,help="reuse a checkpoint across engines")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    fixtures=root/"packages/contracts/fixtures/measurement"
    with httpx.Client(base_url=args.base_url+"/api/v1",timeout=60) as client:
        def get(path):
            response=client.get(path);response.raise_for_status();return response.json()
        def post(path,payload):
            response=client.post(path,json=payload);response.raise_for_status();return response.json()
        def wait_job(identifier):
            deadline=time.monotonic()+args.timeout;last=None
            while time.monotonic()<deadline:
                job=get("/jobs/"+identifier)
                state=(job["state"],job["stage"],job["completed"],job["total"])
                if state!=last:print(json.dumps({"job_id":identifier,"progress":state}),flush=True);last=state
                if job["state"]=="succeeded":return
                if job["state"] in ("failed","cancelled"):raise RuntimeError(json.dumps(job))
                time.sleep(1)
            raise TimeoutError("Worker did not complete within the smoke timeout")
        # Ask the server, not the local process: the engine has to be available
        # where the worker actually runs.
        capabilities=get("/capabilities")
        engine=capabilities["engines"][args.engine]
        if not engine["available"]:raise SystemExit("Server reports "+args.engine+" unavailable: "+str(engine["reason"]))
        inputs=[]
        for direction in ("ltp","ltd"):
            path=fixtures/("pulse-"+direction+".csv")
            response=client.post("/files",files={"files":(path.name,path.read_bytes(),"text/csv")})
            response.raise_for_status();file_id=response.json()["files"][0]["file_id"]
            preview=get("/files/"+file_id+"/preview")
            assert preview["source_rows"][0]==3
            inputs.append(dict(file_id=file_id,column_mapping=dict(time_s="time",id_a="current",vgs_v="gate"),units=dict(time_s="s",id_a="A",vgs_v="V"),condition_id="A1",device_id="SYNTHETIC-NOT-MEASURED",direction=direction,vds_v=.1,read_vgs_v=0))
        queued=post("/analyses",dict(kind="pulse_states",inputs=inputs,settings={}))
        wait_job(queued["job_id"]);analysis=get("/analyses/"+queued["analysis_id"])
        profile=post("/profiles",dict(condition_id="A1",state_analysis_id=analysis["analysis_id"],selected_state_ids=[s["state_id"] for s in analysis["states"]],display_name="SYNTHETIC SOFTWARE SMOKE"))
        endpoint=f"/profiles/{profile['profile_id']}/revisions/1"
        profile=post(endpoint+"/publish",dict(reviewer="automated synthetic smoke",review_note="Only synthetic fixture states; verifies software, not measured CTFM performance."))
        config=json.loads((root/"packages/contracts/fixtures/experiment-baseline.request.json").read_text())
        config["profile_refs"]=[dict(id=profile["profile_id"],revision=1)]
        config["engines"]["accuracy"]=args.engine
        if args.checkpoint_id:config["checkpoint_id"]=args.checkpoint_id
        experiment=post("/experiments",config);wait_job(experiment["job_id"])
        result=get("/experiments/"+experiment["experiment_id"])
        assert result["summary"]["completed"]==result["summary"]["requested"]
        assert result["effective_config"]["seed"]==config["seed"]
        assert result["effective_config"]["engines"]["accuracy"]==args.engine,"engine silently substituted"
        # D0 is digital and always runs on torch_reference; every other run must
        # name the requested engine, so a fallback cannot hide in the results.
        engines_used=sorted({run["engine"] for run in result["runs"]})
        assert args.engine in engines_used,"requested engine never executed: "+str(engines_used)
        accuracies={run["kind"]+"|"+str(run.get("pool"))+"|"+str(run.get("mapping")):run.get("accuracy") for run in result["runs"]}
        print(json.dumps({"analysis_id":analysis["analysis_id"],"profile_id":profile["profile_id"],"experiment_id":experiment["experiment_id"],"checkpoint_id":result["checkpoint_id"],"requested_engine":args.engine,"engines_used":engines_used,"accuracies":accuracies,"summary":result["summary"],"device_evidence":"synthetic_only"},ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":main()
