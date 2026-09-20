"""Synthetic contract checks; no measured profiles or inference."""
import copy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ctfm_contracts.check_experiment_contract import validate_request
from ctfm_contracts.models import ExperimentRequest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages/contracts"


def fixture(name="baseline"):
    return json.loads((CONTRACTS / f"fixtures/experiment-{name}.request.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,count", [("baseline", 1), ("effects", 90)])
def test_request_round_trip_preserves_all_selected_values(name, count):
    request = fixture(name)
    parsed = ExperimentRequest.model_validate(request)
    assert parsed.model_dump(mode="json") == request
    assert validate_request(parsed.root) == count


@pytest.mark.parametrize("bits", range(3, 9))
@pytest.mark.parametrize("tile", [64, 128, 256])
@pytest.mark.parametrize("order", ["subtract_then_adc", "adc_then_subtract"])
def test_each_adc_choice_survives_validation(bits, tile, order):
    request = fixture("effects")
    request["hardware"].update(adc_bits=bits, tile_size=tile, adc_order=order)
    assert ExperimentRequest.model_validate(request).root["hardware"] == {
        "adc_bits": bits, "tile_size": tile, "adc_order": order,
        "range_policy": "validation_max_abs", "preset_id": None,
    }


def test_a_v1_1_request_is_refused_rather_than_reinterpreted():
    """tile_size=null used to mean 'ADC off'; under 1.2.0 it is a physical size."""
    from ctfm_contracts.check_experiment_contract import ContractError
    request = fixture()
    request["schema_version"] = "1.1.0"
    with pytest.raises(ContractError) as error:
        validate_request(request)
    assert error.value.code == "schema_migration_required"
    assert error.value.field == "schema_version"


def test_the_adc_order_is_not_applicable_when_the_converter_is_off():
    request = fixture()
    assert request["effects"]["adc"] is False
    assert request["hardware"]["adc_order"] is None
    # The array is still physical with the ADC off, so its size stays explicit.
    assert request["hardware"]["tile_size"] in (64, 128, 256)
    request["hardware"]["adc_order"] = "subtract_then_adc"
    with pytest.raises(ValidationError):
        ExperimentRequest.model_validate(request)


@pytest.mark.parametrize("path,value", [
    (("arrays",), 30), (("arrays",), True), (("seed",), "123"),
    (("seed",), True), (("seed",), -1), (("n_reprogram",), True),
    (("n_reprogram",), 2), (("years",), [0, 1]),
    (("years",), [0, math.nan]), (("years",), [0, math.inf]),
    (("effects", "c2c"), True), (("effects", "adc"), True),
    (("effects", "d2d"), "false"), (("hardware", "adc_bits"), 6),
    (("hardware", "tile_size"), None), (("hardware", "adc_order"), "subtract"),
    (("engines", "ppa"), "neurosim"), (("vds_v",), 0.5),
    (("profile_refs",), [{"id": "not-a-uuid", "revision": 1}]),
])
def test_invalid_values_are_rejected_without_coercion(path, value):
    request = fixture()
    target = request
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        ExperimentRequest.model_validate(request)


def test_integral_json_numbers_keep_existing_schema_semantics():
    request = fixture()
    request.update(arrays=1.0, seed=20260917.0, n_reprogram=1.0)
    assert ExperimentRequest.model_validate(request).model_dump(mode="json") == request


def test_same_profile_uuid_cannot_bypass_duplicate_check_with_case():
    request = fixture()
    profile_id = "abcdefab-abcd-4abc-8abc-abcdefabcdef"
    request["profile_refs"] = [
        {"id": profile_id, "revision": 1},
        {"id": profile_id.upper(), "revision": 2},
    ]
    with pytest.raises(ValueError, match="revision"):
        validate_request(request)


def test_run_budget_includes_all_requested_candidates():
    request = fixture("effects")
    request.update(
        profile_refs=[{"id": f"00000000-0000-4000-8000-{i:012d}", "revision": 1} for i in range(5)],
        pools=["combined", "ltp", "ltd", "common"],
        mappings=["fixed_reference", "pair_search"],
        arrays=10, years=[0, 1, 2, 3, 4],
    )
    assert validate_request(request) == 2000
    ExperimentRequest.model_validate(request)
    request["arrays"] = 11
    with pytest.raises(ValidationError):
        ExperimentRequest.model_validate(request)


def test_pydantic_exports_authoritative_shape_including_conditional_rules():
    original = json.loads((CONTRACTS / "schemas/experiment-request.schema.json").read_text(encoding="utf-8"))
    exported = ExperimentRequest.model_json_schema()
    for key in ("properties", "required", "additionalProperties", "allOf"):
        assert exported[key] == original[key]
    validator = Draft202012Validator(exported, format_checker=FormatChecker())
    assert validator.is_valid(fixture("effects"))
    invalid = fixture()
    invalid["hardware"]["adc_bits"] = 6
    assert not validator.is_valid(invalid)


def test_parsed_deep_json_is_a_validation_error_not_a_recursion_crash():
    value = 0
    for _ in range(960):
        value = [value]
    with pytest.raises(ValidationError):
        ExperimentRequest.model_validate(value)
