"""Ordinary source intake: one original text, an explicit request and attachments.

The model extracts clinical context. It cannot create the independent paperwork
required by the existing readiness rules. Original responses and call attempts
remain in the existing extraction cache/ledger.
"""
from datetime import date
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..clinical_notes.dataset import sha
from .contracts import ClinicalBinding, Contract, Identifier, Request, Source
from .extraction import extract_document, extraction_context, STRUCTURED_TASK, LEGACY_TASK
from .raw_input import build_case
from .scheduler import CallLedger
from .service import RevisionConflict


DEFAULT_EXTRACTION_TASK = STRUCTURED_TASK


class ClinicalAssociation(Contract):
    """An explicit request target, selected after extraction without a truth vote."""
    requirement: Literal['referral_reason', 'investigation_result', 'therapy_completed']
    concept: str = Field(min_length=1, max_length=2000)
    category: str = Field(min_length=1, max_length=100)
    clinical_purpose: Literal['therapeutic', 'diagnostic', 'unknown'] = 'unknown'


class SelectedClinicalAssociation(Contract):
    """Associate already saved facts; selection does not certify their truth."""
    expected_revision: int = Field(ge=1)
    basis_packet_sha256: Identifier
    clinical_fact_ids: list[Identifier] = Field(min_length=1, max_length=100)
    requirement: Literal['referral_reason', 'investigation_result', 'therapy_completed']
    clinical_purpose: Literal['therapeutic', 'diagnostic', 'unknown'] = 'unknown'
    received_at: date
    actor_id: Identifier
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode='after')
    def distinct_selection(self):
        if len(self.clinical_fact_ids) != len(set(self.clinical_fact_ids)):
            raise ValueError('Choose each original clinical fact once')
        if not self.reason.strip():
            raise ValueError('Explain the request association')
        return self


def selected_association_update(current, packet, selection):
    """Build the existing evidence update from exact current context identities."""
    from ..claims_review.prepare import digest
    from .contracts import Case, EvidenceUpdate
    case = Case.model_validate_json(json.dumps(current))
    known = {fact['context_fact_id'] for context in packet.get('clinical_context', []) for fact in context['facts']}
    if not set(selection.clinical_fact_ids) <= known:
        raise ValueError('Selected clinical fact is absent from this request context')
    scope = {key:getattr(case.request,key) for key in ('patient_id','request_id','service_code','code_system')}
    identity = digest(['careflow-selected-clinical-association/1',scope,selection.model_dump(mode='json')])[:24]
    source_id = 'selected-association-'+identity
    binding = ClinicalBinding(binding_id='selected-'+identity,binding_source_id=source_id,
        **scope,requirement=selection.requirement,clinical_fact_ids=selection.clinical_fact_ids,
        clinical_purpose=selection.clinical_purpose)
    association_source = {
        'source_id':source_id,'patient_id':case.request.patient_id,'encounter_id':case.request.encounter_id,
        'available_at':str(selection.received_at),'recorded_at':None,'event_date':None,'event_link_id':None,
        'record_type':'order','source_kind':'structured_record','origin':'request_intake',
        'availability_basis':'explicit_case_metadata','original_locator':None,
        'content':{'clinical_binding':binding.model_dump(mode='json'),
            'association_version':'careflow-selected-clinical-association/1',
            'selected_by':selection.actor_id,'selection_reason':selection.reason,
            'basis_revision':selection.expected_revision,'basis_packet_sha256':selection.basis_packet_sha256,
            'boundary':'Request relevance selection only; no provider order, form, clinical truth or course completion is created.'}}
    return EvidenceUpdate.model_validate_json(json.dumps({
        'expected_revision':selection.expected_revision,'sources':[association_source],
        'clinical_bindings':[binding.model_dump(mode='json')],
        'intake':{'actor_id':selection.actor_id,'actor_type':'intake_service',
            'basis_revision':selection.expected_revision,'basis_packet_sha256':selection.basis_packet_sha256,
            'reason':selection.reason}}))


class ClinicalTextIntake(Contract):
    schema_version: Literal['careflow-clinical-text-intake/1'] = 'careflow-clinical-text-intake/1'
    case_id: Identifier
    request: Request
    review_as_of: date
    received_at: date
    document_id: Identifier
    input_kind: Literal['note', 'dialogue']
    text: str = Field(min_length=1, max_length=100_000)
    document_role: Literal['clinical_summary'] | None = None
    # An explicit request association, not a clinical truth assertion. Missing on
    # historical intakes; never inferred from the service code or patient alone.
    clinical_reason: str | None = Field(default=None, max_length=4000)
    clinical_associations: list[ClinicalAssociation] = Field(default_factory=list, max_length=100)
    extraction_task: Literal['clinical-structured-extraction/1', 'legacy-clinical-extraction/1'] | None = None
    materials: list[Source] = Field(default_factory=list)

    @model_validator(mode='after')
    def source_is_distinct(self):
        if not self.text.strip():
            raise ValueError('An original nonempty note or dialogue is required')
        if self.document_id in {s.source_id for s in self.materials}:
            raise ValueError('The original text and material source IDs must be distinct')
        if len({s.source_id for s in self.materials}) != len(self.materials):
            raise ValueError('Material source IDs must be unique')
        return self


