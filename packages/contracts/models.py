"""Pydantic boundary over the authoritative experiment JSON Schema."""
from copy import deepcopy
from typing import Any

from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import RootModel, model_validator
from pydantic_core import PydanticCustomError

from .check_experiment_contract import ContractError, SCHEMA, validate_request


class ExperimentRequest(RootModel[dict[str, Any]]):
    """Preserve the request verbatim; validation is shared with the CLI.

    Do not duplicate the schema in coercing Python fields: for example,
    JSON Schema accepts integral JSON numbers but rejects boolean integers.
    Profile publication/hash/data and engine checks belong to the server.
    """

    @model_validator(mode="before")
    @classmethod
    def check_contract(cls, value: Any) -> Any:
        try:
            validate_request(value)
        except SchemaValidationError as error:
            field = ".".join(str(part) for part in error.absolute_path) or None
            unsupported = (
                field == "effects.c2c" and error.instance is True
            ) or (
                field == "n_reprogram"
                and type(error.instance) in (int, float)
                and error.instance != 1
            )
            raise PydanticCustomError(
                "experiment_contract",
                "Request does not match the experiment contract.",
                {"field": field, "code": "unsupported_effect" if unsupported else "invalid_request",
                 "rule": error.validator},
            ) from error
        except ContractError as error:
            raise PydanticCustomError(
                "experiment_contract", str(error),
                {"field": error.field, "code": error.code, "rule": error.code},
            ) from error
        return value

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        return deepcopy(SCHEMA)
