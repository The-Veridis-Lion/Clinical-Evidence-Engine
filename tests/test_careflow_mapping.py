"""Independent clinical existence/relevance/material gates across requests."""
from copy import deepcopy
import json

import pytest

from clinical_intelligence.careflow.clinical_context import prepared_context
from clinical_intelligence.careflow.contracts import Case, ClinicalBinding
from clinical_intelligence.careflow.demo import referral_case, supplemental
from clinical_intelligence.careflow.engine import evaluate


def clinical_request(kind, patient, requirement, *, category='treatment', status='completed',
                     temporality='historical', polarity='present', experiencer='patient'):
    raw = referral_case(patient=patient, request='REQUEST-' + patient, request_type=kind)
    raw['facts'] = [f for f in raw['facts'] if f['requirement'] != requirement]
    if requirement in {'therapy_completed', 'investigation_result'}:
        trigger = 'therapy_required' if requirement == 'therapy_completed' else 'investigation_required'
        raw['facts'] = [f for f in raw['facts'] if f['requirement'] != trigger]
        extra = supplemental(trigger, True, 'Intake request requires this clinical material.', patient=patient, request=raw['request']['request_id'])
        raw['sources'] += extra['sources']; raw['facts'] += extra['facts']
    text = f'Original clinical record for {patient}: the documented clinical event and its state.'
    source = {'source_id': 'CLINICAL-' + patient, 'patient_id': patient, 'encounter_id': raw['request']['encounter_id'],
        'available_at': '2026-10-10', 'origin': 'public_clinical_dataset', 'source_kind': 'clinical_text',
        'recorded_at': None, 'event_date': None, 'record_type': 'note', 'event_link_id': None, 'content': text,
        'original_locator': {'document_id': 'CLINICAL-' + patient}}
    clinical = {'category': category, 'concept': 'documented event', 'original_term': text, 'polarity': polarity,
        'temporality': temporality, 'experiencer': experiencer, 'attributes': None,
        'evidence': {'start': 0, 'end': len(text), 'quote': text}, 'assertion_basis': 'documented_history',
        'attribution_confidence': 'context_supported', 'clinical_status': status, 'supporting_evidence': [], 'provenance': []}
    raw['sources'].append(source)
    raw['clinical_context'] = [{'source_id': source['source_id'], 'extraction': {'document_id': source['source_id'], 'facts': [clinical], 'relationships': []}}]
    base = Case.model_validate_json(json.dumps(raw))
    clinical_id = prepared_context(base)[0]['facts'][0]['context_fact_id']
    binding = ClinicalBinding(binding_id='BINDING-' + patient, binding_source_id='SCOPE-' + patient,
        patient_id=patient, request_id=raw['request']['request_id'], service_code=raw['request']['service_code'],
        code_system=raw['request']['code_system'], requirement=requirement, clinical_fact_ids=[clinical_id],
        clinical_purpose='therapeutic' if requirement == 'therapy_completed' and category == 'procedure' else 'unknown',
        document_role='clinical_summary' if requirement == 'clinical_summary' else None).model_dump(mode='json')
    scope = {**source, 'source_id': binding['binding_source_id'], 'origin': 'constructed_synthetic',
        'source_kind': 'structured_record', 'record_type': 'order', 'original_locator': None,
        'content': {'clinical_binding': binding}}
    raw['sources'].append(scope); raw['clinical_bindings'] = [binding]
    return raw


def check(raw, requirement):
    packet = evaluate(Case.model_validate_json(json.dumps(raw)))
    return next(c['status'] for c in packet['checks'] if c['requirement'] == requirement), packet


@pytest.mark.parametrize('kind,patient', [('referral', 'M-PATIENT-A'), ('prior_authorization', 'M-PATIENT-B')])
@pytest.mark.parametrize('category,status,time,subject,expected', [
    ('treatment', 'completed', 'historical', 'patient', 'SUPPORTED'),
    ('procedure', 'performed', 'current', 'patient', 'SUPPORTED'),
    ('medication', 'administered', 'historical', 'patient', 'SUPPORTED'),
    ('treatment', 'ongoing', 'current', 'patient', 'INSUFFICIENT_EVIDENCE'),
    ('procedure', 'performed', 'planned', 'patient', 'INSUFFICIENT_EVIDENCE'),
    ('treatment', 'completed', 'unknown', 'patient', 'INSUFFICIENT_EVIDENCE'),
    ('procedure', 'performed', 'historical', 'family', 'INSUFFICIENT_EVIDENCE'),
    ('treatment', 'not_completed', 'historical', 'patient', 'NOT_SUPPORTED'),
    ('diagnosis', 'confirmed', 'historical', 'patient', 'INSUFFICIENT_EVIDENCE'),
])
def test_execution_subject_and_time_do_not_promote_plans_or_other_people(kind, patient, category, status, time, subject, expected):
    raw = clinical_request(kind, patient, 'therapy_completed', category=category, status=status, temporality=time, experiencer=subject)
    result, packet = check(raw, 'therapy_completed')
    assert result == expected
    assert packet['clinical_mapping']['version'] == 'careflow-clinical-mapping/1'
    assert packet['clinical_context'][0]['facts'][0]['context_fact_id'] in json.dumps(packet['clinical_mapping'])


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('requirement,category,status,polarity,expected', [
    ('referral_reason', 'diagnosis', 'confirmed', 'present', 'SUPPORTED'),
    ('referral_reason', 'symptom', 'reported', 'present', 'SUPPORTED'),
    ('referral_reason', 'other', 'reported functional limitation', 'present', 'SUPPORTED'),
    ('investigation_result', 'laboratory_result', 'result available', 'absent', 'SUPPORTED'),
    ('investigation_result', 'laboratory_result', 'pending', 'present', 'INSUFFICIENT_EVIDENCE'),
    ('pa_form', 'diagnosis', 'confirmed', 'present', 'INSUFFICIENT_EVIDENCE'),
    ('request_intent', 'diagnosis', 'confirmed', 'present', 'INSUFFICIENT_EVIDENCE'),
    ('clinical_summary', 'symptom', 'reported', 'present', 'SUPPORTED'),
])
def test_clinical_mapping_never_invents_request_paperwork(kind, requirement, category, status, polarity, expected):
    raw = clinical_request(kind, 'SLOT-' + kind, requirement, category=category, status=status, polarity=polarity)
    if requirement == 'pa_form' and kind == 'referral':
        packet = evaluate(Case.model_validate_json(json.dumps(raw)))
        assert not any(f['requirement'] == 'pa_form' for f in packet['facts'])
        assert packet['clinical_mapping']['decisions'][0]['issues']
        return
    result, packet = check(raw, requirement)
    assert result == expected


