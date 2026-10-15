"""Opt-in clinical semantics sidecar; frozen ClinicalFact JSON is never expanded.

The old four-attribute contract cannot express frequency or event time. This
versioned proposal carries those dimensions without retyping old raw values.
Every asserted value is subsequently checked by the shared source verifier.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class ClinicalSemanticsV2(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal['clinical-fact-semantics/2'] = 'clinical-fact-semantics/2'
    frequency: str | None
    event_time: str | None
    duration: str | None
    action_state: Literal['planned', 'completed', 'not_completed', 'ongoing', 'discussed', 'unknown']
    completion_scope: Literal['single_event', 'course', 'full_course', 'unknown'] | None
    assertion_basis: Literal['patient_report', 'clinician_assessment', 'clinician_observation',
                             'documented_history', 'discussion', 'unknown', 'patient_reported']
    action_type: str | None


class SemanticsRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fact_id: str = Field(min_length=1)
    source_sha256: str
    semantics: ClinicalSemanticsV2
    origin: str = Field(min_length=1)


class StructuredSemanticsRecord(BaseModel):
    """A partial representation retains valid dimensions and explicit failures."""
    model_config = ConfigDict(extra='forbid')
    fact_id: str = Field(min_length=1)
    source_sha256: str
    semantics: dict
    origin: Literal['original_structured_extraction']
    normalization_version: Literal['clinical-structured-normalization/1']
    invalid_fields: list[str]

    @model_validator(mode='after')
    def validate_dimensions(self):
        fields=ClinicalSemanticsV2.model_fields
        if set(self.semantics)-set(fields) or set(self.semantics)&set(self.invalid_fields):
            raise ValueError('Structured semantics must separate valid and invalid fields')
        if not set(fields) <= set(self.semantics)|set(self.invalid_fields):
            raise ValueError('Missing structured semantic dimensions need explicit errors')
        for name,value in self.semantics.items():
            TypeAdapter(fields[name].annotation).validate_python(value,strict=True)
        return self


def checked_records(packet):
    values = packet.extraction_metadata.get('clinical_semantics_v2', [])
    if not isinstance(values, list):
        raise ValueError('Clinical semantics v2 must be a list of explicit records')
    known = {f.fact_id for f in packet.facts}
    result = {}
    for raw in values:
        value = (StructuredSemanticsRecord if 'normalization_version' in raw else SemanticsRecord).model_validate(raw)
        if value.fact_id not in known or value.fact_id in result:
            raise ValueError('Clinical semantics has unknown or duplicate fact identity')
        if value.source_sha256 != packet.source.sha256:
            raise ValueError('Clinical semantics source hash mismatch')
        result[value.fact_id] = value.model_dump(mode='json')
    return result


def bound_human_semantic_correction(packet, item, record):
    """An origin string alone is not an explicit human correction decision."""
    if record is None or not record['origin'].startswith('targeted_semantics_correction/human/'):
        return False
    current=item.assertion.model_dump()
    for event in reversed(packet.extraction_metadata.get('semantic_corrections',[])):
        if (event.get('fact_id')!=item.fact_id or event.get('source_sha256')!=packet.source.sha256
                or event.get('after')!=record or event.get('version',packet.version+1)>packet.version):
            continue
        review=next((r for r in packet.reviews if r.review_id==event.get('review_id')),None)
        return bool(review and review.action=='correct' and review.reviewer.reviewer_type=='human'
            and review.fact_id==item.fact_id and review.applied_version==event['version']
            and review.before==review.after==review.replacement==current
            and set(review.evidence_ids)<=set(item.evidence_ids))
    return False


def apply_semantics(claim, record):
    """Build a new verification proposal; the original ClinicalFact is untouched."""
    if record is None:
        return claim
    semantics = record['semantics']
    claim = {**claim, 'attributes': dict(claim['attributes'])}
    # Explicit null in a v2 proposal means this dimension is not asserted. The
    # original duration value remains in original_fact and the version history.
    claim['attributes'].pop('duration', None)
    for name in ('duration', 'frequency'):
        if semantics.get(name) is not None:
            claim['attributes'][name] = semantics[name]
    for name in ('event_time', 'action_type', 'action_state', 'completion_scope'):
        if name not in semantics:
            # A mechanical invalid field is absent from the proposal. The Claim
            # transport requires an unknown action placeholder; the field and
            # raw error remain explicit in the structured record and quarantine.
            if 'normalization_version' in record:
                claim[name] = 'unknown' if name == 'action_state' else None
            continue
        value = semantics[name]
        claim[name] = None if name == 'completion_scope' and value == 'unknown' else value
    claim['reporting_basis'] = semantics.get('assertion_basis',claim['reporting_basis'])
    return claim


def semantic_subject_changed(fact, original):
    """Citation ordering does not invalidate unchanged event/attribute proposals.

    Any clinical field change or a different cited span still invalidates the old
    sidecar. This only recognizes an exact permutation of the same evidence.
    """
    current = fact.model_dump()
    citation_fields = {'evidence', 'supporting_evidence', 'provenance'}
    if {k:v for k,v in current.items() if k not in citation_fields} != {
            k:v for k,v in original.items() if k not in citation_fields}:
        return True
    def spans(value):
        return sorted((p['start'], p['end'], p['quote']) for p in
                      [value['evidence'], *value.get('supporting_evidence', [])])
    return spans(current) != spans(original)


CITATION_PRESERVATION_VERSION = 'citation-permutation-preservation/1'


def citation_preservation_review(packet, review):
    """A new human citation edit may adopt the scoped policy for this fact only."""
    from ..dialogue_first.contract import DialogueFact
    if (review.action != 'correct' or review.reviewer.reviewer_type != 'human'
            or packet.extraction_metadata.get('soap_projection_version') != 'soap/v6'):
        return False
    item = next((f for f in packet.facts if f.fact_id == review.fact_id), None)
    semantic = checked_records(packet).get(review.fact_id)
    if item is None or semantic is None:
        return False
    after = DialogueFact.model_validate(review.after)
    # A source selection cannot restore semantics tied to a changed clinical
    # proposition or newly selected evidence. Both comparisons must be exact.
    if (semantic_subject_changed(after, review.before)
            or semantic_subject_changed(after, item.original_fact)
            or after.model_dump() == item.original_fact):
        return False
    return True


def citation_preservation_targets(packet):
    """Validate retained per-fact events without reinterpreting historical packets."""
    targets = set()
    for review in packet.reviews:
        if review.correction_contract_version is None:
            continue
        if not citation_preservation_review(packet, review):
            raise ValueError('Citation preservation must bind an exact human citation-only correction')
        targets.add(review.fact_id)
    return targets


MAIN_DIMENSIONS = {'category', 'concept', 'experiencer', 'reporting_basis', 'polarity', 'temporality'}
EVENT_DIMENSIONS = {'event_time', 'action_type', 'action_state', 'completion_scope'}


def component_result(result, dimensions):
    checks = [c for c in result['dimension_checks'] if c['dimension'] in dimensions]
    asserted = [c for c in checks if c['status'] != 'NOT_ASSERTED']
    if result['status'] == 'CONFLICTED':
        status = 'CONFLICTED'
    elif any(c['status'] == 'CONTRADICTED' for c in asserted):
        status = 'CONTRADICTED'
    elif not checks or any(c['status'] == 'UNVERIFIED' for c in asserted):
        status = 'INSUFFICIENT_EVIDENCE'
    elif dimensions == MAIN_DIMENSIONS and not MAIN_DIMENSIONS <= {c['dimension'] for c in checks}:
        status = 'INSUFFICIENT_EVIDENCE'
    else:
        status = 'SUPPORTED_BY_SOURCE' if asserted else 'NOT_ASSERTED'
    return {'status': status, 'dimension_checks': checks,
            'unresolved_dimensions': [c['dimension'] for c in asserted if c['status'] in {'UNVERIFIED', 'CONTRADICTED'}]}


def split_verification(record):
    result = record['result']
    main = component_result(result, MAIN_DIMENSIONS)
    event = component_result(result, EVENT_DIMENSIONS)
    if 'hypothetical_discussion_not_committed_plan' in result.get('uncertainty',[]):
        event['modality'] = 'conditional_consideration'
        event['interpretation'] = 'The source expresses a conditional treatment topic, not a committed plan, completed discussion, or executed therapy.'
    attributes = [c for c in result['dimension_checks'] if c['dimension'].startswith('attributes.')]
    targets = main['unresolved_dimensions'] + event['unresolved_dimensions'] + [
        c['dimension'] for c in attributes if c['status'] in {'CONTRADICTED', 'UNVERIFIED'}]
    if result['status'] == 'CONFLICTED':
        targets.append('source_conflict')
    if not result['dimension_checks']:
        targets.append('source_semantics')
    if result['risk_route'] != 'AUTO_ACCEPT_ELIGIBLE' and not targets:
        targets.append('uncalibrated_source_method_or_high_risk_category')
    return {'version': 'copilot-component-verification/1', 'main_assertion': main,
            'event': event, 'attributes': attributes, 'review_targets': targets,
            'automatic_eligible': result['risk_route'] == 'AUTO_ACCEPT_ELIGIBLE',
            'clinical_expert_validation': 'NOT_PERFORMED'}


def review_semantics(packet, request):
    """Audit an explicit type correction without rewriting the original fact."""
    from .models import ReviewRecord, digest, now
    from .service import project
    packet.verify()
    if packet.extraction_metadata.get('soap_projection_version') != 'soap/v6':
        raise ValueError('Semantic sidecar corrections require soap/v6')
    if request.base_version != packet.version:
        raise ValueError('Semantic correction base version is stale')
    item = next((f for f in packet.facts if f.fact_id == request.fact_id), None)
    if item is None:
        raise ValueError('Unknown fact_id')
    if not request.reason.strip() or not set(request.evidence_ids) <= set(item.evidence_ids):
        raise ValueError('Semantic correction must cite the existing target evidence and a reason')
    proposal = ClinicalSemanticsV2.model_validate(request.semantics)
    before = checked_records(packet).get(item.fact_id)
    record = SemanticsRecord(fact_id=item.fact_id, source_sha256=packet.source.sha256,
        semantics=proposal, origin=f'targeted_semantics_correction/{request.reviewer.reviewer_type}/{request.reviewer.version}').model_dump(mode='json')
    if before is not None and before['semantics'] == proposal.model_dump(mode='json'):
        raise ValueError('Semantic correction does not change the proposal')
    p = packet.model_copy(deep=True)
    next(f for f in p.facts if f.fact_id == item.fact_id).review_status = 'corrected'
    p.extraction_metadata['clinical_semantics_v2'] = [
        r for r in p.extraction_metadata.get('clinical_semantics_v2', []) if r['fact_id'] != item.fact_id] + [record]
    p.version += 1
    p.parent_hash = packet.content_hash
    p.created_at = now()
    original = item.assertion.model_dump()
    review_id = 'review-' + digest([packet.content_hash, record, p.version])[:20]
    p.reviews.append(ReviewRecord(base_version=packet.version, fact_id=item.fact_id,
        action='correct', reason=request.reason, evidence_ids=request.evidence_ids,
        reviewer=request.reviewer, replacement=original, review_id=review_id,
        recorded_at=p.created_at, applied_version=p.version, before=original, after=original,
        supersedes_review_id=next((r.review_id for r in reversed(packet.reviews) if r.fact_id==item.fact_id),None)))
    p.extraction_metadata.setdefault('semantic_corrections', []).append({
        'review_id': review_id, 'fact_id': item.fact_id, 'version': p.version,
        'source_sha256': p.source.sha256, 'before': before, 'after': record,
        'original_clinical_fact_unchanged': True})
    from .atomic import checklist
    previous = p.extraction_metadata.get('atomic_source_checklist', {})
    original_packet = p.model_copy(deep=True)
    from .evidence import ground_fact
    for fact in original_packet.facts:
        fact.assertion, _ = ground_fact(fact.original_fact, original_packet.source)
    p.extraction_metadata['atomic_source_checklist'] = checklist(original_packet,
        previous.get('independent_source_assertions', []))
    return project(p)
