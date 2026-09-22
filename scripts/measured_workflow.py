"""Run the running application end to end on the shared, hash-pinned LTP/LTD CSVs.

upload -> preview -> pulse_states analysis -> profile -> publish -> export ZIP
-> MNIST experiment, for every condition in the 2026-09-21 manifest. Unlike
smoke_workflow.py this uses measured files, so it checks the production parser
through the HTTP boundary, not only in-process.

``--compare-adc-orders`` additionally runs the single selected condition's
published profile revision through two experiments that share one checkpoint
and differ only in hardware.adc_order (subtract_then_adc vs adc_then_subtract),
verifying the comparison conditions actually held (same profile revision, same
checkpoint id and weights, identical effective config other than the ADC order
and its derived calibration, identical D0/D1/M0) before reporting any ALL
accuracy or ADC-diagnostic delta. It never prints a report if a comparison
condition or the checkpoint identity is violated; it raises instead
(docs/spec/08-hardware-baseline.md section 4, local_report/01_TASK item 9).
"""
import argparse
import hashlib
import io
import json
import math
import time
import zipfile
from copy import deepcopy
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/reference/ltp-ltd-2026-09-21"
ADC_ORDERS = ("subtract_then_adc", "adc_then_subtract")


def _normalize_effective_config(effective):
    """Zero the fields ADC order is allowed to move so the rest can be compared
    for exact equality. Calibration bounds are NOT zeroed: ``calibrate()``
    (ctfm.simulation.torch_runner) computes both orders' nominal ranges in one
    pass over the same mapped weights, so for one shared checkpoint/profile the
    bounds are expected to be bit-identical -- this is a consistency check
    between the two runs, not a forced/hard-coded number."""
    normalized = deepcopy(effective)
    normalized["hardware"]["adc_order"] = None
    for candidate in normalized["candidates"]:
        candidate["hardware"]["adc_order"] = None
        candidate["hardware"]["calibration_filename"] = None
        candidate["hardware"]["calibration_sha256"] = None
    return normalized


def _normalize_provenance(provenance):
    """training_epoch_losses is populated only by whichever run trains the
    shared checkpoint; the run that reuses it legitimately has none."""
    normalized = deepcopy(provenance)
    normalized["training_epoch_losses"] = None
    return normalized


def _diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b), key=str):
            out += _diff(a.get(key, "<missing>"), b.get(key, "<missing>"), f"{path}.{key}" if path else str(key))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [{"path": path, "a": a, "b": b}]


def _run_by_id(result, run_id):
    matches = [r for r in result["runs"] if r["run_id"] == run_id]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one run {run_id!r}, found {len(matches)}")
    return matches[0]


def _assert_matching_runs(result_a, result_b, run_id, keys):
    a, b = _run_by_id(result_a, run_id), _run_by_id(result_b, run_id)
    mismatches = {k: (a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)}
    if mismatches:
        raise SystemExit(f"{run_id} differs between ADC orders on a supposedly order-independent run: {mismatches}")
    return {k: a.get(k) for k in keys}


