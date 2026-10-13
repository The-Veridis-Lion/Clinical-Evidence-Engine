"""Independent hand-written scenarios and structural generalization regressions.

These fixtures do not use the product's demo generator or rule expectations.
They measure generalizable software behavior, not clinical semantic accuracy.
"""
from copy import deepcopy
import json

import pytest

from clinical_intelligence.careflow.contracts import Case, EvidenceUpdate, Review
from clinical_intelligence.careflow.engine import evaluate
from clinical_intelligence.careflow.service import CareFlow


def independent_case(kind, patient='INDEP-α', request_id='CONSULT-14'):
    rows = [
        ('intent', 'request_intent', True, 'Attending requests evaluation of persistent symptoms.'),
        ('reason', 'referral_reason', True, 'Requested evaluation concerns the documented symptoms.'),
        ('summary', 'clinical_summary', True, 'History and examination are included in this summary.'),
        ('investigation', 'investigation_required', True, 'The request explicitly requires the prior study report.'),
        ('study', 'investigation_result', False, 'The prior study report is explicitly unavailable.'),
        ('therapy', 'therapy_required', None, 'The prior therapy requirement has not been specified.'),
    ]
    rows += [('dest', 'destination', True, 'Recipient: specialty clinic.')] if kind == 'referral' else [
        ('form', 'pa_form', True, 'The prior authorization request form is included.'),
        ('payer', 'payer_context', True, 'Payer request identifier is documented, without eligibility verification.')]
    sources, facts = [], []
    for identifier, requirement, assertion, statement in rows:
        sources.append({
            'source_id': identifier, 'patient_id': patient, 'encounter_id': 'VISIT-5',
            'available_at': '2025-12-02', 'origin': 'constructed_synthetic', 'source_kind': 'synthetic_note',
            'recorded_at': '2025-12-01', 'event_date': None, 'record_type': 'note', 'event_link_id': None,
            'content': 'Document header\r\n' + statement + '\r\nSignature context retained.\r\n',
        })
        facts.append({
            'fact_id': 'assertion-' + identifier, 'patient_id': patient, 'request_id': request_id,
            'service_code': 'evaluation', 'code_system': 'local-request-spec', 'requirement': requirement,
            'assertion': assertion, 'statement': statement, 'interpretation_origin': 'human',
            'evidence': [{'source_id': identifier, 'span_id': identifier + ':L002'}],
        })
    return {'case_id': 'INDEPENDENT-CASE', 'request': {
        'request_id': request_id, 'patient_id': patient, 'encounter_id': 'VISIT-5', 'request_type': kind,
        'service_code': 'evaluation', 'code_system': 'local-request-spec', 'requested_service_date': '2026-01-02',
        'ruleset_id': 'careflow-referral' if kind == 'referral' else 'careflow-pa', 'ruleset_version': '1.0.0',
    }, 'review_as_of': '2025-12-03', 'sources': sources, 'facts': facts}


