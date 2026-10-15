"""Versioned application contract. The Engine's clinical fact schema is unchanged."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

from ..dialogue_first.contract import DialogueFact
from ..dialogue_first.dataset import Document


def digest(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Source(Model):
    model_config = ConfigDict(extra='forbid', frozen=True)
    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    sha256: str
    input_kind: Literal['dialogue', 'note']
    encounter_time: str | None = None
    origin: str = 'user_input'
    offset_unit: Literal['unicode_code_points_end_exclusive'] = 'unicode_code_points_end_exclusive'

    @classmethod
    def create(cls, document_id, text, input_kind='note', **kwargs):
        return cls(document_id=document_id, text=text, sha256=digest(text), input_kind=input_kind, **kwargs)

    @model_validator(mode='after')
    def verify(self):
        if digest(self.text) != self.sha256:
            raise ValueError('Source hash mismatch')
        if self.encounter_time is not None:
            # Caller metadata, never promoted into an assertion's event time.
            datetime.fromisoformat(self.encounter_time.replace('Z', '+00:00'))
        return self

    def document(self):
        return Document(self.document_id, self.document_id, 'copilot', self.text,
                        self.sha256, self.sha256, 0, self.input_kind)


class EvidenceItem(Model):
    evidence_id: str
    source_id: str
    document_id: str
    source_sha256: str
    turn_id: str
    speaker_label: str | None
    quote: str
    start: int
    end: int
    line_start: int
    line_end: int
    source_time: str | None


class Assertion(Model):
    fact_id: str
    original_fact: dict
    assertion: DialogueFact
    evidence_ids: list[str]
    action_status: Literal['planned', 'completed', 'not_completed', 'ongoing', 'discussed', 'unknown'] = 'unknown'
    review_status: Literal['unreviewed', 'accepted', 'questioned', 'corrected', 'escalated'] = 'unreviewed'


class Issue(Model):
    issue_id: str
    code: str
    severity: Literal['info', 'review', 'high']
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    question: str


class Conflict(Model):
    conflict_id: str
    fact_ids: list[str]
    reason: str


class SoapAssertion(Model):
    text: str
    fact_ids: list[str]
    evidence_ids: list[str]
    review_status: str
    requires_review: bool


class Reviewer(Model):
    reviewer_id: str = Field(min_length=1)
    reviewer_type: Literal['human', 'ai']
    version: str = Field(min_length=1)


class ReviewRequest(Model):
    base_version: int = Field(ge=1)
    fact_id: str
    action: Literal['accept', 'question', 'correct', 'escalate']
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    reviewer: Reviewer
    replacement: dict | None = None


class ReviewRecord(ReviewRequest):
    review_id: str
    recorded_at: str
    applied_version: int
    before: dict
    after: dict
    supersedes_review_id: str | None = None
    correction_contract_version: Literal['citation-permutation-preservation/1'] | None = None

    @model_serializer(mode='wrap')
    def serialize_retained_contract(self, handler):
        value = handler(self)
        # Old saved review bytes/hashes do not acquire a newly defaulted field.
        if self.correction_contract_version is None:
            value.pop('correction_contract_version', None)
        return value


class OmissionCorrectionRequest(Model):
    base_version: int = Field(ge=1)
    candidate_claim_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    reviewer: Reviewer
    assertion: dict


class SemanticsReviewRequest(Model):
    """A v6-only sidecar correction; legacy ClinicalFact shape stays frozen."""
    base_version: int = Field(ge=1)
    fact_id: str
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    reviewer: Reviewer
    semantics: dict


class Packet(Model):
    schema_version: Literal['clinical-evidence-copilot/v1'] = 'clinical-evidence-copilot/v1'
    case_id: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    version: int = 1
    created_at: str = Field(default_factory=now)
    parent_hash: str | None = None
    content_hash: str = ''
    source: Source
    extraction_status: Literal['valid', 'partial', 'invalid', 'failed']
    extraction_metadata: dict = Field(default_factory=dict)
    semantic_validation: Literal['not_clinically_validated'] = 'not_clinically_validated'
    facts: list[Assertion] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    rejected_facts: list[dict] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    soap: dict[str, list[SoapAssertion]] = Field(default_factory=lambda: {s: [] for s in 'SOAP'})
    review_required_fact_ids: list[str] = Field(default_factory=list)
    reviews: list[ReviewRecord] = Field(default_factory=list)

    def computed_hash(self):
        return digest(self.model_dump(mode='json', exclude={'content_hash'}))

    def seal(self):
        self.content_hash = self.computed_hash()
        return self

    def verify(self):
        self.source.verify()
        if not self.content_hash or self.content_hash != self.computed_hash():
            raise ValueError('Packet integrity mismatch')
        # Validate the stored graph and prose, without reinterpreting historical
        # review-routing decisions under a newer heuristic implementation.
        from .evidence import ground_fact
        from .service import assertion_text, soap_section, event_projection_policy
        try:
            evidence = {e.evidence_id: e for e in self.evidence}
            fact_ids = {f.fact_id for f in self.facts}
            if len(evidence) != len(self.evidence) or len(fact_ids) != len(self.facts):
                raise ValueError('Duplicate graph IDs')
            for e in self.evidence:
                raw = dict(category='other', concept=None, original_term=e.quote, polarity='uncertain',
                    temporality='unknown', experiencer='unknown', attributes=None,
                    evidence=dict(quote=e.quote, start=e.start, end=e.end))
                _, spans = ground_fact(raw, self.source)
                if spans[0] != e:
                    raise ValueError('Source locator mismatch')
            for f in self.facts:
                _, spans = ground_fact(f.assertion.model_dump(), self.source)
                ground_fact(f.original_fact, self.source)
                if f.evidence_ids != [e.evidence_id for e in spans] or any(evidence.get(e.evidence_id) != e for e in spans):
                    raise ValueError('Assertion evidence mismatch')
            if not set(self.review_required_fact_ids) <= fact_ids:
                raise ValueError('Unknown review target')
            if set(self.soap) != set('SOAP'):
                raise ValueError('Invalid SOAP section set')
            linked = []
            for key, rows in self.soap.items():
                for row in rows:
                    if len(row.fact_ids) != 1:
                        raise ValueError('Each projected assertion must name its source fact')
                    f = next(f for f in self.facts if f.fact_id == row.fact_ids[0])
                    projection_version = self.extraction_metadata.get('soap_projection_version', 'soap/v1')
                    if projection_version not in {'soap/v1', 'soap/v2', 'soap/v3', 'soap/v4', 'soap/v5', 'soap/v6'}:
                        raise ValueError('Unsupported SOAP projection version')
                    expected_section = soap_section(f, projection_version)
                    verification_record = (next((r for r in self.extraction_metadata.get('evidence_verification', {}).get('assertions', [])
                        if r['fact_id'] == f.fact_id), None) if projection_version == 'soap/v6' else None)
                    if key != expected_section or row.text != assertion_text(f,projection_version,verification_record,event_projection_policy(self)) or row.evidence_ids != f.evidence_ids or row.review_status != f.review_status or row.requires_review != (f.fact_id in self.review_required_fact_ids):
                        raise ValueError('SOAP projection differs from linked assertion')
                    linked.extend(row.fact_ids)
            if len(linked) != len(self.facts) or set(linked) != fact_ids:
                raise ValueError('SOAP missing or duplicating facts')
            for i in self.issues:
                if not set(i.fact_ids) <= fact_ids or not set(i.evidence_ids) <= evidence.keys():
                    raise ValueError('Issue references unknown evidence/facts')
            for c in self.conflicts:
                if not set(c.fact_ids) <= fact_ids:
                    raise ValueError('Conflict references unknown facts')
            if self.extraction_metadata.get('soap_projection_version') == 'soap/v4':
                from .atomic import validate_checklist
                from .action_state import inspect_action
                validate_checklist(self.extraction_metadata.get('atomic_source_checklist', {}), self)
                from .action_state import VERSION as action_version
                detector_version = self.extraction_metadata.get('action_state_checklist',{}).get('version',action_version)
                if any(f.action_status != inspect_action(f,self.source,version=detector_version)['action_state'] for f in self.facts):
                    raise ValueError('Action state differs from versioned source detector')
            if self.extraction_metadata.get('soap_projection_version') == 'soap/v5':
                from .service import validate_v5_projection
                validate_v5_projection(self)
            if self.extraction_metadata.get('soap_projection_version') == 'soap/v6':
                from .service import validate_v6_projection
                validate_v6_projection(self)
        except (ValueError, StopIteration, KeyError, TypeError) as exc:
            raise ValueError('Packet consistency violation: '+str(exc)) from exc
        return self
