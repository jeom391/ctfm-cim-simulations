"""Unit-level guard tests for scripts/measured_workflow.py's ADC-order comparison.

These do not talk to a running API/worker; they feed run_adc_order_comparison a
fake ``call``/``wait_job`` pair returning hand-built experiment results, so the
comparison-condition and checkpoint-identity checks themselves are exercised
without a real MNIST run. local_report/01_TASK_adc-order-comparison.md item 9:
a broken comparison must raise, never print a success report.

local_report/01_REVIEW_adc-order-comparison.md found three gaps the first pass
missed (R1/R2/R3, see the tests named after them below) -- this file's fakes
were rebuilt from the real experiment-baseline fixture so "both sides agree"
scenarios can be told apart from "both sides agree on the wrong thing".
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("measured_workflow", ROOT / "scripts/measured_workflow.py")
measured_workflow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measured_workflow)

PROFILE = {"profile_id": "11111111-1111-4111-8111-111111111111"}
CAPS = {"hardware": {"range_policies": ["validation_max_abs"]},
        "engines": {"torch_reference": {"available": True}, "aihwkit_ideal": {"available": False, "reason": "no wheel"}}}
BASE_REQUEST = json.loads((ROOT / "packages/contracts/fixtures/experiment-baseline.request.json").read_text())
BOUNDS = {"fc1": {"subtract_then_adc": 1.5, "adc_then_subtract": 2.0}, "fc2": {"subtract_then_adc": 0.8, "adc_then_subtract": 1.1}}


def _expected_config(order, *, adc_bits=6, engine="torch_reference", tile_size=64):
    """What run_adc_order_comparison actually sends for one side -- built the
    same way the function under test builds it, so a fake result can either
    honestly match it or deliberately deviate for a given guard test."""
    config = copy.deepcopy(BASE_REQUEST)
    config["profile_refs"] = [dict(id=PROFILE["profile_id"], revision=1)]
    config["engines"]["accuracy"] = engine
    config["effects"]["adc"] = True
    config["hardware"].update(adc_bits=adc_bits, tile_size=tile_size, adc_order=order, range_policy="validation_max_abs")
    return config


def _candidate_hardware(order, *, tile_size=64, adc_bits=6):
    return dict(tile_size=tile_size, adc_bits=adc_bits, adc_order=order, range_policy="validation_max_abs", preset_id=None)


def _candidate(order, calibration_suffix, *, tile_size=64, adc_bits=6, bounds=BOUNDS):
    hardware = dict(_candidate_hardware(order, tile_size=tile_size, adc_bits=adc_bits),
                    calibration_filename=f"candidate-1-calibration-{calibration_suffix}.json",
                    calibration_sha256=f"sha-{calibration_suffix}", bounds=bounds)
    return dict(candidate_id="candidate-1", profile_id=PROFILE["profile_id"], profile_revision=1, profile_hash="hash-x",
                pool="combined", mapping="fixed_reference", mapping_artifact="candidate-1-mapping.npz",
                mapping_errors=[{"layer": "fc1", "mae": 0.01}], hardware=hardware)


def _ok_run(run_id, kind, *, accuracy=0.99, engine="torch_reference", **extra):
    correct = round(accuracy * 10000)
    return dict(run_id=run_id, kind=kind, status="succeeded", accuracy=accuracy, correct=correct, n=10000,
               engine=engine, **extra)


def _result(order, checkpoint_id, *, accuracy, tile_size=64, adc_bits=6, engine="torch_reference", bounds=BOUNDS,
           effective_overrides=None, candidate_overrides=None, all_run_overrides=None, extra_runs=(),
           drop_run_ids=(), duplicate_run_id=None):
    """A fully-shaped fake experiment result for one ADC order, honest by
    default. Every guard test starts from this and deviates one thing."""
    config = _expected_config(order, adc_bits=adc_bits, engine=engine, tile_size=tile_size)
    effective = copy.deepcopy(config)
    effective.update(checkpoint_id=checkpoint_id, split_seed=config["seed"],
                     candidates=[_candidate(order, order[:3], tile_size=tile_size, adc_bits=adc_bits, bounds=bounds)])
    if candidate_overrides:
        effective["candidates"][0]["hardware"].update(candidate_overrides)
    if effective_overrides:
        effective.update(effective_overrides)
    all_run = _ok_run("candidate-1-array-0-year-0", "ALL", accuracy=accuracy, engine=engine, pool="combined",
                      mapping="fixed_reference", candidate_id="candidate-1",
                      hardware=_candidate_hardware(order, tile_size=tile_size, adc_bits=adc_bits),
                      adc={"fc1": {"saturation_ratio": 0.01}})
    if all_run_overrides:
        all_run.update(all_run_overrides)
    runs = [
        _ok_run("D0", "D0", accuracy=0.99, loss_vs_digital_pp=0.),
        _ok_run("D1", "D1", accuracy=0.99, loss_vs_digital_pp=0.01),
        _ok_run("candidate-1-M0", "M0", accuracy=0.98, engine=engine, validation_accuracy=0.98,
               loss_vs_mapped_pp=0., candidate_id="candidate-1"),
        all_run,
    ]
    runs = [r for r in runs if r["run_id"] not in drop_run_ids]
    runs += list(extra_runs)
    if duplicate_run_id is not None:
        runs.append(dict(_run_by_id_helper(runs, duplicate_run_id)))
    return dict(
        checkpoint_id=checkpoint_id, effective_config=effective,
        provenance=dict(training_epoch_losses=None,
                        checkpoint=dict(sha256="checkpoint-sha-fixed", checkpoint_id=checkpoint_id),
                        dataset_sha256="dataset-sha"),
        summary=dict(completed=4, requested=4),
        runs=runs,
    )


def _run_by_id_helper(runs, run_id):
    return next(r for r in runs if r["run_id"] == run_id)


class FakeAPI:
    """Two POST /experiments in sequence, keyed replies for their GET. Records
    every request so a test can check the second one actually reused the
    first's checkpoint_id rather than trusting the fake results alone."""
    def __init__(self, result_a, result_b):
        self.results = {"exp-a": result_a, "exp-b": result_b}
        self.next_id = iter(["exp-a", "exp-b", "exp-c", "exp-d"])
        self.requests = []

    def call(self, method, path, **kw):
        self.requests.append((method, path, kw))
        if method == "POST" and path == "/experiments":
            identifier = next(self.next_id)
            return _Response({"experiment_id": identifier, "job_id": "job-" + identifier})
        if method == "GET" and path.startswith("/experiments/"):
            return _Response(self.results[path.rsplit("/", 1)[-1]])
        raise AssertionError("unexpected call " + method + " " + path)

    def wait_job(self, identifier):
        return None

    @property
    def experiment_posts(self):
        return [kw["json"] for method, path, kw in self.requests if method == "POST" and path == "/experiments"]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _run_comparison(result_a, result_b, **kwargs):
    api = FakeAPI(result_a, result_b)
    report = measured_workflow.run_adc_order_comparison(api.call, api.wait_job, CAPS, PROFILE, adc_bits=6, **kwargs)
    return api, report


