"""Read-only request validation and synthetic contract checks; no inference."""
import argparse
import copy
import json
import math
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

MAX_REQUESTED_RUNS = 2000


class ContractError(ValueError):
    def __init__(self, message, field=None, code='invalid_request'):
        super().__init__(message)
        self.field = field
        self.code = code


ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / "schemas/experiment-request.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate_request(request):
    """Structural validation only; profile/engine availability needs server checks."""
    pending = [(request, 0)]
    while pending:
        value, depth = pending.pop()
        # Valid requests are shallow; bound traversal before jsonschema formats
        # invalid values, which can also recurse while constructing an error.
        if depth > 32:
            raise ContractError("Request nesting exceeds the supported depth")
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError("Non-finite numbers are not allowed")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)

    VALIDATOR.validate(request)
    ids = [UUID(ref["id"]) for ref in request["profile_refs"]]
    if len(ids) != len(set(ids)):
        raise ContractError("Only one revision per profile is allowed in one request", "profile_refs")
    count = (len(ids) * len(request["pools"]) * len(request["mappings"])
             * request["arrays"] * len(request["years"]))
    if count > MAX_REQUESTED_RUNS:
        raise ContractError("Requested inference run count exceeds 2000", code="run_budget_exceeded")
    return count


def self_test():
    from jsonschema.exceptions import ValidationError
    fixtures = sorted((ROOT / "fixtures").glob("experiment-*.request.json"))
    for path in fixtures:
        validate_request(json.loads(path.read_text(encoding="utf-8")))
    baseline = json.loads((ROOT / "fixtures/experiment-baseline.request.json").read_text(encoding="utf-8"))
    invalid = []
    def case(section, key, value):
        request = copy.deepcopy(baseline)
        (request[section] if section else request)[key] = value
        invalid.append(request)
    case("effects", "c2c", True)
    case(None, "n_reprogram", 10)
    case(None, "arrays", 30)  # D2D off
    case(None, "years", [0, 1])  # Retention off
    case("effects", "adc", True)  # missing ADC controls
    case("hardware", "adc_bits", 6)  # ADC off
    case("engines", "ppa", "neurosim")
    case(None, "vds_v", 0.5)  # no measurement override
    case(None, "seed", -1)
    case(None, "years", [float("nan")])
    active = json.loads((ROOT / "fixtures/experiment-effects.request.json").read_text(encoding="utf-8"))
    for bits in [2, 9, 4.5]:
        request = copy.deepcopy(active)
        request["hardware"]["adc_bits"] = bits
        invalid.append(request)
    request = copy.deepcopy(active)
    request["hardware"]["tile_size"] = 100
    invalid.append(request)
    request = copy.deepcopy(active)
    request["profile_refs"].append({"id": request["profile_refs"][0]["id"], "revision": 2})
    invalid.append(request)
    request = copy.deepcopy(active)
    request.update(arrays=100, pools=["combined", "ltp", "ltd", "common"],
                   mappings=["fixed_reference", "pair_search"], years=[0, 1, 5])
    invalid.append(request)
    for request in invalid:
        try:
            validate_request(request)
        except (ValueError, ValidationError):
            continue
        raise AssertionError(f"Invalid request was accepted: {request}")
    for bits in range(3, 9):
        for size in [64, 128, 256]:
            request = copy.deepcopy(active)
            request["hardware"].update(adc_bits=bits, tile_size=size)
            assert validate_request(request) == 90
    print(f"PASS: {len(fixtures)} fixtures, {len(invalid)} rejection cases, 18 ADC/tile combinations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, nargs="?")
    args = parser.parse_args()
    if args.request:
        count = validate_request(json.loads(args.request.read_text(encoding="utf-8")))
        print(f"Valid shape: {count} requested runs; server capability/data checks still required")
    else:
        self_test()
