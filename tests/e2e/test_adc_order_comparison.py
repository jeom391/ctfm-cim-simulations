"""Unit-level guard tests for scripts/measured_workflow.py's ADC-order comparison.

These do not talk to a running API/worker; they feed run_adc_order_comparison a
fake ``call``/``wait_job`` pair returning hand-built experiment results, so the
comparison-condition and checkpoint-identity checks themselves are exercised
without a real MNIST run. local_report/01_TASK_adc-order-comparison.md item 9:
a broken comparison must raise, never print a success report.
"""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("measured_workflow", ROOT / "scripts/measured_workflow.py")
measured_workflow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measured_workflow)


def _hardware(order, tile_size=64, adc_bits=6):
    return dict(tile_size=tile_size, adc_bits=adc_bits, adc_order=order, range_policy="validation_max_abs", preset_id=None)


def _candidate(order, calibration_suffix, bounds):
    return dict(candidate_id="candidate-1", profile_id="11111111-1111-4111-8111-111111111111", profile_revision=1,
                profile_hash="hash-x", pool="combined", mapping="fixed_reference",
                mapping_artifact="candidate-1-mapping.npz", mapping_errors=[{"layer": "fc1", "mae": 0.01}],
                hardware=dict(_hardware(order), calibration_filename=f"candidate-1-calibration-{calibration_suffix}.json",
                             calibration_sha256=f"sha-{calibration_suffix}", bounds=bounds))


BOUNDS = {"fc1": {"subtract_then_adc": 1.5, "adc_then_subtract": 2.0}, "fc2": {"subtract_then_adc": 0.8, "adc_then_subtract": 1.1}}


def _result(order, checkpoint_id, *, accuracy, tile_size=64):
    common_run = lambda run_id, kind, **extra: dict(run_id=run_id, kind=kind, status="succeeded",
                                                     accuracy=0.99, correct=9900, n=10000, loss_vs_digital_pp=0., **extra)
    return dict(
        checkpoint_id=checkpoint_id,
        effective_config=dict(hardware=_hardware(order, tile_size=tile_size),
                              candidates=[_candidate(order, order[:3], BOUNDS)]),
        provenance=dict(training_epoch_losses=None,
                        checkpoint=dict(sha256="checkpoint-sha-fixed", checkpoint_id=checkpoint_id),
                        dataset_sha256="dataset-sha"),
        summary=dict(completed=4, requested=4),
        runs=[
            common_run("D0", "D0"),
            common_run("D1", "D1"),
            common_run("candidate-1-M0", "M0", validation_accuracy=0.98, loss_vs_mapped_pp=0.),
            dict(run_id="candidate-1-array-0-year-0", kind="ALL", status="succeeded", pool="combined",
                mapping="fixed_reference", accuracy=accuracy, adc={"fc1": {"saturation_ratio": 0.01}}),
        ],
    )


class FakeAPI:
    """Two POST /experiments in sequence, keyed replies for their GET."""
    def __init__(self, result_a, result_b):
        self.results = {"exp-a": result_a, "exp-b": result_b}
        self.next_id = iter(["exp-a", "exp-b", "exp-c", "exp-d"])

    def call(self, method, path, **kw):
        if method == "POST" and path == "/experiments":
            identifier = next(self.next_id)
            return _Response({"experiment_id": identifier, "job_id": "job-" + identifier})
        if method == "GET" and path.startswith("/experiments/"):
            return _Response(self.results[path.rsplit("/", 1)[-1]])
        raise AssertionError("unexpected call " + method + " " + path)

    def wait_job(self, identifier):
        return None


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


CAPS = {"hardware": {"range_policies": ["validation_max_abs"]}}
PROFILE = {"profile_id": "11111111-1111-4111-8111-111111111111"}


def test_matching_pair_reports_the_accuracy_delta():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965)
    api = FakeAPI(result_a, result_b)
    report = measured_workflow.run_adc_order_comparison(api.call, api.wait_job, CAPS, PROFILE, adc_bits=6)
    assert report["checkpoint_id"] == "ckpt-1"
    assert report["all_by_pool_mapping"][0]["accuracy_delta_pp"] == pytest.approx(100 * (0.96 - 0.965))
    assert report["calibration_bounds_by_candidate"]["candidate-1"] == BOUNDS


def test_checkpoint_mismatch_between_the_two_runs_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = _result("adc_then_subtract", "ckpt-DIFFERENT", accuracy=0.965)
    api = FakeAPI(result_a, result_b)
    with pytest.raises(SystemExit, match="checkpoint_id"):
        measured_workflow.run_adc_order_comparison(api.call, api.wait_job, CAPS, PROFILE, adc_bits=6)


def test_an_unrelated_config_difference_is_rejected_not_silently_allowed():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96, tile_size=64)
    result_b = _result("adc_then_subtract", "ckpt-1", accuracy=0.965, tile_size=128)
    api = FakeAPI(result_a, result_b)
    with pytest.raises(SystemExit, match="effective config differs"):
        measured_workflow.run_adc_order_comparison(api.call, api.wait_job, CAPS, PROFILE, adc_bits=6)


def test_a_diverging_order_independent_d0_run_is_rejected():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = copy.deepcopy(_result("adc_then_subtract", "ckpt-1", accuracy=0.965))
    result_b["runs"][0]["accuracy"] = 0.5  # D0 must never depend on ADC order
    api = FakeAPI(result_a, result_b)
    with pytest.raises(SystemExit, match="D0 differs"):
        measured_workflow.run_adc_order_comparison(api.call, api.wait_job, CAPS, PROFILE, adc_bits=6)


def test_a_diverging_calibration_bound_is_rejected_not_averaged_away():
    result_a = _result("subtract_then_adc", "ckpt-1", accuracy=0.96)
    result_b = copy.deepcopy(_result("adc_then_subtract", "ckpt-1", accuracy=0.965))
    result_b["effective_config"]["candidates"][0]["hardware"]["bounds"]["fc1"]["subtract_then_adc"] = 999.
    api = FakeAPI(result_a, result_b)
    with pytest.raises(SystemExit, match="effective config differs"):
        measured_workflow.run_adc_order_comparison(api.call, api.wait_job, CAPS, PROFILE, adc_bits=6)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
