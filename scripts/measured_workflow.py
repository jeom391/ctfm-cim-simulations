"""Run the running application end to end on the shared, hash-pinned LTP/LTD CSVs.

upload -> preview -> pulse_states analysis -> profile -> publish -> export ZIP
-> MNIST experiment, for every condition in the 2026-09-21 manifest. Unlike
smoke_workflow.py this uses measured files, so it checks the production parser
through the HTTP boundary, not only in-process.
"""
import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/reference/ltp-ltd-2026-09-21"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--conditions", default="A1,A2,A3,A4,A5")
    parser.add_argument("--experiment-conditions", default="A1",
                        help="conditions that also run an MNIST experiment ('' for none)")
    parser.add_argument("--engine", default="torch_reference")
    parser.add_argument("--adc-order", default="subtract_then_adc",
                        help="with --adc-bits; 'none' runs without ADC")
    parser.add_argument("--adc-bits", type=int, default=6)
    parser.add_argument("--checkpoint-id", default=None)
    args = parser.parse_args()
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))["files"]
    report = {"conditions": {}}
    with httpx.Client(base_url=args.base_url + "/api/v1", timeout=120) as client:
        def call(method, path, **kw):
            r = client.request(method, path, **kw)
            if r.status_code >= 400:
                raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:800]}")
            return r

        def wait_job(identifier):
            deadline, last = time.monotonic() + args.timeout, None
            while time.monotonic() < deadline:
                job = call("GET", "/jobs/" + identifier).json()
                state = (job["state"], job["stage"], job["completed"], job["total"])
                if state != last:
                    print(json.dumps({"job_id": identifier, "progress": state}), flush=True)
                    last = state
                if job["state"] == "succeeded":
                    return
                if job["state"] in ("failed", "cancelled"):
                    raise SystemExit(json.dumps(job, ensure_ascii=False))
                time.sleep(1)
            raise SystemExit("timeout waiting for " + identifier)

        caps = call("GET", "/capabilities").json()
        if not caps["engines"][args.engine]["available"]:
            raise SystemExit(args.engine + " unavailable: " + str(caps["engines"][args.engine]))
        for condition in args.conditions.split(","):
            entries = [f for f in manifest if f["condition_id"] == condition]
            inputs, checks = [], []
            for f in entries:
                raw = (DATA / f["file"]).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == f["sha256"]
                up = call("POST", "/files", files={"files": (Path(f["file"]).name, raw, "text/csv")}).json()["files"][0]
                assert up["sha256"] == f["sha256"], ("server hash differs", up)
                preview = call("GET", f"/files/{up['file_id']}/preview").json()
                assert preview["source_rows"][0] == f["data_start_row"], preview["source_rows"][:3]
                inputs.append(dict(file_id=up["file_id"], column_mapping=f["column_mapping"], units=f["units"],
                                   condition_id=condition, device_id=condition + "-measured-2026-09-21",
                                   direction=f["direction"], vds_v=f["vds_v"], read_vgs_v=f["read_vgs_v"]))
                checks.append(f)
            queued = call("POST", "/analyses", json=dict(kind="pulse_states", inputs=inputs, settings={})).json()
            wait_job(queued["job_id"])
            analysis = call("GET", "/analyses/" + queued["analysis_id"]).json()
            states = analysis["states"]
            for f in checks:
                own = [s for s in states if s["direction"] == f["direction"]]
                assert len(own) == f["reference_candidate_count"], (f["file"], len(own))
                for s, exp in ((own[0], f["reference_first_sample"]), (own[-1], f["reference_last_sample"])):
                    assert s["source_row"] == exp["source_row"] and abs(s["id_a"] - exp["id_a"]) <= 1e-14, (s, exp)
            profile = call("POST", "/profiles", json=dict(
                condition_id=condition, state_analysis_id=analysis["analysis_id"],
                selected_state_ids=[s["state_id"] for s in states],
                display_name=f"{condition} measured 2026-09-21 (verification)")).json()
            endpoint = f"/profiles/{profile['profile_id']}/revisions/1"
            call("POST", endpoint + "/publish", json=dict(
                reviewer="integration verification",
                review_note="Measured 2026-09-21 CSV through HTTP; software verification, not a device-quality claim."))
            export = call("GET", endpoint + "/export")
            names = zipfile.ZipFile(io.BytesIO(export.content)).namelist()
            row = dict(analysis_id=analysis["analysis_id"], profile_id=profile["profile_id"],
                       states=len(states), export_bytes=len(export.content), export_entries=names,
                       warnings=analysis.get("warnings"))
            if condition in args.experiment_conditions.split(","):
                config = json.loads((ROOT / "packages/contracts/fixtures/experiment-baseline.request.json").read_text())
                config["profile_refs"] = [dict(id=profile["profile_id"], revision=1)]
                config["engines"]["accuracy"] = args.engine
                config["checkpoint_id"] = args.checkpoint_id
                if args.adc_order != "none":
                    config["effects"]["adc"] = True
                    config["hardware"].update(adc_bits=args.adc_bits, adc_order=args.adc_order,
                                              range_policy=caps["hardware"]["range_policies"][0])
                exp = call("POST", "/experiments", json=config).json()
                wait_job(exp["job_id"])
                result = call("GET", "/experiments/" + exp["experiment_id"]).json()
                assert result["summary"]["completed"] == result["summary"]["requested"], result["summary"]
                assert result["effective_config"]["engines"]["accuracy"] == args.engine
                row["experiment"] = dict(
                    experiment_id=exp["experiment_id"], checkpoint_id=result["checkpoint_id"],
                    hardware=result["effective_config"]["hardware"],
                    runs={f"{r['kind']}|{r.get('pool')}|{r.get('mapping')}|{r['engine']}": r.get("accuracy")
                          for r in result["runs"]})
            report["conditions"][condition] = row
            print(json.dumps({condition: {k: v for k, v in row.items() if k != "export_entries"}}, ensure_ascii=False), flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