def runtime_paths(database, cache=None, ledger=None):
    root = Path(database).resolve().parent / (Path(database).stem + '-luna')
    return Path(cache) if cache else root / 'cache', Path(ledger) if ledger else root / 'calls.sqlite3'


def clinical_reason_bindings(case, reason, *, received_at):
    """Propose exact-concept request associations; source support is recomputed.

    A clinical question is independent intake metadata. Matching a concept in it
    establishes relevance only. Negative, uncertain and unsupported proposals
    stay candidates and cannot waive the existing source/patient/time checks.
    """
    from ..claims_review.prepare import digest
    from .clinical_context import prepared_context
    if not reason or not reason.strip():
        return [], [], []
    normalized = ' '.join(reason.casefold().split())
    scope = {k: getattr(case.request, k) for k in ('patient_id', 'request_id', 'service_code', 'code_system')}
    sources, bindings, decisions = [], [], []
    for context in prepared_context(case):
        for fact in context['facts']:
            concept = ' '.join((fact['concept'] or '').casefold().split())
            selected = (fact['category'] in {'symptom', 'condition', 'diagnosis', 'observation'}
                and bool(concept) and re.search(r'(?<!\w)' + re.escape(concept) + r'(?!\w)', normalized))
            if not selected:
                continue
            identity = digest(['careflow-request-reason-association/1', scope, reason, fact['context_fact_id']])[:24]
            source_id = 'reason-association-' + identity
            binding = ClinicalBinding(binding_id='reason-' + identity, binding_source_id=source_id,
                **scope, requirement='referral_reason', clinical_fact_ids=[fact['context_fact_id']])
            sources.append(Source.model_validate_json(json.dumps({
                'source_id': source_id, 'patient_id': case.request.patient_id,
                'encounter_id': case.request.encounter_id, 'available_at': str(received_at),
                'recorded_at': None, 'event_date': None, 'event_link_id': None,
                'record_type': 'order', 'source_kind': 'structured_record', 'origin': 'request_intake',
                'availability_basis': 'explicit_case_metadata', 'original_locator': None,
                'content': {'clinical_binding': binding.model_dump(mode='json'),
                    'request_clinical_reason': reason, 'association_version': 'careflow-request-reason-association/1',
                    'association_basis': 'Exact concept in an explicitly supplied request reason; not source entailment.',
                    'original_source_id': context['source_id'], 'original_fact_index': fact['original_fact_index']}})))
            bindings.append(binding)
            decisions.append({'clinical_fact_id': fact['context_fact_id'], 'source_id': context['source_id'],
                'binding_id': binding.binding_id, 'requirement': 'referral_reason',
                'association': 'EXPLICIT_REQUEST_REASON_CONCEPT', 'source_support': 'RECOMPUTED_BY_REQUIREMENT_GATE'})
    return sources, bindings, decisions


def clinical_target_bindings(case, targets, *, received_at):
    from ..claims_review.prepare import digest
    from .clinical_context import prepared_context
    sources, bindings, decisions = [], [], []
    scope = {k:getattr(case.request, k) for k in ('patient_id','request_id','service_code','code_system')}
    for target in targets:
        for context in prepared_context(case):
            for fact in context['facts']:
                if (fact['category'] != target.category or
                        ' '.join((fact['concept'] or '').casefold().split()) != ' '.join(target.concept.casefold().split())):
                    continue
                identity = digest(['careflow-request-clinical-target/1', scope,
                    target.model_dump(mode='json'), fact['context_fact_id']])[:24]
                source_id = 'clinical-target-' + identity
                binding = ClinicalBinding(binding_id='target-'+identity, binding_source_id=source_id,
                    **scope, requirement=target.requirement, clinical_fact_ids=[fact['context_fact_id']],
                    clinical_purpose=target.clinical_purpose)
                sources.append(Source.model_validate_json(json.dumps({
                    'source_id':source_id, 'patient_id':case.request.patient_id,
                    'encounter_id':case.request.encounter_id, 'available_at':str(received_at),
                    'recorded_at':None,'event_date':None,'event_link_id':None,
                    'record_type':'order','source_kind':'structured_record','origin':'request_intake',
                    'availability_basis':'explicit_case_metadata','original_locator':None,
                    'content':{'clinical_binding':binding.model_dump(mode='json'),
                        'association_version':'careflow-request-clinical-target/1',
                        'original_target':target.model_dump(mode='json'),
                        'original_source_id':context['source_id'], 'original_fact_index':fact['original_fact_index']}})))
                bindings.append(binding)
                decisions.append({'clinical_fact_id':fact['context_fact_id'], 'source_id':context['source_id'],
                    'binding_id':binding.binding_id,'requirement':target.requirement,
                    'association':'EXPLICIT_REQUEST_CLINICAL_TARGET','source_support':'RECOMPUTED_BY_REQUIREMENT_GATE'})
    return sources, bindings, decisions


