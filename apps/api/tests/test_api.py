"""HTTP boundary checks against the actual ASGI application."""
import json
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from ctfm_api.app import create_app
app = create_app()

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return 'asyncio'


@pytest.fixture(scope="module")
async def client(tmp_path_factory):
    app.state.store = __import__("ctfm_api.storage",fromlist=["Store"]).Store(tmp_path_factory.mktemp("api-boundary"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as value:
        yield value


def baseline():
    return json.loads((ROOT / "packages/contracts/fixtures/experiment-baseline.request.json").read_text(encoding="utf-8"))


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert set(error) == {"code", "message", "field", "details", "request_id"}
    assert error["code"] == code
    UUID(error["request_id"])
    assert response.headers["X-Request-ID"] == error["request_id"]
    return error


async def test_capabilities_never_advertise_unimplemented_execution(client):
    response = await client.get("/api/v1/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.4.0"
    for name in ("aihwkit_ideal", "neurosim"):
        if not payload["engines"][name]["available"]:
            assert payload["engines"][name]["reason"]
    # C2C is a manual-assumption calculation (docs/completion-plan-2026-09-21.md
    # P2), not a measured effect, so its availability tracks torch like ADC does.
    assert payload["effects"]["c2c"]["available"] == payload["engines"]["torch_reference"]["available"]
    assert payload["effects"]["adc"]["available"] == payload["engines"]["torch_reference"]["available"]
    assert payload["hardware"]["adc_bits"] == [3, 4, 5, 6, 7, 8]
    assert payload["hardware"]["tile_sizes"] == [64]
    assert payload["hardware"]["adc_orders"] == ["adc_then_subtract"]
    assert payload["hardware"]["ppa_tile_sizes"] == []
    assert not payload["engines"]["neurosim"]["available"]
    assert all(row["tile_size"] == 64 and row["adc_order"] == "adc_then_subtract"
               for row in payload["hardware"]["validated_combinations"])
    assert payload["limits"]["max_requested_runs"] == 2000
    assert payload["limits"]["max_n_reprogram"] == 100


async def test_capabilities_do_not_probe_out_of_scope_neurosim(client, monkeypatch):
    import ctfm.adapters

    def unexpected_probe():
        raise AssertionError("NeuroSim was probed for product capabilities")

    monkeypatch.setattr(ctfm.adapters, "_neurosim_capability", unexpected_probe)
    response = await client.get("/api/v1/capabilities")
    assert response.status_code == 200, response.text
    assert response.json()["engines"]["neurosim"]["reason"] == "outside_product_scope"


async def test_valid_request_cannot_create_a_fake_job(client):
    response = await client.post("/api/v1/experiments", json=baseline())
    assert_error(response, 404, "not_found")
    assert "job_id" not in response.json()
    assert "accuracy" not in response.json()


@pytest.mark.parametrize("field,value", [
    ("hardware.tile_size", 128), ("hardware.tile_size", 256),
    ("hardware.adc_order", "subtract_then_adc"),
    ("engines.ppa", "assumed_proxy"),
])
async def test_out_of_scope_request_is_rejected_before_profile_lookup(client, field, value):
    request = baseline()
    request["schema_version"] = "1.4.0"
    request["effects"]["adc"] = True
    request["hardware"].update(adc_bits=5, adc_order="adc_then_subtract",
                               range_policy="validation_max_abs")
    section, key = field.split(".")
    request[section][key] = value
    error = assert_error(await client.post("/api/v1/experiments", json=request), 422,
                         "outside_product_scope")
    assert error["field"] == field


@pytest.mark.parametrize("changes", [
    {"seed": -1}, {"seed": True}, {"arrays": 30}, {"vds_v": 0.5},
    {"years": [0, 1]},
])
async def test_request_constraints_reach_http_boundary(client, changes):
    request = baseline()
    request.update(changes)
    assert_error(await client.post("/api/v1/experiments", json=request), 422, "invalid_request")


async def test_unsupported_effect_has_explicit_error_code(client):
    request = baseline()
    request["effects"]["c2c"] = True
    assert_error(await client.post("/api/v1/experiments", json=request), 422, "unsupported_effect")


@pytest.mark.parametrize("body", ['{"seed":', '{"years":[NaN]}', '{"years":[Infinity]}', 'null', '[]'])
async def test_malformed_or_nonfinite_json_has_serializable_error(client, body):
    response = await client.post("/api/v1/experiments", content=body, headers={"Content-Type": "application/json"})
    error = assert_error(response, 422, "invalid_request")
    assert isinstance(error["message"], str)
    assert "input" not in error["details"]
    json.loads(response.text, parse_constant=lambda value: pytest.fail(f"Nonfinite JSON: {value}"))


@pytest.mark.parametrize("method,path,status", [("get", "/api/v1/missing", 404), ("put", "/api/v1/capabilities", 405)])
async def test_routing_errors_use_common_envelope(client, method, path, status):
    response = await getattr(client, method)(path)
    assert_error(response, status, "not_found" if status == 404 else "method_not_allowed")


async def test_openapi_exposes_the_real_request_and_error_contracts(client):
    document = (await client.get("/openapi.json")).json()
    operation = document["paths"]["/api/v1/experiments"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    request_name = schema["$ref"].split("/")[-1]
    request_schema = document["components"]["schemas"][request_name]
    assert request_schema["properties"]["schema_version"]["enum"] == ["1.2.0", "1.3.0", "1.4.0"]
    assert request_schema["allOf"]
    assert "202" in operation["responses"]
    response_ref = operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
    assert response_ref.endswith("/ErrorResponse")


@pytest.mark.parametrize('depth', [64, 900, 957])
async def test_deep_invalid_json_is_rejected_with_the_common_envelope(client, depth):
    response = await client.post(
        "/api/v1/experiments", content="[" * depth + "0" + "]" * depth,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)
    assert_error(response, response.status_code, 'invalid_request')


async def test_unexpected_server_failure_does_not_leak_internal_details(monkeypatch):
    import importlib
    module = importlib.import_module("ctfm_api.app")

    def broken_metadata(_):
        raise RuntimeError("private file path and stack trace")

    monkeypatch.setattr(module, "version", broken_metadata)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver"
    ) as local_client:
        response = await local_client.get("/api/v1/capabilities")
    assert_error(response, 500, "internal_error")
    assert "private" not in response.text
