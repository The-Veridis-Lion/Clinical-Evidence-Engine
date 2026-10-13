"""Source support is a documented entailment judgment, never expert clinical truth."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ENGINE_VERSION = 'evidence-verifier/1'
METHOD_VERSION = 'bounded-source-grammar/1'
Status = Literal['SUPPORTED_BY_SOURCE', 'CONTRADICTED', 'INSUFFICIENT_EVIDENCE', 'CONFLICTED']
Route = Literal['AUTO_ACCEPT_ELIGIBLE', 'CORRECTION_CANDIDATE', 'REVIEW_REQUIRED', 'MISSING_EVIDENCE', 'CONFLICT_REVIEW']


def digest(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Span(Model):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)
    source_id: str | None = None


class Source(Model):
    source_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sha256: str
    patient_id: str = Field(min_length=1)
    encounter_id: str | None = None
    available_at: str | None = None
    input_kind: str = 'note'

    @model_validator(mode='after')
    def source_hash(self):
        if digest(self.text) != self.sha256:
            raise ValueError('Full source hash mismatch')
        return self

    def check_span(self, span: Span) -> bool:
        return (span.source_id in {None, self.source_id} and
                0 <= span.start < span.end <= len(self.text) and
                self.text[span.start:span.end] == span.quote)


class Claim(Model):
    claim_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    encounter_id: str | None = None
    category: str
    concept: str | None
    spans: list[Span] = Field(min_length=1)
    experiencer: str = 'unknown'
    reporting_basis: str = 'unknown'
    polarity: str = 'uncertain'
    certainty: str = 'unknown'
    temporality: str = 'unknown'
    event_time: str | None = None
    action_type: str | None = None
    action_state: str = 'unknown'
    completion_scope: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        return digest(self.model_dump(mode='json'))


class DimensionCheck(Model):
    dimension: str
    status: Literal['SUPPORTED', 'CONTRADICTED', 'UNVERIFIED', 'NOT_ASSERTED']
    proposed: Any = None
    source_value: Any = None
    reason: str
    spans: list[Span] = Field(default_factory=list)


class SourceReview(Model):
    """Retained external judgment must bind the complete claim and original source.

    Exact binding prevents reuse across patients/events. A valid record remains a
    reviewer opinion: its method must be independently calibrated for auto routing.
    """
    review_id: str
    source_id: str
    source_hash: str
    claim_fingerprint: str
    patient_id: str
    encounter_id: str | None
    status: Status
    dimension_checks: list[DimensionCheck] = Field(min_length=1)
    supporting_spans: list[Span] = Field(default_factory=list)
    counter_spans: list[Span] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    method: str
    model_version: str | None = None
    reviewer_type: str
    uncertainty: list[str] = Field(default_factory=list)


class Calibration(Model):
    calibration_id: str
    method: str
    categories: list[str]
    sample_count: int = Field(gt=0)
    measured_precision: float = Field(ge=0, le=1)
    minimum_precision: float = Field(ge=.95, le=1)
    reference_type: str
    data_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    scope: str = 'explicit-symptom-clause/1'


class VerificationResult(Model):
    claim_id: str
    claim_fingerprint: str
    source_hash: str
    engine_version: str = ENGINE_VERSION
    status: Status
    dimension_checks: list[DimensionCheck]
    supporting_spans: list[Span] = Field(default_factory=list)
    counter_spans: list[Span] = Field(default_factory=list)
    source_assertion: Claim | None = None
    context_spans: list[Span] = Field(default_factory=list)
    reasons: list[str]
    method: str
    model_version: str | None = None
    uncertainty: list[str] = Field(default_factory=list)
    risk_route: Route
    calibration_id: str | None = None
    expert_validation: Literal['NOT_ESTABLISHED'] = 'NOT_ESTABLISHED'


class EnumerationResult(Model):
    version: str = 'source-assertion-enumeration/1'
    source_hash: str
    assertions: list[Claim]
    assertion_proposals: list[dict[str, Any]] = Field(default_factory=list)
    assertion_origins: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_units: list[dict[str, Any]]
    method: str = METHOD_VERSION
    semantic_completeness: Literal['PARTIAL', 'UNVERIFIED'] = 'PARTIAL'
    limitation: str = 'Bounded explicit assertions only; unrecognized meanings remain outside the enumerated denominator.'


class BoundVerificationResult(Model):
    version: str = 'bound-source-verification/1'
    per_source_results: list[VerificationResult]
    effective_results: list[VerificationResult]
    conflict_groups: list[dict[str, Any]]
    unresolved_event_groups: list[dict[str, Any]]
    boundary: str = 'Exact per-source proofs are immutable; cross-source conflicts require explicit correction authority outside this engine.'


class CoverageResult(Model):
    version: str = 'source-coverage-verification/1'
    enumeration: EnumerationResult
    alignments: list[dict[str, Any]]
    omission_candidates: list[Claim]
    duplicate_claim_groups: list[list[str]]
    unsupported_claim_ids: list[str]
    unmatched_claim_ids: list[str] = Field(default_factory=list)
    unrepresented_attributes: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_attributes: list[dict[str, Any]] = Field(default_factory=list)
    misaligned_claim_ids: list[str]
    semantic_completeness: Literal['PARTIAL', 'UNVERIFIED'] = 'PARTIAL'
    reference_type: str = 'bounded_source_assertions_not_independent_clinical_gold'
