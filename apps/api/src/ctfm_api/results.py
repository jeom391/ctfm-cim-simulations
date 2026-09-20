"""Shared response shapes. Additional scientific diagnostics retain their native keys."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class ScientificResult(BaseModel):
    model_config=ConfigDict(extra="allow",allow_inf_nan=False)

class Artifact(ScientificResult):
    id: UUID
    kind: str
    filename: str
    media_type: str
    sha256: str=Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int=Field(ge=0)
    download_url: str

class AnalysisResult(ScientificResult):
    analysis_id: UUID
    job_id: UUID
    status: Literal["queued","running","succeeded","failed","cancelled"]
    kind: Literal["iv","d2d","retention","pulse_states"] | None=None
    condition_id: str | None=None
    settings: dict | None=None
    summaries: dict | None=None
    tables: dict[str,list[dict]] | None=None
    exclusions: list[dict] | None=None
    warnings: list[str] | None=None
    artifacts: list[Artifact]

class RunResult(ScientificResult):
    kind: Literal["D0","D1","M0","ALL","candidate"]
    status: Literal["succeeded","invalid","skipped","failed"]
    accuracy: float | None=Field(default=None,ge=0,le=1)
    loss_vs_digital_pp: float | None=None
    loss_vs_mapped_pp: float | None=None
    retention_loss_pp: float | None=None
    years: float | None=Field(default=None,ge=0)
    array_index: int | None=Field(default=None,ge=0)
    reason: str | None=None

class ExperimentResult(ScientificResult):
    experiment_id: UUID
    job_id: UUID
    status: Literal["queued","running","succeeded","partial","failed","cancelled"]
    schema_version: Literal["1.2.0"] | None=None
    requested_config: dict | None=None
    resolved_config: dict | None=None
    effective_config: dict | None=None
    provenance: dict | None=None
    assumptions: list[dict] | None=None
    warnings: list[str] | None=None
    runs: list[RunResult] | None=None
    summary: dict | None=None
    artifacts: list[Artifact]

class JobResult(ScientificResult):
    id: UUID
    kind: Literal["analysis","experiment"]
    entity_id: UUID
    state: Literal["queued","running","succeeded","failed","cancelled"]
    stage: str | None
    progress: float=Field(ge=0,le=1)
    completed: int=Field(ge=0)
    total: int=Field(ge=0)
    cancel_requested: bool
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: dict | None

class FileMetadata(ScientificResult):
    file_id: UUID
    name: str
    sha256: str=Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int=Field(ge=0)
    media_type: str
    created_at: str

class FileUploadResult(ScientificResult):
    files: list[FileMetadata]

class FileList(ScientificResult):
    items: list[FileMetadata]

class FilePreview(ScientificResult):
    file_id: UUID
    sheet: str | None
    sheets: list[str]
    columns: list[str]
    rows: list[dict]
    source_rows: list[int]
    warnings: list[str]

class JobList(ScientificResult):
    items: list[JobResult]

class AnalysisList(ScientificResult):
    items: list[AnalysisResult]

class ExperimentList(ScientificResult):
    items: list[ExperimentResult]