def extract_intake(app, intake, *, cache=None, ledger=None, provider=None):
    """Use the real request identity, without predeclared extraction indices.

    Duplicate cases are rejected before dispatch. The existing cache rejects
    changed identities and never replays an unresolved dispatch. The caller must
    serialize concurrent submissions for the same case (the HTTP entry does).
    """
    try:
        app.packet(intake.case_id)
    except KeyError:
        pass
    else:
        raise RevisionConflict('Case already exists; use its material update entry')
    source = {
        'source_id': intake.document_id, 'patient_id': intake.request.patient_id,
        'encounter_id': intake.request.encounter_id, 'available_at': intake.received_at.isoformat(),
        'origin': 'request_intake', 'source_kind': 'clinical_text',
        'recorded_at': None, 'event_date': None, 'event_link_id': None,
        'record_type': 'note', 'content': intake.text,
        'availability_basis': 'explicit_case_metadata',
        'original_locator': {'document_id': intake.document_id, 'input_kind': intake.input_kind,
                             'dataset': 'user-supplied', 'source_sha256': sha(intake.text)},
    }
    materials = [s.model_dump(mode='json') for s in intake.materials]
    if intake.document_role == 'clinical_summary':
        from ..claims_review.facts import source_key
        from .requirement_support import material_envelope
        attachment_id = intake.document_id + ':summary-attachment'
        if attachment_id in {s['source_id'] for s in materials}:
            raise ValueError('Summary attachment identity conflicts with a supplied source')
        request = intake.request.model_dump(mode='json')
        scope = {key: request[key] for key in ('patient_id', 'request_id', 'service_code', 'code_system')}
        material = {**scope, 'document_type': 'clinical_summary', 'document_role': 'clinical_summary',
                    'summary_source_id': intake.document_id, 'summary_sha256': source_key(source)}
        materials.append({**source, 'source_id': attachment_id, 'record_type': 'order',
            'source_kind': 'structured_record', 'original_locator': None,
            'content': {'material': material, 'requirement_support': material_envelope(request,
                'clinical_summary', 'clinical_summary', {'source_id': attachment_id, 'field': 'material'}),
                'intake_declaration': 'User attached the received original text as the request clinical summary; clinical correctness is not certified.'}})
    # Validate the ordinary request/material contract before any model call.
    build_case(intake.case_id, intake.request, intake.review_as_of, [source, *materials])
    from .rules import ruleset
    ruleset(intake.request.ruleset_id, intake.request.ruleset_version, intake.request.request_type)
    record = {'document_id': intake.document_id,
              'case_group': intake.request.encounter_id or intake.request.patient_id,
              'dataset': 'user-supplied', 'input_kind': intake.input_kind,
              'text': intake.text, 'source_sha256': sha(intake.text)}
    cache_path, ledger_path = runtime_paths(app.store.path, cache, ledger)
    calls = CallLedger(ledger_path)
    before = len(calls.attempts())
    result = extract_document(record, cache_path, calls, provider=provider, max_attempts=1,
        task_version=None if intake.extraction_task == LEGACY_TASK else intake.extraction_task or DEFAULT_EXTRACTION_TASK)
    case, receipt = build_case(intake.case_id, intake.request, intake.review_as_of,
        [source, *materials], extractions=[extraction_context(intake.document_id, result)])
    association_sources, bindings, associations = clinical_reason_bindings(
        case, intake.clinical_reason, received_at=intake.received_at)
    target_sources, target_bindings, target_decisions = clinical_target_bindings(
        case, intake.clinical_associations, received_at=intake.received_at)
    association_sources.extend(target_sources); bindings.extend(target_bindings); associations.extend(target_decisions)
    if bindings:
        case, receipt = build_case(intake.case_id, intake.request, intake.review_as_of,
            [*case.sources, *association_sources], extractions=case.clinical_context, clinical_bindings=bindings)
    packet = (app._create_from_extraction(case, record, cache_path, calls)
        if 'structured_extraction' in result else app.create(case))
    new_attempts = [r for r in calls.attempts()[before:] if r['document_id'] == intake.document_id]
    extraction_receipt = {
        'schema_version': 'careflow-clinical-intake-receipt/1',
        'document_id': intake.document_id, 'source_sha256': sha(intake.text),
        'extraction_identity': result['identity'], 'accepted_attempt': result['attempt'],
        'actual_new_attempts': len(new_attempts), 'reused_success': not new_attempts,
        'usage': result['usage'], 'clinical_fact_count': len(result['extraction']['facts']),
        'cache_identity': sha(json.dumps(result['identity'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))),
        'clinical_binding_candidates': len(bindings), 'clinical_associations': associations,
        'unmatched_request_reason': bool(intake.clinical_reason and not bindings),
        'boundary': 'Request-reason associations are candidates checked against original clinical sources. Formal paperwork remains separately required; no order, PA form or completed course is inferred.',
    }
    with app.store.transaction() as conn:
        app.store.append_event(conn, intake.case_id, 'CLINICAL_SOURCE_EXTRACTED', extraction_receipt)
    return {'packet': packet, 'intake_receipt': receipt, 'extraction_receipt': extraction_receipt}
