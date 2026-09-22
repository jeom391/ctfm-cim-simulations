"""Exercise the C2C-on request path (schema_version 1.3.0) against the running
application: a synthetic-profile smoke run, plus (if a stored A1 profile and
checkpoint are given) a real torch_reference request that reuses them without
retraining. Backend-only per local_report/04_TASK_c2c-backend.md; the web
input screen is out of scope.
"""
import argparse
import json
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--engine", default="torch_reference", choices=("torch_reference", "aihwkit_ideal"))
    parser.add_argument("--profile-id", default=None, help="reuse a published profile instead of a synthetic one")
    parser.add_argument("--profile-revision", type=int, default=1)
    parser.add_argument("--checkpoint-id", default=None, help="reuse a checkpoint across engines/requests")
    parser.add_argument("--cv-percent", type=float, default=5)
    parser.add_argument("--n-reprogram", type=int, default=2)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url + "/api/v1", timeout=60) as client:
        def get(path):
            r = client.get(path); r.raise_for_status(); return r.json()

        def post(path, payload):
            r = client.post(path, json=payload); r.raise_for_status(); return r.json()

        def wait_job(identifier):
            deadline = time.monotonic() + args.timeout; last = None
            while time.monotonic() < deadline:
                job = get("/jobs/" + identifier)
                state = (job["state"], job["stage"], job["completed"], job["total"])
                if state != last:
                    print(json.dumps({"job_id": identifier, "progress": state}), flush=True); last = state
                if job["state"] == "succeeded": return
                if job["state"] in ("failed", "cancelled"): raise RuntimeError(json.dumps(job))
                time.sleep(1)
            raise TimeoutError("worker did not complete within the smoke timeout")

        caps = get("/capabilities")
        assert caps["schema_version"] == "1.3.0", caps["schema_version"]
        assert caps["effects"]["c2c"]["available"], caps["effects"]["c2c"]
        engine_cap = caps["engines"][args.engine]
        if not engine_cap["available"]:
            raise SystemExit(f"{args.engine} unavailable: {engine_cap}")

        if args.profile_id:
            profile_id, revision, source = args.profile_id, args.profile_revision, "reused"
        else:
            for direction in ("ltp", "ltd"):
                rows = ["synthetic fixture; not measured", "time,current,gate"]
                for i, value in enumerate((1e-6, 2e-6, 3e-6) if direction == "ltp" else (3e-6, 2e-6, 1e-6)):
                    t = 6 + i * 5
                    gate = -6 if direction == "ltp" else 6
                    rows += [f"{t},{value},0", f"{t+1},{value},0", f"{t+2},0,{gate/6}", f"{t+3},0,{gate}"]
                rows += ["30,0.000001,0", "31,0.000001,0"]
                data = ("\n".join(rows) + "\n").encode()
                r = client.post("/files", files={"files": (direction + "-c2c-smoke.csv", data)})
                r.raise_for_status()
                file_id = r.json()["files"][0]["file_id"]
                if direction == "ltp":
                    inputs = []
                inputs.append(dict(file_id=file_id, column_mapping=dict(time_s="time", id_a="current", vgs_v="gate"),
                                   units=dict(time_s="s", id_a="A", vgs_v="V"), condition_id="A1",
                                   device_id="SYNTHETIC-C2C-SMOKE", direction=direction, vds_v=.1, read_vgs_v=0))
            queued = post("/analyses", dict(kind="pulse_states", inputs=inputs, settings={}))
            wait_job(queued["job_id"]); analysis = get("/analyses/" + queued["analysis_id"])
            created = post("/profiles", dict(condition_id="A1", state_analysis_id=analysis["analysis_id"],
                                             selected_state_ids=[s["state_id"] for s in analysis["states"]],
                                             display_name="SYNTHETIC C2C SMOKE"))
            profile_id = created["profile_id"]
            published = post(f"/profiles/{profile_id}/revisions/1/publish",
                             dict(reviewer="automated c2c smoke",
                                 review_note="Synthetic fixture states only; verifies the C2C wiring, not device data."))
            revision = published["revision"]; source = "synthetic"

        config = dict(
            schema_version="1.3.0",
            profile_refs=[dict(id=profile_id, revision=revision,
                               c2c=dict(cv_percent=args.cv_percent, source="manual_assumption"))],
            model_id="mnist_mlp_v1", checkpoint_id=args.checkpoint_id,
            pools=["combined"], mappings=["fixed_reference"],
            effects=dict(d2d=False, retention=False, adc=False, c2c=True),
            arrays=1, n_reprogram=args.n_reprogram, years=[0], seed=20260917,
            hardware=dict(tile_size=64, adc_bits=None, adc_order=None, range_policy=None, preset_id=None),
            engines=dict(accuracy=args.engine, ppa="off"))
        experiment = post("/experiments", config); wait_job(experiment["job_id"])
        result = get("/experiments/" + experiment["experiment_id"])
        assert result["summary"]["completed"] == result["summary"]["requested"], result["summary"]
        assert result["effective_config"]["engines"]["accuracy"] == args.engine, "engine silently substituted"
        assert result["schema_version"] == "1.3.0"
        all_runs = [r for r in result["runs"] if r["kind"] == "ALL"]
        assert len(all_runs) == args.n_reprogram, (len(all_runs), args.n_reprogram)
        seeds = [set(v["seed"] for v in r["c2c_diagnostics"].values()) for r in all_runs]
        assert all(s.isdisjoint(t) for i, s in enumerate(seeds) for t in seeds[i + 1:]), "records were not independent"
        print(json.dumps({
            "source": source, "profile_id": profile_id, "revision": revision,
            "checkpoint_id": result["checkpoint_id"], "checkpoint_reused": args.checkpoint_id is not None,
            "requested_engine": args.engine, "engines_used": sorted({r["engine"] for r in result["runs"]}),
            "cv_percent": args.cv_percent, "n_reprogram": args.n_reprogram,
            "d0": result["runs"][0]["accuracy"], "d1": result["runs"][1]["accuracy"],
            "m0": next(r["accuracy"] for r in result["runs"] if r["kind"] == "M0"),
            "all_by_record": [dict(run_id=r["run_id"], accuracy=r["accuracy"],
                                   c2c_seeds=sorted(v["seed"] for v in r["c2c_diagnostics"].values()))
                              for r in all_runs],
            "array_statistics": result["summary"]["array_statistics"],
            "device_evidence": "synthetic_only" if source == "synthetic" else "reused_measured_profile_and_checkpoint_no_retrain",
        }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
