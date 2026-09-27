"""Release guards: external PPA errors never masquerade as candidate costs."""
import subprocess
from unittest.mock import patch
import numpy as np
import pytest
from ctfm.adapters import neurosim_ppa as ppa, neurosim_build


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("engine", 1), OSError("missing binary"),
                                   neurosim_build.EngineBuildError("compiler failed")])
def test_external_ppa_failures_are_results_not_experiment_exceptions(tmp_path, error):
    base = {"blocking_reasons": [], "area_m2": None, "energy_j_per_inference": None, "latency_s_per_inference": None}
    with patch("ctfm.adapters.neurosim.ppa_result", return_value=base), patch.object(ppa, "engine_root_supports_two_planes", return_value=True), patch.object(ppa, "run_ppa", side_effect=error):
        result = ppa.assumed_proxy_result([], preset={}, hardware={"adc_order": "adc_then_subtract"},
                                         layers=[], codes=[], states=[], out_dir=tmp_path, root=tmp_path)
    assert result["status"] == "failed"
    assert result["failure_code"] == "engine_execution_error"
    assert result["area_m2"] is None and "known_total" not in result


def test_costs_belong_only_to_evaluated_candidates_hardware_runs():
    costs = {"candidate": {"candidate_id": "A1"}, "known_total": {"area_m2": 1}}
    assert ppa.ppa_for_run(costs, {"kind": "ALL", "candidate_id": "A1"}) == costs
    assert ppa.ppa_for_run(costs, {"kind": "ALL", "candidate_id": "A3"}) is None
    for kind in ("D0", "D1", "M0", "candidate"):
        assert ppa.ppa_for_run(costs, {"kind": kind, "candidate_id": "A1"}) is None


@pytest.mark.parametrize("fidelity,consistency", [
    ("failed", {"array_area_equals_slots": True}),
    ("passed", {"array_area_equals_slots": False}),
    ("passed", {"array_area_equals_slots": None}),
    ("passed", {"array_area_equals_slots": True, "adc_area_equals_slots": True, "adc_class_energy_equals_ledger": None}),
])
def test_unverified_engine_costs_are_withheld(tmp_path, fidelity, consistency):
    with patch.object(ppa.nd, "pool_bounds", return_value={}), patch.object(ppa.nd, "build_config_diff", return_value=({}, {})), patch.object(ppa.neurosim_build, "build", return_value={"binary": "engine"}), patch.object(ppa.nd, "stage_weights", return_value=([(1, 1)], "net", [])), patch.object(ppa.nd, "stage_sample", return_value=[]), patch.object(ppa.nd, "run_samples", return_value=[(0, "diagnostic", "", [])]), patch.object(ppa.nd, "aggregate", return_value={}), patch.object(ppa, "fidelity_checks", return_value={"status": fidelity}), patch.object(ppa.compose_mod, "compose", return_value={"consistency": consistency, "known_total": {"area_m2": 99}}):
        result = ppa.run_ppa([], [np.zeros((1, 1))], {}, {"adc_order": "adc_then_subtract", "tile_size": 64}, [], root=tmp_path, out_dir=tmp_path)
    assert result["status"] == "failed"
    assert result["failure_code"] == "model_verification_failed"
    assert "known_total" not in result and "composed" not in result
