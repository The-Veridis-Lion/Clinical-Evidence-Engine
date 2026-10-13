"""Preparation input contracts, deliberately separate from the engine's models."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

Identifier = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ClaimInput(Contract):
    claim_id: Identifier
    patient_id: Identifier
    encounter_id: Identifier | None
    service_date: date | None
    service_concept: Literal["hba1c_monitoring", "hba1c_screening", "unspecified"]
    procedure_code: str | None
    code_system: str | None
    mapping_status: Literal["constructed_demo", "unmapped", "verified"]
    data_origin: Literal["constructed_synthetic", "synthea_export"]

    @model_validator(mode="after")
    def require_paired_code_metadata(self):
        if (self.procedure_code is None) != (self.code_system is None):
            raise ValueError("procedure_code and code_system must both be supplied or both null")
        return self


class ReviewContext(Contract):
    as_of: date
    history_start: date
    history_end: date
    history_completeness: Literal["not_asserted", "complete_within_constructed_case"]

    @model_validator(mode="after")
    def ordered_window(self):
        if not self.history_start <= self.history_end <= self.as_of:
            raise ValueError("Require history_start <= history_end <= as_of")
        return self


class SourceInput(Contract):
    source_id: Identifier
    patient_id: Identifier
    encounter_id: Identifier | None
    available_at: date | None
    origin: Literal["constructed_synthetic", "synthea_export"]
    source_kind: Literal["structured_record", "synthetic_note"]
    recorded_at: date | None
    event_date: date | None
    record_type: Literal["observation", "procedure", "condition", "medication_order", "order", "note", "encounter"]
    event_link_id: Identifier | None
    content: dict[str, Any] | str
    availability_basis: Literal["explicit_case_metadata", "export_snapshot_received", "unknown"] = "explicit_case_metadata"
    original_locator: dict[str, Any] | None = None

    @model_validator(mode="after")
    def content_matches_source_kind(self):
        if self.source_kind == "synthetic_note":
            if not isinstance(self.content, str) or not self.content.strip():
                raise ValueError("synthetic_note requires nonempty source text")
            if self.record_type != "note":
                raise ValueError("synthetic_note must use record_type=note")
        elif not isinstance(self.content, dict) or not self.content:
            raise ValueError("structured_record requires a nonempty unmodified field object")
        return self


class CaseInput(Contract):
    schema_version: Literal["claims-review-prep/0.1"]
    case_id: Identifier
    claim: ClaimInput
    review_context: ReviewContext
    sources: list[SourceInput]

    @model_validator(mode="after")
    def unique_source_ids(self):
        identifiers = [source.source_id for source in self.sources]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate source_id: preserve independent records under distinct source IDs")
        return self


FactKind = Literal['purpose', 'diabetes_context', 'test_event', 'test_mention',
                   'regimen_change', 'clinical_rationale', 'order_intent', 'source_record']
FactValue = StrictBool | StrictStr | StrictInt | StrictFloat | None
TemporalStatus = Literal['actual', 'historical', 'planned', 'unknown']


class Citation(Contract):
    patient_id: str
    source_id: str
    source_sha256: str
    method: Literal['unicode_line_anchor', 'input_json_pointer']
    locator: str
    quote: str | None = None
    start: int | None = None
    end: int | None = None
    raw_value: Any = None
    original_locator: dict[str, Any] | None = None


class NoteAssertion(Contract):
    kind: Literal['purpose', 'diabetes_context', 'test_mention', 'regimen_change',
                  'clinical_rationale', 'order_intent']
    statement: Annotated[str, StringConstraints(min_length=1)]
    value: FactValue
    fact_date: date | None
    date_role: Literal['actual_test', 'requested_test', 'order_issued', 'adjustment_start', 'background_review', 'unknown']
    temporal_status: TemporalStatus
    target_date: date | None
    test_specific: StrictBool | None
    provider: str | None
    reporter: str | None
    authenticated: StrictBool | None
    span_ids: list[str] = Field(min_length=1)


class NoteProposal(Contract):
    patient_id: str
    source_id: str
    facts: list[NoteAssertion]


class EvidenceFact(Contract):
    fact_id: str
    patient_id: str
    source_id: str
    kind: FactKind
    statement: str
    value: FactValue
    fact_date: date | None
    date_role: str
    temporal_status: TemporalStatus
    target_date: date | None
    test_specific: bool | None
    provider: str | None
    reporter: str | None
    authenticated: bool | None
    event_link_id: str | None
    citations: list[Citation] = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class PolicyReference(Contract):
    source_id: str
    source_version: str
    official_url: str
    locator: str


class CriterionResult(Contract):
    criterion_id: str
    criterion_role: str
    status: Literal['SUPPORTED', 'NOT_SUPPORTED', 'INSUFFICIENT_EVIDENCE',
                    'CONFLICTED', 'NOT_APPLICABLE', 'NOT_EVALUATED']
    reason: str
    clinical_refs: list[Citation]
    policy_refs: list[PolicyReference]
    gaps: list[str]
    conflicts: list[dict[str, Any]]
    derivation: dict[str, Any]
    evidence_complete: bool


class ReviewPacket(Contract):
    version: str
    case_id: str
    status: Literal['EVIDENCE_READY_FOR_HUMAN_REVIEW', 'NEEDS_HUMAN_REVIEW', 'UNSUPPORTED_SCOPE']
    target: ClaimInput
    review_context: ReviewContext
    preparation: dict[str, Any]
    facts: list[EvidenceFact]
    criteria: list[CriterionResult]
    timeline: list[dict[str, Any]]
    gaps: list[str]
    execution: dict[str, Any]
    identity: dict[str, Any]
    policy_review_status: str
    human_review_completed: bool
    clinical_expert_review_completed: bool
    decision_boundary: str = 'Evidence review only; no approval, denial, payment, or medical-necessity adjudication.'