@pytest.mark.parametrize('mutation', ['patient', 'request', 'service', 'scope_source', 'source_patient', 'source_availability', 'unknown_fact'])
@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_unrelated_or_untraceable_clinical_bindings_remain_insufficient(kind, mutation):
    raw = clinical_request(kind, 'SCOPE-' + kind, 'therapy_completed')
    binding = raw['clinical_bindings'][0]
    if mutation in {'patient', 'request', 'service'}:
        field = {'patient': 'patient_id', 'request': 'request_id', 'service': 'service_code'}[mutation]
        binding[field] = 'UNRELATED'
        raw['sources'][-1]['content']['clinical_binding'] = deepcopy(binding)
    elif mutation == 'scope_source':
        raw['sources'][-1]['content']['clinical_binding'] = {'unrelated': 'order'}
    elif mutation == 'source_patient':
        raw['sources'][-2]['patient_id'] = 'FOREIGN'
    elif mutation == 'source_availability':
        raw['sources'][-2]['available_at'] = None
    else:
        binding['clinical_fact_ids'] = ['ABSENT-ID']
        raw['sources'][-1]['content']['clinical_binding'] = deepcopy(binding)
    assert check(raw, 'therapy_completed')[0] == 'INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_one_supported_target_cannot_hide_an_unknown_required_target(kind):
    raw = clinical_request(kind, 'MULTI-' + kind, 'therapy_completed')
    another = deepcopy(raw['clinical_context'][0]['extraction']['facts'][0])
    another['concept'] = 'other requested therapy'
    another['clinical_status'] = 'ongoing'
    raw['clinical_context'][0]['extraction']['facts'].append(another)
    clinical_ids = [f['context_fact_id'] for f in prepared_context(Case.model_validate_json(json.dumps(raw)))[0]['facts']]
    raw['clinical_bindings'][0]['clinical_fact_ids'] = clinical_ids
    raw['sources'][-1]['content']['clinical_binding'] = deepcopy(raw['clinical_bindings'][0])
    assert check(raw, 'therapy_completed')[0] == 'INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_new_scoped_authority_can_correct_a_mapped_fact_with_audit(tmp_path, kind):
    from clinical_intelligence.careflow.contracts import EvidenceUpdate
    from clinical_intelligence.careflow.service import CareFlow
    raw = clinical_request(kind, 'CORRECT-' + kind, 'therapy_completed', status='ongoing')
    app = CareFlow(tmp_path / 'mapping.sqlite')
    before = app.create(Case.model_validate_json(json.dumps(raw)))
    original_id = before['clinical_mapping']['derived_fact_ids'][0]
    extra = supplemental('therapy_completed', True, 'A new signed source records completed therapy.',
        patient=raw['request']['patient_id'], request=raw['request']['request_id'], amends=original_id, authority=True)
    review = {'reviewer_id': 'independent-reviewer', 'reviewer_type': 'advanced_ai', 'model': 'offline-fixture', 'model_version': '1',
        'basis_revision': 1, 'basis_packet_sha256': before['packet_sha256'], 'fact_ids': [original_id],
        'judgment': 'PROPOSE_CORRECTION', 'reason': 'New corrective source establishes completed execution.'}
    after = app.add_evidence(raw['case_id'], EvidenceUpdate.model_validate_json(json.dumps({
        'expected_revision': 1, 'review': review, **extra})))
    assert next(c['status'] for c in after['checks'] if c['requirement'] == 'therapy_completed') == 'SUPPORTED'
    assert app.packet(raw['case_id'], 1) == before
    assert app.audit(raw['case_id'])['verified']


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('purpose', ['diagnostic', 'unknown'])
def test_completed_diagnostic_procedure_does_not_prove_therapeutic_course(kind, purpose):
    raw = clinical_request(kind, 'PURPOSE-' + kind, 'therapy_completed', category='procedure', status='performed')
    raw['clinical_bindings'][0]['clinical_purpose'] = purpose
    raw['sources'][-1]['content']['clinical_binding'] = deepcopy(raw['clinical_bindings'][0])
    assert check(raw, 'therapy_completed')[0] == 'INSUFFICIENT_EVIDENCE'
