"""Application-owned data contract; no provider or extraction-library types."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

# Extraction contracts and derived facts have separate invalidation versions.
ABSTRACTION_VERSION = "4"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class State(StrEnum):
    RESOLVED = "resolved"
    UNCERTAIN = "uncertain"
    CONFLICTED = "conflicted"
    INSUFFICIENT = "insufficient_evidence"


class ServiceType(StrEnum):
    INDIVIDUAL = "individual"
    GROUP = "group"
    FAMILY = "family"
    MEDICATION = "medication"
    COLLATERAL = "collateral"
    COORDINATION = "coordination"
    ADMINISTRATIVE = "administrative"


THERAPY_TYPES = {ServiceType.INDIVIDUAL, ServiceType.GROUP, ServiceType.FAMILY}


class EvidenceKind(StrEnum):
    CLINICAL = "clinical"
    ATTENDANCE = "attendance"
    SCHEDULE = "schedule"
    DRAFT = "draft"
    BILLING = "billing"
    CORRECTION = "correction"
    RETRANSMISSION = "retransmission"


class Patient(Model):
    patient_id: str  # MRN when explicitly supplied; never inferred from a name alone
    name: str
    dob: date | None = None


class RegisteredDocument(Model):
    document_id: str  # content SHA256: stable across filenames and input order
    fingerprint: str
    source_names: list[str]
    text: str
    status: Literal["registered", "extracted", "failed"] = "registered"
    extraction_key: str | None = None
    declared_id: str | None = None
    error: str | None = None


class SourcePassage(Model):
    document_id: str
    # Character offsets refer to retained Unicode text; end is exclusive.
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    alignment: Literal["exact"] = "exact"
    locator: Literal["langextract", "unique_exact_substring"] = "langextract"

    @model_validator(mode="after")
    def valid_span(self):
        if self.end <= self.start or len(self.quote) != self.end - self.start:
            raise ValueError("Source span must match quote length")
        return self


class TimeInterval(Model):
    """Half-open interval of local calendar-day minutes. No implied overnight wrap."""
    start: int = Field(ge=0, lt=1440)
    end: int = Field(gt=0, le=1440)

    @model_validator(mode="after")
    def forward(self):
        if self.end <= self.start:
            raise ValueError("Interval end must follow start on the same local date")
        return self


# Source claims preserve a document's statements, including errors or disagreements.
class ClinicalClaim(Model):
    claim_id: str
    document_id: str
    patient_id: str
    passages: list[SourcePassage] = Field(min_length=1)
    statement: str
    recorded_at: datetime | None = None


class ServiceClaim(ClinicalClaim):
    kind: Literal["service"] = "service"
    encounter_ref: str | None = None
    appointment_ref: str | None = None
    service_date: date | None = None
    service_type: ServiceType | None = None
    evidence_kind: EvidenceKind
    signed: bool = False
    # None means unknown; patient presence and service delivery are separate claims.
    patient_present: bool | None = None
    delivered: bool | None = None
    # Keep actual contact, scheduled slots and reported duration separate.
    actual_intervals: list[TimeInterval] = Field(default_factory=list)
    scheduled_intervals: list[TimeInterval] = Field(default_factory=list)
    # Retain header clocks without promoting them to delivered treatment evidence.
    unspecified_intervals: list[TimeInterval] = Field(default_factory=list)
    breaks: list[TimeInterval] = Field(default_factory=list)
    reported_minutes: int | None = Field(default=None, ge=0)
    reason: str | None = None


class PlanClaim(ClinicalClaim):
    kind: Literal["plan"] = "plan"
    plan_ref: str | None = None
    effective_start: date
    effective_end: date | None = None
    required_days: int = Field(ge=0, le=7)
    required_minutes: int = Field(ge=0)
    service_types: list[ServiceType] = Field(min_length=1)
    week_basis: Literal["monday_sunday"] = "monday_sunday"
    signed: bool


class AssessmentClaim(ClinicalClaim):
    kind: Literal["assessment"] = "assessment"
    instrument: str
    assessment_date: date | None = None
    form_ref: str | None = None
    score: float | None = None
    reporter: str
    experiencer: str
    copied: bool = False


class ClinicalObservation(ClinicalClaim):
    kind: Literal["observation"] = "observation"
    observation_date: date | None = None
    category: Literal["symptom", "function", "safety", "treatment_reason", "response"]
    # A partner may report the patient's symptoms or describe their own experience.
    reporter: str
    experiencer: str
    polarity: Literal["present", "absent", "uncertain"]
    temporality: Literal["current", "historical", "planned"]


class FunctionalAction(ClinicalClaim):
    """A reported real-world step; completion applies to this action only."""
    kind: Literal["functional_action"] = "functional_action"
    report_date: date
    # A report does not establish when the described action actually occurred.
    action_date: date | None = None
    action: str
    actor: str
    reporter: str
    status: Literal["planned", "attempted", "completed"]


# A correction identifies a target and field; reconciliation decides its effect.
class CorrectionRelationship(ClinicalClaim):
    kind: Literal["relationship"] = "relationship"
    relation: Literal["corrects", "retransmits", "duplicates", "supersedes_plan"]
    signed: bool = False
    target_encounter: str | None = None
    target_document_ref: str | None = None
    target_plan_ref: str | None = None
    field: Literal["arrival", "departure", "minutes", "presence", "plan", "record"]
    replacement_time: int | None = Field(default=None, ge=0, le=1440)
    replacement_minutes: int | None = Field(default=None, ge=0)
    replacement_presence: bool | None = None
    original_time: int | None = Field(default=None, ge=0, le=1440)
    service_date: date | None = None


Claim = Annotated[ServiceClaim | PlanClaim | AssessmentClaim | ClinicalObservation | FunctionalAction | CorrectionRelationship,
                  Field(discriminator="kind")]


class ExtractionUsage(Model):
    provider: str
    model: str
    settings: dict
    latency_seconds: float = Field(ge=0)
    model_calls: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    input_characters: int | None = Field(default=None, ge=0)
    # Character allocation is measured; hidden CLI context prevents exact token allocation.
    call_metrics: list[dict] = Field(default_factory=list)
    parse_failures: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    claim_counts: dict[str, int] = Field(default_factory=dict)
    cost_usd: float | None = None
    cost_basis: str | None = None


class DocumentExtraction(Model):
    document_id: str
    extraction_key: str
    declared_id: str | None = None
    patient: Patient
    claims: list[Claim]
    usage: ExtractionUsage

    @model_validator(mode="after")
    def identities(self):
        for claim in self.claims:
            if claim.document_id != self.document_id or claim.patient_id != self.patient.patient_id:
                raise ValueError("Claim identity does not match its document/patient")
            if any(p.document_id != self.document_id for p in claim.passages):
                raise ValueError("Passage identity does not match its document")
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("Duplicate claim IDs")
        return self


class ReconciliationDecision(Model):
    rule: str
    explanation: str
    claim_ids: list[str]


class Conflict(Model):
    conflict_id: str
    subject_id: str
    field: str
    values: list[str]
    claim_ids: list[str]
    explanation: str


class Uncertainty(Model):
    subject_id: str
    explanation: str
    claim_ids: list[str]
    needed_evidence: str


class CalculationTrace(Model):
    operation: str
    inputs: dict
    output: dict
    claim_ids: list[str]
    event_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


# Derived events keep eligibility separate from duration and its supported alternatives.
class ServiceEvent(Model):
    event_id: str
    patient_id: str
    encounter_ref: str | None
    appointment_refs: list[str]
    service_date: date | None
    service_type: ServiceType | None
    date_options: list[date] = Field(default_factory=list)
    type_options: list[ServiceType] = Field(default_factory=list)
    delivered: bool | None
    patient_present: bool | None
    countable: bool | None
    state: State
    minute_options: list[int] = Field(default_factory=list)
    minutes_lower: int = Field(ge=0)
    # An unknown upper bound must not be interpreted as zero treatment time.
    minutes_upper: int | None = Field(default=None, ge=0)
    claim_ids: list[str]
    decisions: list[ReconciliationDecision]
    conflicts: list[Conflict] = Field(default_factory=list)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    calculations: list[CalculationTrace] = Field(default_factory=list)


# Resolved plan periods may be shortened by an explicit supersession relationship.
class TreatmentPlan(Model):
    plan_id: str
    patient_id: str
    effective_start: date
    effective_end: date | None
    required_days: int
    required_minutes: int
    service_types: list[ServiceType]
    claim_ids: list[str]


class Assessment(Model):
    assessment_id: str
    patient_id: str
    instrument: str
    # Conflicting completion dates remain alternatives instead of choosing the earliest.
    assessment_date: date | None
    date_options: list[date] = Field(default_factory=list)
    form_ref: str | None
    experiencer: str
    reporters: list[str]
    score_options: list[float]
    state: State
    claim_ids: list[str]
    decisions: list[ReconciliationDecision]


class PatientAbstraction(Model):
    abstraction_version: str = ABSTRACTION_VERSION
    patient: Patient
    # Retain source claims alongside derived entities so every decision stays auditable.
    source_claims: list[Claim]
    events: list[ServiceEvent]
    plans: list[TreatmentPlan]
    assessments: list[Assessment]
    observations: list[ClinicalObservation]
    functional_actions: list[FunctionalAction] = Field(default_factory=list)
    relationships: list[CorrectionRelationship]
    conflicts: list[Conflict]
    uncertainties: list[Uncertainty]