def test_matching_pair_reports_the_accuracy_delta_and_reuses_the_checkpoint():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965)
    api, report = _run_comparison(result_a, result_b)
    assert report["checkpoint_id"] == "ckpt-1"
    assert report["all_by_pool_mapping"][0]["accuracy_delta_pp"] == pytest.approx(100 * (0.96 - 0.965))
    assert report["calibration_bounds_by_candidate"]["candidate-1"] == BOUNDS
    posts = api.experiment_posts
    assert len(posts) == 2
    assert [p["hardware"]["adc_order"] for p in posts] == ["subtract_then_adc", "adc_then_subtract"]
    assert posts[0]["checkpoint_id"] is None  # first run creates the checkpoint
    assert posts[1]["checkpoint_id"] == "ckpt-1"  # second run explicitly reuses it
    assert posts[0]["profile_refs"] == posts[1]["profile_refs"] == [{"id": PROFILE["profile_id"], "revision": 1}]


def test_checkpoint_mismatch_between_the_two_runs_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = _result("adc_then_subtract", "ckpt-DIFFERENT", accuracy=0.965)
    with pytest.raises(SystemExit, match="checkpoint_id"):
        _run_comparison(result_a, result_b)


def test_a_diverging_order_independent_d0_run_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = copy.deepcopy(_result("adc_then_subtract", "ckpt-1", accuracy=0.965))
    result_b["runs"][0]["accuracy"] = 0.5
    result_b["runs"][0]["correct"] = 5000  # keep correct/n internally consistent so this fails for the RIGHT reason
    with pytest.raises(SystemExit, match="D0 differs"):
        _run_comparison(result_a, result_b)


