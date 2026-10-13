"""Cross-request persistence, correction authority, and optional AI invariants."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3

import pytest

from clinical_intelligence.careflow.contracts import Case, EvidenceUpdate, Review
from clinical_intelligence.careflow.demo import referral_case, supplemental
from clinical_intelligence.careflow.engine import evaluate
from clinical_intelligence.careflow.service import CareFlow, RevisionConflict
from clinical_intelligence.claims_review.prepare import digest


def model(cls, value):
    return cls.model_validate_json(json.dumps(value))


def find(packet, name='clinical_summary'):
    return next(c for c in packet['checks'] if c['requirement'] == name)


def review_for(packet, *, ai=False, facts=None, judgment='PROPOSE_CORRECTION'):
    return model(Review, {
        'reviewer_id': 'reviewer-1', 'reviewer_type': 'advanced_ai' if ai else 'human',
        'model': 'test-adapter' if ai else None, 'model_version': 'v7' if ai else None,
        'basis_revision': packet['revision'], 'basis_packet_sha256': packet['packet_sha256'],
        'fact_ids': facts if facts is not None else [f['fact_id'] for f in packet['facts']],
        'judgment': judgment, 'reason': 'Supplied new documentation changes a source-backed assertion.',
    })


@pytest.mark.parametrize('kind,patient,request_id', [('referral', 'P-100', 'R-100'), ('prior_authorization', 'P-200', 'PA-200')])
@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('authority,status', [(True, 'SUPPORTED'), (False, 'CONFLICTED'), (None, 'CONFLICTED')])
def test_generalized_correction_authority_and_history(tmp_path, kind, patient, request_id, ai, authority, status):
    raw = referral_case(patient=patient, request=request_id, request_type=kind)
    old = supplemental('clinical_summary', False, f'Original summary absent for {request_id}.', patient=patient, request=request_id)
    raw['sources'] += old['sources']
    raw['facts'] += old['facts']
    app = CareFlow(tmp_path / 'db.sqlite')
    before = app.create(model(Case, raw))
    assert find(before)['status'] == 'NOT_SUPPORTED'
    extra = supplemental('clinical_summary', True, f'Corrected attachment for {request_id}: independent summary provided.',
                         patient=patient, request=request_id, amends=old['facts'][0]['fact_id'], authority=authority)
    after = app.add_evidence(raw['case_id'], model(EvidenceUpdate, {
        'expected_revision': 1, 'review': review_for(before, ai=ai).model_dump(mode='json'), **extra,
    }))
    assert find(after)['status'] == status
    assert app.packet(raw['case_id'], 1) == before
    assert len(after['sources']) == len(before['sources']) + 1
    assert len(after['facts']) == len(before['facts']) + 1
    assert app.audit(raw['case_id'])['verified']
    event = app.audit(raw['case_id'])['events'][-1]
    assert event['event_type'] == 'FACT_CORRECTED'
    assert event['payload']['reviewer']['reviewer_type'] == ('advanced_ai' if ai else 'human')
    assert event['payload']['reevaluated_rule_ids'] == [c['rule_id'] for c in after['checks']]


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_reused_or_nonexistent_evidence_never_fills_gap(tmp_path, kind):
    app = CareFlow(tmp_path / 'db.sqlite')
    packet = app.create(model(Case, referral_case(request_type=kind)))
    raw = supplemental('clinical_summary', True, 'New assertion reusing an old document.')
    raw['facts'][0]['evidence'] = [packet['facts'][0]['evidence'][0]]
    update = model(EvidenceUpdate, {'expected_revision': 1, 'review': review_for(packet).model_dump(mode='json'), **raw})
    with pytest.raises(ValueError, match='new source evidence'):
        app.add_evidence(packet['case_id'], update)
    assert app.packet(packet['case_id']) == packet
    assert app.audit(packet['case_id'])['revision_count'] == 1
    assert not app.reviews(packet['case_id'])
    raw['facts'][0]['evidence'] = [{'source_id': 'nonexistent', 'span_id': 'nonexistent:L001'}]
    with pytest.raises(ValueError, match='unknown source'):
        model(Case, {**referral_case(), 'sources': raw['sources'], 'facts': raw['facts']})


@pytest.mark.parametrize('ai', [False, True])
def test_review_cannot_override_rules_and_cannot_invent_basis(tmp_path, ai):
    app = CareFlow(tmp_path / 'db.sqlite')
    before = app.create(model(Case, referral_case()))
    review = review_for(before, ai=ai, judgment='AGREE')
    app.review(before['case_id'], review)
    assert app.packet(before['case_id']) == before
    for change in [{'fact_ids': ['invented-fact']}, {'basis_packet_sha256': 'wrong-hash'}]:
        with pytest.raises(ValueError):
            app.review(before['case_id'], model(Review, {**review.model_dump(mode='json'), **change}))
    with pytest.raises(ValueError):
        model(Review, {**review.model_dump(mode='json'), 'readiness': 'DOCUMENTATION_READY'})
    assert len(app.reviews(before['case_id'])) == 1


def test_optimistic_concurrent_updates_and_reopen(tmp_path):
    path = tmp_path / 'db.sqlite'
    app = CareFlow(path)
    before = app.create(model(Case, referral_case()))
    update = model(EvidenceUpdate, {'expected_revision': 1, 'review': review_for(before).model_dump(mode='json'),
                                  **supplemental('clinical_summary', True, 'Summary newly received.')})
    def attempt():
        try:
            return app.add_evidence(before['case_id'], update)['revision']
        except RevisionConflict:
            return 'STALE'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results, key=str) == [2, 'STALE']
    reopened = CareFlow(path)
    assert reopened.packet(before['case_id'])['revision'] == 2
    assert len(reopened.reviews(before['case_id'])) == 1
    assert reopened.audit(before['case_id'])['verified']


def test_db_is_append_only_and_transaction_failure_rolls_back(tmp_path, monkeypatch):
    app = CareFlow(tmp_path / 'db.sqlite')
    before = app.create(model(Case, referral_case()))
    update = model(EvidenceUpdate, {'expected_revision': 1, 'review': review_for(before).model_dump(mode='json'),
                                  **supplemental('clinical_summary', True, 'Summary newly received.')})
    def failure(*args, **kwargs):
        raise RuntimeError('Injected storage error after revision insert')
    monkeypatch.setattr(app.store, 'append_event', failure)
    with pytest.raises(RuntimeError):
        app.add_evidence(before['case_id'], update)
    assert app.packet(before['case_id']) == before
    assert app.audit(before['case_id'])['verified']
    with app.store.connect() as conn:
        for query in ['DELETE FROM revisions', 'UPDATE revisions SET revision=99', 'DELETE FROM events',
                      "UPDATE events SET event_sha256='altered'"]:
            with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                conn.execute(query)


def test_audit_detects_tampered_snapshot_even_after_packet_hash_recomputed(tmp_path):
    app = CareFlow(tmp_path / 'db.sqlite')
    before = app.create(model(Case, referral_case()))
    altered = deepcopy(before)
    altered['readiness'] = 'DOCUMENTATION_READY'
    altered['packet_sha256'] = digest({k: v for k, v in altered.items() if k != 'packet_sha256'})
    with app.store.connect() as conn:
        conn.execute('DROP TRIGGER revisions_no_update')
        conn.execute('UPDATE revisions SET packet_json=?', (json.dumps(altered),))
    audit = app.audit(before['case_id'])
    assert not audit['verified'] and audit['errors']


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_optional_risk_review_reserves_failures_and_skips_routine_cases(tmp_path, kind):
    app = CareFlow(tmp_path / 'db.sqlite')
    raw = referral_case(request_type=kind)
    before = app.create(model(Case, raw))
    def forbidden(_):
        raise AssertionError('Low-risk requests must not call AI')
    assert app.risk_review(before['case_id'], forbidden, reviewer_id='reviewer-1', model='test-adapter', model_version='v7')['status'] == 'SKIPPED_LOW_RISK'
    extra = supplemental('clinical_summary', False, 'Summary explicitly unavailable.')
    high = app.add_evidence(before['case_id'], model(EvidenceUpdate, {
        'expected_revision': 1, 'review': review_for(before).model_dump(mode='json'), **extra}))
    def provider_failure(_):
        raise RuntimeError('Synthetic adapter failure, no network call')
    with pytest.raises(RuntimeError):
        app.risk_review(before['case_id'], provider_failure, reviewer_id='reviewer-1', model='test-adapter', model_version='v7')
    assert app.model_calls(before['case_id']) == {'research_model_calls': 0, 'product_model_calls': 1,
                                                'failed_product_reviews': 1, 'incomplete_product_reviews': 0}
    result = app.risk_review(before['case_id'], lambda p: review_for(p, ai=True),
                             reviewer_id='reviewer-1', model='test-adapter', model_version='v7')
    assert result['status'] == 'REVIEW_RECORDED'
    assert app.packet(before['case_id']) == high
    assert app.model_calls(before['case_id'])['product_model_calls'] == 2


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('record_type,expected', [('order', 'SUPPORTED'), ('observation', 'INSUFFICIENT_EVIDENCE'),
                                               ('procedure', 'INSUFFICIENT_EVIDENCE')])
def test_future_order_intent_is_distinct_from_future_actual_event(kind, record_type, expected):
    raw = referral_case(request_type=kind)
    extra = supplemental('clinical_summary', True, 'Document declared for a future service.', structured=True)
    extra['sources'][0].update(event_date='2026-11-01', record_type=record_type)
    raw['sources'] += extra['sources']
    raw['facts'] += extra['facts']
    assert find(evaluate(model(Case, raw)))['status'] == expected


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
@pytest.mark.parametrize('structured', [False, True])
def test_invalid_locator_retains_failure_and_does_not_fill_gap(kind, structured):
    raw = referral_case(request_type=kind)
    extra = supplemental('clinical_summary', True, 'Grounding check original text.', structured=structured)
    extra['facts'][0]['evidence'][0]['field' if structured else 'span_id'] = 'invalid'
    raw['sources'] += extra['sources']
    raw['facts'] += extra['facts']
    packet = evaluate(model(Case, raw))
    assert find(packet)['status'] == 'INSUFFICIENT_EVIDENCE'
    assert packet['excluded_facts'][0]['grounding_errors']
    assert packet['review_route']['recommended']


def test_unknown_ruleset_does_not_fallback_and_ai_model_metadata_required():
    raw = referral_case()
    raw['request']['ruleset_version'] = 'unknown-version'
    with pytest.raises(ValueError, match='Unsupported ruleset'):
        evaluate(model(Case, raw))
    before = evaluate(model(Case, referral_case()))
    review = review_for(before, ai=True).model_dump(mode='json')
    review['model_version'] = None
    with pytest.raises(ValueError, match='model and version'):
        model(Review, review)
