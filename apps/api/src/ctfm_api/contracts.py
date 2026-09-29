"""Typed workflow requests; scientific settings remain owned by ctfm-core."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class IvBlockSelection(Strict):
    """Explicit Vg/Id/Ig block and monotone Vg segment of a repeated-block IV sheet."""
    type: Literal["iv_block"]
    block: int = Field(ge=0, strict=True)
    segment: int = Field(ge=0, strict=True)

class RetentionColumnSelection(Strict):
    """Explicit 0-based sheet columns for the independent Erase/Program time axes."""
    type: Literal["retention_columns"]
    columns: dict[str, int]

RETENTION_ROLES = ("erase_time_s", "erase_id_a", "program_time_s", "program_id_a")

class AnalysisInput(Strict):
    file_id: UUID
    sheet: str | None = None
    column_mapping: dict[str, str] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    selection: IvBlockSelection | RetentionColumnSelection | None = Field(default=None, discriminator="type")
    measurement_conditions: dict | None = None
    header_read_vgs_v: float | None = None
    device_id: str = Field(min_length=1, max_length=200)
    condition_id: str = Field(min_length=1, max_length=200)
    branch: Literal["program", "erase"] | None = None
    sweep_amplitude_v: float | None = Field(default=None, gt=0)
    direction: Literal["ltp", "ltd"] | None = None
    source_label: str | None = None
    read_vgs_v: float | None = None
    vds_v: float | None = Field(default=None, gt=0)
    start_time_s: float | None = Field(default=None, ge=0)
    row_start: int | None = Field(default=None, ge=1, strict=True)
    row_end: int | None = Field(default=None, ge=1, strict=True)

class AnalysisRequest(Strict):
    recognition_id: UUID | None = None
    kind: Literal["iv", "d2d", "retention", "pulse_states", "c2c_detrended"]
    inputs: list[AnalysisInput] = Field(min_length=1, max_length=40)
    settings: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def explicit_inputs(self):
        import json
        json.dumps(self.settings, allow_nan=False)
        keys = {"iv": {"vgs_v", "id_a"}, "d2d": {"vgs_v", "id_a"},
                "pulse_states": {"time_s", "id_a", "vgs_v"},
                "retention": {"time_s", "program_id_a", "erase_id_a"},
                "c2c_detrended": set()}[self.kind]
        if self.kind == "c2c_detrended" and len(self.inputs) != 1:
            raise ValueError("Measured C2C analyzes exactly one workbook")
        for item in self.inputs:
            if item.start_time_s is not None and self.kind != "pulse_states":
                raise ValueError("Per-source start time belongs to pulse analyses only")
            if self.kind == "d2d" and item.device_id.startswith("measurement-source:"):
                raise ValueError("D2D requires confirmed physical devices, not opaque measurement-source identities")
            if not item.device_id.strip() or not item.condition_id.strip():
                raise ValueError("Device and condition IDs must be explicit")
            if item.measurement_conditions is not None and self.kind != "c2c_detrended":
                raise ValueError("measurement_conditions belongs to measured C2C analyses only")
            if self.kind == "c2c_detrended":
                if item.column_mapping or item.units or item.selection is not None:
                    raise ValueError("Measured C2C recognizes its columns by header; do not send a column mapping or selection")
                if item.row_start or item.row_end:
                    raise ValueError("Measured C2C uses every cycle row; row ranges are not supported")
                from ctfm.measurement.c2c import C2CAnalysisError, validate_measurement_conditions
                try:
                    validate_measurement_conditions(item.measurement_conditions)
                except C2CAnalysisError as exc:
                    raise ValueError(str(exc)) from exc
                continue
            if item.selection is not None:
                self._selected_layout(item)
                continue
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

    def _selected_layout(self, item):
        """Explicit block/column selections replace the header-name mapping; nothing is inferred."""
        if item.column_mapping or item.row_start or item.row_end:
            raise ValueError("A layout selection replaces column_mapping and row ranges; do not send both")
        selection = item.selection
        if self.kind in ("iv", "d2d"):
            if not isinstance(selection, IvBlockSelection):
                raise ValueError("IV/D2D layout selection must be type iv_block")
            if item.branch is None or item.sweep_amplitude_v is None or item.vds_v is None or not item.sheet:
                raise ValueError("Sheet, branch, sweep amplitude and VDS must be explicit for a block selection")
            if set(item.units) != {"vgs_v", "id_a"} or item.units["vgs_v"] not in ("V", "mV") or item.units["id_a"] not in ("A", "mA", "uA", "nA"):
                raise ValueError("Block selection needs explicit vgs_v and id_a units")
        elif self.kind == "retention":
            if not isinstance(selection, RetentionColumnSelection):
                raise ValueError("Retention layout selection must be type retention_columns")
            if set(selection.columns) != set(RETENTION_ROLES) or len(set(selection.columns.values())) != 4 or min(selection.columns.values()) < 0:
                raise ValueError("Retention selection needs four distinct non-negative column indices for " + ", ".join(RETENTION_ROLES))
            if not item.sheet or not item.source_label or item.read_vgs_v is None or item.vds_v is None:
                raise ValueError("Retention selection needs sheet, raw source label and read biases")
            if set(item.units) != set(RETENTION_ROLES):
                raise ValueError("Retention selection needs a unit for each of " + ", ".join(RETENTION_ROLES))
            for key, unit in item.units.items():
                if unit not in (["s", "ms"] if key.endswith("time_s") else ["A", "mA", "uA", "nA"]):
                    raise ValueError("Unsupported unit for " + key)
        else:
            raise ValueError("This analysis kind has no layout selection")

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

class RecognitionResolution(Strict):
    """Only uncertain facts; reason is recorded as user evidence, never file evidence."""
    file_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    kind: Literal['pulse_states', 'iv', 'retention', 'c2c_detrended'] | None = None
    condition_id: str | None = Field(default=None, min_length=1, max_length=200)
    direction: Literal['ltp', 'ltd'] | None = None
    sheet: str | None = None
    column_mapping: dict[str, str] | None = None
    units: dict[str, str] | None = None
    measurement_group: str | None = Field(default=None, min_length=1, max_length=200)
    source_label: str | None = None
    read_vgs_v: float | None = None

class RecognitionRequest(Strict):
    file_ids: list[UUID] = Field(min_length=1, max_length=100)
    resolutions: list[RecognitionResolution] = Field(default_factory=list, max_length=100)

class RecognitionEvidence(Strict):
    field: str
    value: object = None
    scope: Literal['file_header', 'filename', 'snapshot_manifest', 'project_assumption', 'project_source', 'user_confirmed', 'waveform', 'unknown']
    rule: str
    detail: str

class RecognitionIssue(Strict):
    code: str
    detail: str
    sheet: str | None = None
    source_row: int | None = None
    cell: str | None = None
    block: int | None = None

class PulseRecognition(Strict):
    write_onset_time_s: float
    write_onset_source_row: int
    preceding_read_time_s: float
    preceding_read_source_row: int
    recording_start_time_s: float
    row_count: int
    write_transition_count: int
    sample_offset_rows: Literal[2]
    read_tolerance_v: float
    write_threshold_v: float
    pre_write_read_is_state: Literal[False]

class RecognizedSource(Strict):
    file_id: UUID
    sha256: str
    name: str
    kind: Literal['pulse_states', 'iv', 'retention', 'c2c_detrended'] | None
    condition_id: str | None
    direction: Literal['ltp', 'ltd'] | None
    sheet: str | None
    status: Literal['ready', 'needs_choice', 'invalid', 'unsupported']
    physical_identity: Literal['unverified', 'user_confirmed']
    simulation_eligible: Literal[False]
    evidence: list[RecognitionEvidence]
    issues: list[RecognitionIssue]
    warnings: list[str]
    layout: dict | None
    pulse: PulseRecognition | None
    measurement_group: str | None
    snapshot_paths: list[str]

class PulsePair(Strict):
    pair_key: str
    condition_id: str
    file_ids: list[UUID]
    status: Literal['ready', 'needs_choice']
    basis: str

class RecognitionProvenance(Strict):
    recognition_id: UUID
    rule: str
    sources: list[RecognizedSource]
    pulse_pairs: list[PulsePair]
class RecognitionResult(RecognitionProvenance):
    requests: list[AnalysisRequest]


class PhysicalDeviceSelection(Strict):
    file_id: UUID
    device_id: str = Field(min_length=1, max_length=200)
    identity_evidence: str = Field(min_length=1, max_length=2000)
    sheet: str | None = None
    block: int = Field(ge=0, strict=True)
    segment: int = Field(ge=0, strict=True)
    units: dict[str, str]

class D2DRecognitionRequest(Strict):
    condition_id: str = Field(min_length=1, max_length=200)
    selections: list[PhysicalDeviceSelection] = Field(min_length=2, max_length=40)
