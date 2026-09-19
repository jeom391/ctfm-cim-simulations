"""Typed workflow requests; scientific settings remain owned by ctfm-core."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class AnalysisInput(Strict):
    file_id: UUID
    sheet: str | None = None
    column_mapping: dict[str, str]
    units: dict[str, str]
    device_id: str = Field(min_length=1, max_length=200)
    condition_id: str = Field(min_length=1, max_length=200)
    branch: Literal["program", "erase"] | None = None
    sweep_amplitude_v: float | None = Field(default=None, gt=0)
    direction: Literal["ltp", "ltd"] | None = None
    source_label: str | None = None
    read_vgs_v: float | None = None
    vds_v: float | None = Field(default=None, gt=0)
    row_start: int | None = Field(default=None, ge=1, strict=True)
    row_end: int | None = Field(default=None, ge=1, strict=True)

class AnalysisRequest(Strict):
    kind: Literal["iv", "d2d", "retention", "pulse_states"]
    inputs: list[AnalysisInput] = Field(min_length=1, max_length=40)
    settings: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def explicit_inputs(self):
        import json
        json.dumps(self.settings, allow_nan=False)
        keys = {"iv": {"vgs_v", "id_a"}, "d2d": {"vgs_v", "id_a"},
                "pulse_states": {"time_s", "id_a", "vgs_v"},
                "retention": {"time_s", "program_id_a", "erase_id_a"}}[self.kind]
        for item in self.inputs:
            if not item.device_id.strip() or not item.condition_id.strip():
                raise ValueError("Device and condition IDs must be explicit")
            if set(item.column_mapping) != keys or set(item.units) != keys:
                raise ValueError("Explicit column mapping and units are required")
            if len(set(item.column_mapping.values())) != len(keys) or not all(item.column_mapping.values()):
                raise ValueError("Use distinct nonempty columns")
            for key, unit in item.units.items():
                valid = ["s", "ms"] if key == "time_s" else ["V", "mV"] if key == "vgs_v" else ["A", "mA", "uA", "nA"]
                if unit not in valid:
                    raise ValueError("Unsupported unit for " + key)
            if item.row_start and item.row_end and item.row_start > item.row_end:
                raise ValueError("Invalid source row range")
            if self.kind in ("iv", "d2d") and (item.branch is None or item.sweep_amplitude_v is None):
                raise ValueError("Branch and sweep amplitude must be selected")
            if self.kind == "pulse_states" and item.direction is None:
                raise ValueError("Pulse direction must be selected")
            if self.kind == "retention" and (not item.source_label or item.read_vgs_v is None or item.vds_v is None):
                raise ValueError("Raw source label and read biases are required")
        if len({item.condition_id for item in self.inputs}) != 1:
            raise ValueError("Analyze A1-A5 separately; conditions cannot be mixed")
        return self

class ProfileCreate(Strict):
    condition_id: str = Field(min_length=1)
    state_analysis_id: UUID
    selected_state_ids: list[str]
    d2d_analysis_id: UUID | None = None
    retention_analysis_id: UUID | None = None
    display_name: str | None = None

class ProfileRevision(Strict):
    base_revision: int = Field(ge=1, strict=True)
    selected_state_ids: list[str] | None = None
    display_name: str | None = None

class ProfilePublish(Strict):
    reviewer: str = Field(min_length=1, max_length=200)
    review_note: str = Field(min_length=1, max_length=10000)

class QueuedAnalysis(Strict):
    analysis_id: UUID
    job_id: UUID

class QueuedExperiment(Strict):
    experiment_id: UUID
    job_id: UUID