def test_a_diverging_calibration_bound_is_rejected_not_averaged_away():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = copy.deepcopy(_result("adc_then_subtract", "ckpt-1", accuracy=0.965))
    result_b["effective_config"]["candidates"][0]["hardware"]["bounds"]["fc1"]["subtract_then_adc"] = 999.
    with pytest.raises(SystemExit, match="effective config differs"):
        _run_comparison(result_a, result_b)


# --- R1: a failed/missing/duplicate run must never be reported as a passing comparison ---

def test_r1_both_all_runs_failed_is_rejected_not_reported_as_a_comparison():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96,
                       all_run_overrides=dict(status="failed", accuracy=None, correct=None, n=None))
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965,
                       all_run_overrides=dict(status="failed", accuracy=None, correct=None, n=None))
    with pytest.raises(SystemExit, match="did not succeed"):
        _run_comparison(result_a, result_b)


def test_r1_missing_all_run_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96, drop_run_ids=("candidate-1-array-0-year-0",))
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965)
    with pytest.raises(SystemExit, match=r"expected exactly 1 ALL run"):
        _run_comparison(result_a, result_b)


def test_r1_duplicate_all_run_id_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96, duplicate_run_id="candidate-1-array-0-year-0")
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965)
    with pytest.raises(SystemExit, match=r"expected exactly 1 ALL run"):
        _run_comparison(result_a, result_b)


def test_r1_nonfinite_accuracy_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96, all_run_overrides=dict(accuracy=float("nan")))
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965)
    with pytest.raises(SystemExit, match="non-finite"):
        _run_comparison(result_a, result_b)


def test_r1_accuracy_inconsistent_with_correct_over_n_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96, all_run_overrides=dict(correct=1))
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965)
    with pytest.raises(SystemExit, match="does not match correct/n"):
        _run_comparison(result_a, result_b)


# --- R2: two responses agreeing with each other is not the same as honoring the request ---

def test_r2_effective_config_deviating_from_the_request_on_one_side_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96, tile_size=64)
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965, tile_size=128)
    with pytest.raises(SystemExit, match="does not match what was requested"):
        _run_comparison(result_a, result_b)


def test_r2_both_sides_agreeing_on_the_wrong_adc_bits_is_rejected():
    """The exact repro from the review: both fakes report adc_bits=3 while the
    function requested adc_bits=6 -- A==B is not enough, each side must match
    what was actually asked for."""
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96, adc_bits=3)
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965, adc_bits=3)
    with pytest.raises(SystemExit, match="does not match what was requested") as excinfo:
        _run_comparison(result_a, result_b)
    assert "hardware.adc_bits" in str(excinfo.value)


# --- R3: the candidate's own ADC order must match, not just the top-level field ---

def test_r3_candidate_adc_order_disagreeing_with_the_top_level_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965,
                       candidate_overrides=dict(adc_order="subtract_then_adc"))
    with pytest.raises(SystemExit, match="hardware.adc_order"):
        _run_comparison(result_a, result_b)


def test_r3_all_run_hardware_adc_order_disagreeing_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965,
                       all_run_overrides=dict(hardware=_candidate_hardware("subtract_then_adc")))
    with pytest.raises(SystemExit, match="carries hardware.adc_order"):
        _run_comparison(result_a, result_b)


# --- engine capability ---

def test_an_unavailable_engine_is_rejected_before_any_request():
    with pytest.raises(SystemExit, match="unavailable"):
        api = FakeAPI(None, None)
        measured_workflow.run_adc_order_comparison(api.call, api.wait_job, CAPS, PROFILE, adc_bits=6,
                                                   engine="aihwkit_ideal")
    assert api.requests == []  # rejected before making any HTTP call


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