def model(cls, value):
    return cls.model_validate_json(json.dumps(value))


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_independent_mixed_document_conditions_and_order_invariance(kind):
    raw = independent_case(kind)
    packet = evaluate(model(Case, raw))
    statuses = {c['requirement']: c['status'] for c in packet['checks']}
    assert statuses['request_intent'] == statuses['clinical_summary'] == 'SUPPORTED'
    assert statuses['investigation_result'] == 'NOT_SUPPORTED'
    assert statuses['therapy_completed'] == 'INSUFFICIENT_EVIDENCE'
    assert packet['readiness'] == 'NOT_SUPPORTED'
    assert packet['review_route']['recommended']
    reverse = deepcopy(raw)
    reverse['sources'].reverse()
    reverse['facts'].reverse()
    after = evaluate(model(Case, reverse))
    assert {c['requirement']: c['status'] for c in after['checks']} == statuses
    assert {f['fact_id']: f['fact_sha256'] for f in after['facts']} == {f['fact_id']: f['fact_sha256'] for f in packet['facts']}
    for fact in packet['facts']:
        citation = fact['citations'][0]
        original = next(s for s in raw['sources'] if s['source_id'] == citation['source_id'])
        assert original['content'][citation['start']:citation['end']] == citation['quote']


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('patient,request_id', [('INDEP-α', 'CONSULT-14'), ('INDEP-β', 'REQUEST-88')])
def test_relabelled_retransmission_is_not_new_evidence(tmp_path, kind, patient, request_id):
    raw = independent_case(kind, patient, request_id)
    # Remove the summary from the intake packet: this material is still missing.
    raw['sources'] = [s for s in raw['sources'] if s['source_id'] != 'summary']
    raw['facts'] = [f for f in raw['facts'] if f['requirement'] != 'clinical_summary']
    app = CareFlow(tmp_path / 'db.sqlite')
    before = app.create(model(Case, raw))
    source = deepcopy(raw['sources'][0])
    source['source_id'] = 'new-id-same-document'
    fact = deepcopy(raw['facts'][0])
    fact.update(fact_id='new-id-same-passage', requirement='clinical_summary')
    fact['evidence'] = [{'source_id': source['source_id'], 'span_id': source['source_id'] + ':L002'}]
    review = {'reviewer_id': 'external-ai', 'reviewer_type': 'advanced_ai', 'model': 'test', 'model_version': 'v1',
              'basis_revision': 1, 'basis_packet_sha256': before['packet_sha256'], 'fact_ids': [],
              'judgment': 'PROPOSE_CORRECTION', 'reason': 'Attempt to relabel an already seen document as new material.'}
    update = model(EvidenceUpdate, {'expected_revision': 1, 'sources': [source], 'facts': [fact], 'review': review})
    with pytest.raises(ValueError, match='Previously received content'):
        app.add_evidence(raw['case_id'], update)
    assert app.packet(raw['case_id']) == before
    assert app.audit(raw['case_id'])['verified']


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_unresolved_conflict_is_visible_even_when_requirement_is_inapplicable(kind):
    raw = independent_case(kind)
    for f in raw['facts']:
        if f['requirement'] == 'investigation_required':
            f['assertion'] = False
    another = deepcopy(next(f for f in raw['facts'] if f['requirement'] == 'investigation_result'))
    another.update(fact_id='opposing-study-fact', assertion=True)
    raw['facts'].append(another)
    packet = evaluate(model(Case, raw))
    assert next(c for c in packet['checks'] if c['requirement'] == 'investigation_result')['status'] == 'NOT_APPLICABLE'
    assert any(set(c['fact_ids']) == {'assertion-study', 'opposing-study-fact'} for c in packet['unresolved_conflicts'])


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('exclusion', ['patient_mismatch', 'not_available_as_of', 'ungrounded_citation'])
def test_excluded_amendment_cannot_change_an_in_scope_fact(kind, exclusion):
    raw = independent_case(kind)
    original = next(f for f in raw['facts'] if f['requirement'] == 'clinical_summary')
    source = {'source_id': 'outside-amendment', 'patient_id': original['patient_id'], 'encounter_id': 'VISIT-5',
              'available_at': '2025-12-02', 'origin': 'constructed_synthetic', 'source_kind': 'structured_record',
              'recorded_at': '2025-12-01', 'event_date': None, 'record_type': 'order', 'event_link_id': None,
              'content': {'statement': 'Summary explicitly absent in this corrective assertion.',
                          'amendment_authority_confirmed': True, 'amends_fact_id': original['fact_id'],
                          'amendment_scope': 'assertion'}}
    amended = deepcopy(original)
    amended.update(fact_id='outside-amendment-fact', assertion=False, amends_fact_id=original['fact_id'],
                   authority_ref={'source_id': source['source_id'], 'field': 'amendment_authority_confirmed'},
                   evidence=[{'source_id': source['source_id'], 'field': 'statement'}])
    if exclusion == 'patient_mismatch':
        source['patient_id'] = 'ANOTHER-PATIENT'
    elif exclusion == 'not_available_as_of':
        source['available_at'] = '2026-01-01'
    else:
        amended['evidence'][0]['field'] = 'nonexistent'
    raw['sources'].append(source)
    raw['facts'].append(amended)
    packet = evaluate(model(Case, raw))
    assert next(c for c in packet['checks'] if c['requirement'] == 'clinical_summary')['status'] == 'SUPPORTED'
    assert packet['excluded_facts'][0]['reason'] == exclusion