def _finite_unit_accuracy(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def _require_ok_runs(result, kind, expected_count, *, engine=None):
    """Reject a comparison built on missing/duplicate/failed/skipped runs or
    null/nonfinite accuracy -- review R1: completed==requested alone does not
    guarantee the specific runs a comparison needs actually succeeded."""
    matches = [r for r in result["runs"] if r["kind"] == kind]
    if len(matches) != expected_count:
        raise SystemExit(f"expected exactly {expected_count} {kind} run(s), found {len(matches)}: "
                         + json.dumps([r.get("run_id") for r in matches]))
    run_ids = [r["run_id"] for r in matches]
    if len(set(run_ids)) != len(run_ids):
        raise SystemExit(f"duplicate run_id among {kind} runs: {run_ids}")
    for r in matches:
        if r.get("status") != "succeeded":
            raise SystemExit(f"{kind} run {r.get('run_id')!r} did not succeed: status={r.get('status')!r}")
        if not _finite_unit_accuracy(r.get("accuracy")):
            raise SystemExit(f"{kind} run {r.get('run_id')!r} has a non-finite/out-of-range accuracy: {r.get('accuracy')!r}")
        n, correct = r.get("n"), r.get("correct")
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            raise SystemExit(f"{kind} run {r.get('run_id')!r} has an invalid n: {n!r}")
        if not isinstance(correct, int) or isinstance(correct, bool) or not 0 <= correct <= n:
            raise SystemExit(f"{kind} run {r.get('run_id')!r} has an invalid correct count: {correct!r}")
        if abs(correct / n - r["accuracy"]) > 1e-9:
            raise SystemExit(f"{kind} run {r.get('run_id')!r} accuracy does not match correct/n")
        if engine is not None and r.get("engine") != engine:
            raise SystemExit(f"{kind} run {r.get('run_id')!r} used engine {r.get('engine')!r}, requested {engine!r}")
    return matches


def _check_effective_matches_request(config, order, effective):
    """Review R2/R3: two responses agreeing with each other is not the same as
    either of them honoring what was actually requested. Compares the exact
    request dict built for this run (not a round-tripped/server-normalized
    copy) against effective_config, including each candidate's own ADC order
    -- not just the top-level field a normalization pass could paper over."""
    hardware = effective["hardware"]
    request_hardware = config["hardware"]
    checks = [
        ("model_id", effective.get("model_id"), config["model_id"]),
        ("schema_version", effective.get("schema_version"), config["schema_version"]),
        ("pools", effective.get("pools"), config["pools"]),
        ("mappings", effective.get("mappings"), config["mappings"]),
        ("effects", effective.get("effects"), config["effects"]),
        ("arrays", effective.get("arrays"), int(config["arrays"])),
        ("n_reprogram", effective.get("n_reprogram"), int(config["n_reprogram"])),
        ("years", effective.get("years"), config["years"]),
        ("seed", effective.get("seed"), int(config["seed"])),
        ("engines", effective.get("engines"), config["engines"]),
        ("profile_refs", effective.get("profile_refs"), config["profile_refs"]),
        ("hardware.tile_size", hardware.get("tile_size"), request_hardware["tile_size"]),
        ("hardware.adc_bits", hardware.get("adc_bits"), request_hardware["adc_bits"]),
        ("hardware.range_policy", hardware.get("range_policy"), request_hardware["range_policy"]),
        ("hardware.preset_id", hardware.get("preset_id"), request_hardware["preset_id"]),
        ("hardware.adc_order", hardware.get("adc_order"), order),
    ]
    mismatches = [{"field": name, "effective": actual, "requested": expected}
                 for name, actual, expected in checks if actual != expected]
    if mismatches:
        raise SystemExit(f"{order}: effective config does not match what was requested: "
                         + json.dumps(mismatches, ensure_ascii=False))
    for candidate in effective.get("candidates", []):
        candidate_hardware = candidate["hardware"]
        if candidate_hardware.get("adc_order") != order:
            raise SystemExit(f"{order}: candidate {candidate.get('candidate_id')!r} hardware.adc_order="
                             f"{candidate_hardware.get('adc_order')!r} does not match the requested order")
        for key in ("tile_size", "adc_bits", "range_policy", "preset_id"):
            if candidate_hardware.get(key) != hardware.get(key):
                raise SystemExit(f"{order}: candidate {candidate.get('candidate_id')!r} hardware.{key}="
                                 f"{candidate_hardware.get(key)!r} does not match effective_config.hardware.{key}={hardware.get(key)!r}")


def run_adc_order_comparison(call, wait_job, caps, profile, *, adc_bits, checkpoint_id=None, engine="torch_reference"):
    """Two experiments on one published profile revision, sharing one
    checkpoint, differing only in hardware.adc_order. Returns a report dict, or
    raises SystemExit before returning anything if a comparison condition, the
    checkpoint identity, or an order-independent run (D0/D1/M0) is violated."""
    if not caps["engines"].get(engine, {}).get("available"):
        raise SystemExit(f"{engine} unavailable for the ADC-order comparison: {caps['engines'].get(engine)}")
    base = json.loads((ROOT / "packages/contracts/fixtures/experiment-baseline.request.json").read_text())
    base["profile_refs"] = [dict(id=profile["profile_id"], revision=1)]
    base["engines"]["accuracy"] = engine
    base["effects"]["adc"] = True
    base["hardware"].update(adc_bits=adc_bits, range_policy=caps["hardware"]["range_policies"][0])
    if len(base["pools"]) != 1 or len(base["mappings"]) != 1:
        raise SystemExit("this comparison expects exactly one pool/mapping candidate; "
                         "the baseline fixture changed shape")

    def run(order, checkpoint):
        config = deepcopy(base)
        config["hardware"]["adc_order"] = order
        config["checkpoint_id"] = checkpoint
        exp = call("POST", "/experiments", json=config).json()
        wait_job(exp["job_id"])
        result = call("GET", "/experiments/" + exp["experiment_id"]).json()
        if result["summary"]["completed"] != result["summary"]["requested"]:
            raise SystemExit(f"{order}: experiment did not complete fully: {result['summary']}")
        _check_effective_matches_request(config, order, result["effective_config"])
        _require_ok_runs(result, "D0", 1, engine="torch_reference")
        _require_ok_runs(result, "D1", 1, engine="torch_reference")
        _require_ok_runs(result, "M0", 1, engine=engine)
        for run_record in _require_ok_runs(result, "ALL", int(config["arrays"]) * len(config["years"]), engine=engine):
            if run_record["hardware"]["adc_order"] != order:
                raise SystemExit(f"{order}: ALL run {run_record['run_id']!r} carries hardware.adc_order="
                                 f"{run_record['hardware']['adc_order']!r} instead of the requested order")
        return exp["experiment_id"], result

    experiment_a, result_a = run(ADC_ORDERS[0], checkpoint_id)
    shared_checkpoint = checkpoint_id or result_a["checkpoint_id"]
    if not shared_checkpoint:
        raise SystemExit("first run produced no checkpoint id to share")
    experiment_b, result_b = run(ADC_ORDERS[1], shared_checkpoint)

    if result_a["checkpoint_id"] != shared_checkpoint or result_b["checkpoint_id"] != shared_checkpoint:
        raise SystemExit("the two runs did not end up on the same checkpoint_id")

    config_diff = _diff(_normalize_effective_config(result_a["effective_config"]),
                        _normalize_effective_config(result_b["effective_config"]))
    if config_diff:
        raise SystemExit("effective config differs beyond the allowed ADC-order fields: "
                         + json.dumps(config_diff, ensure_ascii=False))

    provenance_diff = _diff(_normalize_provenance(result_a["provenance"]), _normalize_provenance(result_b["provenance"]))
    if provenance_diff:
        raise SystemExit("provenance differs beyond the expected training-log gap: "
                         + json.dumps(provenance_diff, ensure_ascii=False))

    d0 = _assert_matching_runs(result_a, result_b, "D0", ("accuracy", "correct", "n", "loss_vs_digital_pp"))
    d1 = _assert_matching_runs(result_a, result_b, "D1", ("accuracy", "correct", "n", "loss_vs_digital_pp"))
    m0_run_ids = sorted({r["run_id"] for r in result_a["runs"] if r["kind"] == "M0"})
    if not m0_run_ids or m0_run_ids != sorted({r["run_id"] for r in result_b["runs"] if r["kind"] == "M0"}):
        raise SystemExit("M0 candidate identities differ between the two ADC-order runs")
    m0 = {run_id: _assert_matching_runs(result_a, result_b, run_id,
                                        ("accuracy", "correct", "n", "validation_accuracy", "loss_vs_digital_pp", "loss_vs_mapped_pp"))
          for run_id in m0_run_ids}

    all_a = {r["run_id"]: r for r in result_a["runs"] if r["kind"] == "ALL"}
    all_b = {r["run_id"]: r for r in result_b["runs"] if r["kind"] == "ALL"}
    if set(all_a) != set(all_b):
        raise SystemExit("ALL run identities differ between the two ADC-order runs")
    all_comparison = []
    for run_id in sorted(all_a):
        ra, rb = all_a[run_id], all_b[run_id]
        aa, ab = ra.get("accuracy"), rb.get("accuracy")
        all_comparison.append(dict(
            run_id=run_id, pool=ra["pool"], mapping=ra["mapping"],
            subtract_then_adc=dict(status=ra["status"], accuracy=aa, adc=ra.get("adc")),
            adc_then_subtract=dict(status=rb["status"], accuracy=ab, adc=rb.get("adc")),
            accuracy_delta_pp=100*(aa-ab) if aa is not None and ab is not None else None))

    bounds_by_candidate = {c["candidate_id"]: c["hardware"]["bounds"] for c in result_a["effective_config"]["candidates"]}

    return dict(
        experiment_ids={"subtract_then_adc": experiment_a, "adc_then_subtract": experiment_b},
        checkpoint_id=shared_checkpoint, checkpoint_sha256=result_a["provenance"]["checkpoint"]["sha256"],
        profile_id=profile["profile_id"], profile_revision=1, engine=engine,
        adc_bits=adc_bits, tile_size=base["hardware"]["tile_size"],
        calibration_bounds_by_candidate=bounds_by_candidate,
        calibration_note=("bounds are computed for both ADC orders in one nominal pass over the shared mapped "
                          "weights (ctfm.simulation.torch_runner.calibrate); identical bounds above are therefore "
                          "expected for this single-checkpoint comparison, not a forced number"),
        d0=d0, d1=d1, m0=m0, all_by_pool_mapping=all_comparison,
        scope_note="single shared-checkpoint comparison; not evidence of general ADC-order or device-condition superiority")


def _publish_condition(call, wait_job, manifest, condition):
    """Upload -> analyze -> publish once for ``condition``; returns (profile, row)."""
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
    return profile, row


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
    parser.add_argument("--compare-adc-orders", action="store_true",
                        help="ignore --adc-order/--experiment-conditions; run the single --conditions "
                             "entry's profile through both ADC orders on one shared checkpoint and verify "
                             "the comparison conditions instead of running the default single experiment")
    args = parser.parse_args()
    if args.compare_adc_orders and "," in args.conditions:
        raise SystemExit("--compare-adc-orders requires exactly one --conditions entry")
    if args.compare_adc_orders and args.engine != "torch_reference":
        raise SystemExit("--compare-adc-orders only verifies torch_reference; "
                         f"--engine {args.engine!r} is not supported by this comparison")
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
            profile, row = _publish_condition(call, wait_job, manifest, condition)
            if args.compare_adc_orders:
                row["adc_order_comparison"] = run_adc_order_comparison(
                    call, wait_job, caps, profile, adc_bits=args.adc_bits, checkpoint_id=args.checkpoint_id,
                    engine=args.engine)
            elif condition in args.experiment_conditions.split(","):
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
