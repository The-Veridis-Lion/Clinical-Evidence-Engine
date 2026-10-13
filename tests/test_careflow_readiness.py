"""Fixed documentation-readiness oracles; never clinical accuracy scores."""
from copy import deepcopy
from datetime import date
import json

import pytest

from clinical_intelligence.careflow.contracts import Case, Review, EvidenceUpdate
from clinical_intelligence.careflow.engine import evaluate
from clinical_intelligence.careflow.demo import referral_case, supplemental
from clinical_intelligence.careflow.service import CareFlow


def case(**changes):
    value = referral_case()
    value.update(changes)
    return Case.model_validate_json(json.dumps(value))


def check(packet, requirement):
    return next(c for c in packet['checks'] if c['requirement'] == requirement)


def test_missing_is_insufficient_and_never_ready():
    packet = evaluate(case())
    assert check(packet, 'clinical_summary')['status'] == 'INSUFFICIENT_EVIDENCE'
    assert packet['readiness'] == 'NEEDS_EVIDENCE'
    assert packet['gaps']


def test_explicit_contrary_is_distinct_from_missing():
    value = referral_case()
    extra = supplemental('clinical_summary', False, 'Summary explicitly not attached.')
    value['sources'] += extra['sources']
    value['facts'] += extra['facts']
    packet = evaluate(case(**value))
    assert check(packet, 'clinical_summary')['status'] == 'NOT_SUPPORTED'
    assert packet['readiness'] != 'DOCUMENTATION_READY'


def test_unrelated_material_does_not_fill_gap():
    value = referral_case()
    extra = supplemental('clinical_summary', True, 'Summary for another request.')
    extra['facts'][0]['request_id'] = 'REF-OTHER'
    value['sources'] += extra['sources']
    value['facts'] += extra['facts']
    packet = evaluate(case(**value))
    assert check(packet, 'clinical_summary')['status'] == 'INSUFFICIENT_EVIDENCE'
    assert packet['excluded_facts'][0]['reason'] == 'request_mismatch'


def test_conflict_keeps_both_facts_even_if_positive_arrives_later():
    value = referral_case()
    for assertion in (False, True):
        extra = supplemental('clinical_summary', assertion, f'Summary attached: {assertion}.')
        value['sources'] += extra['sources']
        value['facts'] += extra['facts']
    packet = evaluate(case(**value))
    result = check(packet, 'clinical_summary')
    assert result['status'] == 'CONFLICTED'
    assert len(result['fact_ids']) == 2
    assert result['conflicts'] and packet['readiness'] == 'CONFLICTED'


def test_review_is_separate_and_revisioned_correction_is_audited(tmp_path):
    app = CareFlow(tmp_path / 'careflow.sqlite')
    packet = app.create(case())
    review = Review.model_validate_json(json.dumps({
        'reviewer_id': 'advanced-reviewer', 'reviewer_type': 'advanced_ai',
        'model': 'offline-test', 'model_version': '1',
        'basis_revision': 1, 'basis_packet_sha256': packet['packet_sha256'],
        'fact_ids': [packet['facts'][0]['fact_id']],
        'judgment': 'PROPOSE_CORRECTION', 'reason': 'Clinical summary is missing.',
        'proposed_actions': ['Obtain the request-specific clinical summary.'],
    }))
    app.review('CF-REF-001', review)
    assert app.packet('CF-REF-001')['readiness'] == 'NEEDS_EVIDENCE'
    update = EvidenceUpdate.model_validate_json(json.dumps({
        'expected_revision': 1, 'review': review.model_dump(mode='json'),
        **supplemental('clinical_summary', True, 'Request-specific clinical summary attached.'),
    }))
    revised = app.add_evidence('CF-REF-001', update)
    assert revised['revision'] == 2
    assert check(revised, 'clinical_summary')['status'] == 'SUPPORTED'
    assert app.packet('CF-REF-001', revision=1)['readiness'] == 'NEEDS_EVIDENCE'
    assert app.audit('CF-REF-001')['verified'] is True
    assert len(app.reviews('CF-REF-001')) == 2


@pytest.mark.parametrize('patient,request_id', [('PAT-A', 'REQ-11'), ('PAT-B', 'REQ-99'), ('患者-C', '请求-7')])
@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('assertions,expected', [([], 'INSUFFICIENT_EVIDENCE'), ([None], 'INSUFFICIENT_EVIDENCE'),
                                              ([True], 'SUPPORTED'), ([False], 'NOT_SUPPORTED'),
                                              ([True, False], 'CONFLICTED')])
