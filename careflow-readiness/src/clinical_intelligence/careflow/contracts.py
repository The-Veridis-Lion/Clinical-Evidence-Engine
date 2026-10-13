"""Strict request/reviewer contracts reuse the existing source and citation types."""
from datetime import date
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from ..claims_review.contracts import Contract, Identifier, SourceInput
from ..dialogue_first.contract import Extraction

Requirement = Literal[
    'request_intent', 'referral_reason', 'destination', 'clinical_summary',
    'investigation_required', 'investigation_result', 'therapy_required',
    'therapy_completed', 'pa_form', 'payer_context',
]


class Source(SourceInput):
    """Add public text origins locally; leave the shared claims contract intact."""
    origin: Literal['constructed_synthetic', 'synthea_export', 'public_clinical_dataset', 'request_intake']
    source_kind: Literal['structured_record', 'synthetic_note', 'clinical_text']

    @model_validator(mode='after')
    def content_matches_source_kind(self):
        if self.source_kind == 'clinical_text':
            if not isinstance(self.content, str) or not self.content.strip() or self.record_type != 'note':
                raise ValueError('clinical_text requires original nonempty note/dialogue content')
            return self
        return super().content_matches_source_kind()


class ClinicalContext(Contract):
    source_id: Identifier
    extraction: Extraction


class ClinicalBinding(Contract):
    """Explicit intake/order association, independently grounded from existence."""
    schema_version: Literal['careflow-clinical-binding/1'] = 'careflow-clinical-binding/1'
    binding_id: Identifier
    binding_source_id: Identifier
    patient_id: Identifier
    request_id: Identifier
    service_code: Identifier
    code_system: Identifier
    requirement: Requirement
    clinical_fact_ids: list[Identifier] = Field(min_length=1)
    document_role: Literal['clinical_summary'] | None = None
    clinical_purpose: Literal['therapeutic', 'diagnostic', 'unknown'] = 'unknown'


class Request(Contract):
    request_id: Identifier
    patient_id: Identifier
    encounter_id: Identifier | None
    request_type: Literal['referral', 'prior_authorization']
    service_code: Identifier
    code_system: Identifier
    requested_service_date: date | None
    ruleset_id: Identifier
    ruleset_version: Identifier


class EvidenceRef(Contract):
    source_id: Identifier
    # Existing Unicode line anchors or an exact structured content field.
    span_id: Identifier | None = None
    field: Identifier | None = None

    @model_validator(mode='after')
    def one_locator(self):
        if (self.span_id is None) == (self.field is None):
            raise ValueError('Exactly one span_id or field is required')
        return self


class Fact(Contract):
    fact_id: Identifier
    patient_id: Identifier
    request_id: Identifier
    service_code: Identifier
    code_system: Identifier
    requirement: Requirement
    assertion: StrictBool | None
    statement: Identifier
    evidence: list[EvidenceRef] = Field(min_length=1)
    # This is asserted interpretation, not source authenticity certification.
    interpretation_origin: Literal['structured_mapping', 'human', 'advanced_ai']
    amends_fact_id: Identifier | None = None
    authority_ref: EvidenceRef | None = None

    @model_validator(mode='after')
    def authority_is_scoped(self):
        if (self.amends_fact_id is None) != (self.authority_ref is None):
            raise ValueError('An amendment requires an explicit source authority reference')
        return self


