"""Reuse universal ClinicalFact without promoting clinical context to PA material."""
from copy import deepcopy
import json

import pytest

from clinical_intelligence.careflow.contracts import Case
from clinical_intelligence.careflow.demo import referral_case
from clinical_intelligence.careflow.engine import evaluate
from clinical_intelligence.careflow.report import markdown


def clinical_case(kind, *, patient='CTX-PATIENT', category='symptom'):
    raw = referral_case(patient=patient, request='CTX-REQUEST', request_type=kind)
    text = 'Patient reports persistent pain and difficulty walking.'
    source = {'source_id': 'PUBLIC-DOCUMENT', 'patient_id': patient, 'encounter_id': 'ENC-A',
              'available_at': '2026-10-10', 'origin': 'public_clinical_dataset', 'source_kind': 'clinical_text',
              'recorded_at': None, 'event_date': None, 'record_type': 'note', 'event_link_id': None,
              'content': text, 'original_locator': {'dataset': 'fixture', 'document_id': 'PUBLIC-DOCUMENT'}}
    fact = {'category': category, 'concept': 'pain', 'polarity': 'present', 'temporality': 'current',
            'experiencer': 'patient', 'original_term': text, 'attributes': None,
            'evidence': {'start': 0, 'end': len(text), 'quote': text},
            'supporting_evidence': [], 'provenance': [], 'assertion_basis': 'patient_report',
            'attribution_confidence': 'context_supported', 'clinical_status': 'documented symptom'}
    raw['sources'].append(source)
    raw['clinical_context'] = [{'source_id': source['source_id'],
                                'extraction': {'document_id': source['source_id'], 'facts': [fact], 'relationships': []}}]
    return raw


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('category', ['symptom', 'diagnosis', 'medication', 'treatment', 'laboratory_result', 'other'])
def test_public_clinical_facts_are_preserved_reviewable_and_context_only(kind, category):
    raw = clinical_case(kind, category=category)
    packet = evaluate(Case.model_validate_json(json.dumps(raw)))
    assert packet['readiness'] == 'NEEDS_EVIDENCE'
    context = packet['clinical_context'][0]
    assert context['facts'][0]['category'] == category
    assert context['facts'][0]['evidence'] == raw['clinical_context'][0]['extraction']['facts'][0]['evidence']
    assert context['context_only'] is True
    assert context['facts'][0]['context_fact_id']
    assert packet['execution']['scope'] == 'this_deterministic_evaluation_only'
    assert packet['execution']['upstream_extraction_model_calls'] is None
    assert raw['sources'][-1]['content'] in markdown(packet)
    assert 'Clinical context' in markdown(packet)


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_bad_clinical_quote_or_document_binding_is_rejected_before_ready(kind):
    raw = clinical_case(kind)
    for change in ('quote', 'document_id'):
        wrong = deepcopy(raw)
        if change == 'quote':
            wrong['clinical_context'][0]['extraction']['facts'][0]['evidence']['quote'] = 'invented'
        else:
            wrong['clinical_context'][0]['extraction']['document_id'] = 'another-patient-document'
        with pytest.raises(ValueError):
            Case.model_validate_json(json.dumps(wrong))


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_other_patient_clinical_context_is_not_associated(kind):
    raw = clinical_case(kind)
    raw['sources'][-1]['patient_id'] = 'FOREIGN-PATIENT'
    packet = evaluate(Case.model_validate_json(json.dumps(raw)))
    context = packet['clinical_context'][0]
    assert context['scope_status'] == 'EXCLUDED'
    assert context['exclusion_reason'] == 'patient_mismatch'
    assert packet['readiness'] == 'NEEDS_EVIDENCE'


def test_empty_context_preserves_original_case_and_packet_hashes():
    raw = referral_case()
    before = evaluate(Case.model_validate_json(json.dumps(raw)))
    raw['clinical_context'] = []
    after = evaluate(Case.model_validate_json(json.dumps(raw)))
    assert after == before
    assert 'clinical_context' not in Case.model_validate_json(json.dumps(raw)).model_dump(mode='json')


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_advanced_reviewer_can_cite_clinical_context_fact_ids(tmp_path, kind):
    from clinical_intelligence.careflow.contracts import Review
    from clinical_intelligence.careflow.service import CareFlow
    app = CareFlow(tmp_path / 'db.sqlite')
    before = app.create(Case.model_validate_json(json.dumps(clinical_case(kind))))
    fact_id = before['clinical_context'][0]['facts'][0]['context_fact_id']
    review = Review.model_validate_json(json.dumps({
        'reviewer_id': 'clinical-reviewer', 'reviewer_type': 'advanced_ai', 'model': 'offline-fixture', 'model_version': '1',
        'basis_revision': 1, 'basis_packet_sha256': before['packet_sha256'], 'fact_ids': [fact_id],
        'judgment': 'ESCALATE', 'reason': 'Clinical source is available, but request-specific paperwork is still missing.'}))
    app.review(before['case_id'], review)
    assert app.reviews(before['case_id'])[0]['payload']['fact_ids'] == [fact_id]
    assert app.packet(before['case_id']) == before


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('mutation', ['quote', 'context_fact_id', 'source_sha256'])
def test_packet_verifier_includes_clinical_context(kind, mutation):
    from clinical_intelligence.careflow.evaluation.acceptance import verify_packet
    packet = evaluate(Case.model_validate_json(json.dumps(clinical_case(kind))))
    assert all(verify_packet(packet)['source_checks'])
    context = packet['clinical_context'][0]
    if mutation == 'quote':
        context['facts'][0]['evidence']['quote'] = 'fabricated'
    elif mutation == 'context_fact_id':
        context['facts'][0]['context_fact_id'] = 'another-fact'
    else:
        context['source_sha256'] = 'another-source'
    assert not all(verify_packet(packet)['source_checks'])
