"""Drafts deliberately permit incomplete choices; execution uses ExperimentRequest."""
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from .contracts import Strict

class ComparisonProfileRef(Strict):
    id: UUID
    revision: int = Field(ge=1, strict=True)

class ComparisonCard(Strict):
    card_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    profile_ref: ComparisonProfileRef | None = None
    condition_id: str | None = None
    state_analysis_id: UUID | None = None
    selected_state_ids: list[str] | None = None
    d2d_analysis_id: UUID | None = None
    retention_analysis_id: UUID | None = None
    c2c_analysis_id: UUID | None = None
    c2c_approved_assumption: bool = False
    cross_condition_acknowledged: bool = False
    manual_c2c_cv_percent: float | None = Field(default=None, ge=0)

class ComparisonDraft(Strict):
    common_settings: dict = Field(default_factory=dict, description="ExperimentRequest fields except profile_refs. Incomplete settings may be persisted; run validates the authoritative contract.")
    cards: list[ComparisonCard] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def unique_cards(self):
        if len({c.card_id for c in self.cards}) != len(self.cards):
            raise ValueError("Card IDs must be unique")
        if "profile_refs" in self.common_settings:
            raise ValueError("Use cards for profile references")
        return self

class ComparisonUpdate(ComparisonDraft):
    expected_version: int = Field(ge=1, strict=True)

class ComparisonRun(Strict):
    expected_version: int = Field(ge=1, strict=True)

class ComparisonSave(Strict):
    name: str = Field(min_length=1, max_length=200)

class ComparisonClone(Strict):
    operation_id: UUID

class ComparisonCardResult(ComparisonCard):
    status: Literal["draft", "blocked", "queued", "running", "succeeded", "partial", "failed", "cancelled"] = "draft"
    reason: str | None = None
    profile_hash: str | None = None
    experiment_id: UUID | None = None
    job_id: UUID | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    runs: list[dict] = Field(default_factory=list)

class ComparisonResult(Strict):
    comparison_id: UUID
    version: int
    lifecycle: Literal["drafting", "running", "temporary", "saved", "discarded"]
    name: str | None = None
    common_settings: dict
    cards: list[ComparisonCardResult]
    created_at: str
    updated_at: str
    origin_id: UUID | None = None
    clone_operation_id: UUID | None = None
    experiment_id: UUID | None = None
    job_id: UUID | None = None
    outcome: Literal["succeeded", "partial", "failed", "cancelled"] | None = None
    snapshot: dict | None = None
    discard_requested: bool = False

class ComparisonList(Strict):
    items: list[ComparisonResult]