class Case(Contract):
    schema_version: Literal['careflow-case/1'] = 'careflow-case/1'
    case_id: Identifier
    request: Request
    review_as_of: date
    sources: list[Source]
    facts: list[Fact]
    clinical_context: list[ClinicalContext] = Field(default_factory=list, exclude_if=lambda value: not value)
    clinical_bindings: list[ClinicalBinding] = Field(default_factory=list, exclude_if=lambda value: not value)

    @model_validator(mode='after')
    def unique_ids_and_references(self):
        for kind, items in [('source_id', self.sources), ('fact_id', self.facts)]:
            ids = [getattr(item, kind) for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f'Duplicate {kind}')
        sources = {s.source_id for s in self.sources}
        facts = {f.fact_id: f for f in self.facts}
        if self.clinical_context:
            from .clinical_context import validate_context_sources
            validate_context_sources(self)
        if self.clinical_bindings:
            if len({b.binding_id for b in self.clinical_bindings}) != len(self.clinical_bindings):
                raise ValueError('Duplicate clinical binding identity')
            if any(b.binding_source_id not in sources for b in self.clinical_bindings):
                raise ValueError('Clinical binding references an unknown scope source')
            from .mapping import map_clinical
            derived, _ = map_clinical(self)
            if facts.keys() & {f.fact_id for f in derived}:
                raise ValueError('Supplied fact identity collides with a derived clinical mapping')
            facts.update((f.fact_id, f) for f in derived)
        for fact in self.facts:
            refs = fact.evidence + ([fact.authority_ref] if fact.authority_ref else [])
            if any(ref.source_id not in sources for ref in refs):
                raise ValueError('Fact references an unknown source')
            if fact.amends_fact_id:
                original = facts.get(fact.amends_fact_id)
                if original is None or original.fact_id == fact.fact_id:
                    raise ValueError('Amendment target missing or self-referential')
                fields = ('patient_id', 'request_id', 'service_code', 'code_system', 'requirement')
                if any(getattr(fact, field) != getattr(original, field) for field in fields):
                    raise ValueError('Amendment scope differs from the original fact')
                old_sources = {r.source_id for r in original.evidence}
                if any(r.source_id in old_sources for r in fact.evidence):
                    raise ValueError('A correction requires independent source evidence')
        return self


class Review(Contract):
    reviewer_id: Identifier
    reviewer_type: Literal['human', 'advanced_ai']
    model: Identifier | None = None
    model_version: Identifier | None = None
    basis_revision: int = Field(ge=1)
    basis_packet_sha256: Identifier
    fact_ids: list[Identifier]
    judgment: Literal['AGREE', 'DISAGREE', 'PROPOSE_CORRECTION', 'ESCALATE']
    reason: Identifier
    proposed_actions: list[Identifier] = Field(default_factory=list)

    @model_validator(mode='after')
    def reviewer_identity(self):
        if self.reviewer_type == 'advanced_ai' and (self.model is None or self.model_version is None):
            raise ValueError('Advanced AI review requires model and version')
        if self.reviewer_type == 'human' and (self.model is not None or self.model_version is not None):
            raise ValueError('Human reviewers do not have model metadata')
        if len(self.fact_ids) != len(set(self.fact_ids)):
            raise ValueError('Duplicate review fact IDs')
        return self


class EvidenceIntake(Contract):
    """Administrative source receipt, not a clinical reviewer opinion."""
    actor_id: Identifier
    actor_type: Literal['intake_service']
    basis_revision: int = Field(ge=1)
    basis_packet_sha256: Identifier
    reason: Identifier


class EvidenceUpdate(Contract):
    expected_revision: int = Field(ge=1)
    sources: list[Source] = Field(min_length=1)
    facts: list[Fact] = Field(default_factory=list)
    review: Review | None = Field(default=None, exclude_if=lambda value: value is None)
    intake: EvidenceIntake | None = Field(default=None, exclude_if=lambda value: value is None)
    clinical_context: list[ClinicalContext] = Field(default_factory=list, exclude_if=lambda value: not value)
    clinical_bindings: list[ClinicalBinding] = Field(default_factory=list, exclude_if=lambda value: not value)

    @model_validator(mode='after')
    def meaningful_update(self):
        if (self.review is None) == (self.intake is None):
            raise ValueError('Exactly one review or administrative intake record is required')
        if any(f.amends_fact_id for f in self.facts) and self.review is None:
            raise ValueError('Assertion corrections require a reasoned human/AI review')
        if not (self.facts or self.clinical_context or self.clinical_bindings):
            raise ValueError('Evidence update needs assertions, clinical facts or source-backed bindings')
        return self


class SourceIntake(Contract):
    """Original sources and optional cached extractions, without caller truth votes."""
    schema_version: Literal['careflow-source-intake/1'] = 'careflow-source-intake/1'
    case_id: Identifier
    request: Request
    review_as_of: date
    sources: list[Source] = Field(min_length=1)
    extractions: list[ClinicalContext] = Field(default_factory=list)
    clinical_bindings: list[ClinicalBinding] = Field(default_factory=list)