def test_generalized_assertion_states(patient, request_id, kind, structured, assertions, expected):
    raw = referral_case(patient=patient, request=request_id, request_type=kind, structured=structured)
    for index, assertion in enumerate(assertions):
        extra = supplemental('clinical_summary', assertion, f'Original record {index}: state {assertion} / {patient}.',
                             patient=patient, request=request_id, structured=structured)
        raw['sources'] += extra['sources']
        raw['facts'] += extra['facts']
    packet = evaluate(case(**raw))
    assert check(packet, 'clinical_summary')['status'] == expected
    assert (packet['readiness'] == 'DOCUMENTATION_READY') is (expected == 'SUPPORTED')
    assert packet['ruleset']['version'] == '1.0.0'
    assert packet['packet_sha256']


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('requirement,trigger', [('investigation_result', 'investigation_required'),
                                              ('therapy_completed', 'therapy_required')])
@pytest.mark.parametrize('trigger_values,documented,expected', [
    ([], True, 'INSUFFICIENT_EVIDENCE'), ([None], True, 'INSUFFICIENT_EVIDENCE'),
    ([False], None, 'NOT_APPLICABLE'), ([True], None, 'INSUFFICIENT_EVIDENCE'),
    ([True], True, 'SUPPORTED'), ([True], False, 'NOT_SUPPORTED'), ([False, True], True, 'CONFLICTED'),
])
def test_generalized_conditional_rules(kind, requirement, trigger, trigger_values, documented, expected):
    raw = referral_case(patient='OTHER-PATIENT', request='OTHER-REQUEST', request_type=kind)
    removed = {f['evidence'][0]['source_id'] for f in raw['facts'] if f['requirement'] == trigger}
    raw['facts'] = [f for f in raw['facts'] if f['requirement'] != trigger]
    raw['sources'] = [s for s in raw['sources'] if s['source_id'] not in removed]
    for value in trigger_values:
        extra = supplemental(trigger, value, f'Explicit trigger declaration: {value}.', patient='OTHER-PATIENT', request='OTHER-REQUEST')
        raw['sources'] += extra['sources']
        raw['facts'] += extra['facts']
    if documented is not None:
        extra = supplemental(requirement, documented, f'Required material documented: {documented}.', patient='OTHER-PATIENT', request='OTHER-REQUEST')
        raw['sources'] += extra['sources']
        raw['facts'] += extra['facts']
    result = check(evaluate(case(**raw)), requirement)
    assert result['status'] == expected
    if expected == 'NOT_APPLICABLE':
        assert result['clinical_refs'] and result['derivation']['trigger'] is False


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('structured', [False, True])
@pytest.mark.parametrize('field,value,reason', [
    ('patient_id', 'WRONG-PATIENT', 'patient_mismatch'), ('request_id', 'WRONG-REQUEST', 'request_mismatch'),
    ('service_code', 'WRONG-SERVICE', 'service_mismatch'), ('code_system', 'WRONG-SYSTEM', 'service_mismatch'),
])
def test_generalized_fact_isolation(kind, structured, field, value, reason):
    raw = referral_case(patient='ISOLATED-PAT', request='ISOLATED-REQ', request_type=kind)
    extra = supplemental('clinical_summary', True, 'Material with mismatching assertion scope.',
                         patient='ISOLATED-PAT', request='ISOLATED-REQ', structured=structured)
    extra['facts'][0][field] = value
    raw['sources'] += extra['sources']
    raw['facts'] += extra['facts']
    packet = evaluate(case(**raw))
    assert check(packet, 'clinical_summary')['status'] == 'INSUFFICIENT_EVIDENCE'
    assert packet['excluded_facts'][0]['reason'] == reason


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('field,value,reason', [
    ('patient_id', 'OTHER-PATIENT', 'patient_mismatch'), ('encounter_id', 'OTHER-ENCOUNTER', 'encounter_mismatch'),
    ('available_at', None, 'availability_unknown'), ('available_at', '2026-10-15', 'not_available_as_of'),
    ('recorded_at', '2026-10-12', 'inconsistent_recorded_and_available_dates'),
])
def test_generalized_source_scope_and_availability(kind, field, value, reason):
    raw = referral_case(request_type=kind)
    extra = supplemental('clinical_summary', True, 'Source-scoped clinical summary.')
    extra['sources'][0][field] = value
    raw['sources'] += extra['sources']
    raw['facts'] += extra['facts']
    packet = evaluate(case(**raw))
    assert check(packet, 'clinical_summary')['status'] == 'INSUFFICIENT_EVIDENCE'
    assert packet['excluded_facts'][0]['reason'] == reason
