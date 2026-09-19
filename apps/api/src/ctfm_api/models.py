"""Response contracts for the first P0 API slice."""
from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class APIError(ResponseModel):
    code: str
    message: str
    field: str | None
    details: dict
    request_id: str


class ErrorResponse(ResponseModel):
    error: APIError


class Capability(ResponseModel):
    available: bool
    reason: str | None
    version: str | None = None
    parity: dict | None = None
    config: str | None = None


class HardwareControls(ResponseModel):
    # These are request choices, not advertised engine support.
    tile_sizes: list[int]
    adc_bits: list[int]
    range_policies: list[str]
    validated_combinations: list[dict]


class Capabilities(ResponseModel):
    schema_version: str
    profile_schema_version: str
    models: dict[str, Capability]
    engines: dict[str, Capability]
    effects: dict[str, Capability]
    hardware: HardwareControls
    limits: dict[str, int]
    supported_file_formats: list[str]
    warnings: list[str]
