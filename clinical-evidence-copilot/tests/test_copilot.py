"""Product acceptance: safety properties and workflow, not clinical accuracy."""
import copy
import json
from pathlib import Path

import pytest

from clinical_intelligence.copilot import build_packet, render_markdown
from clinical_intelligence.copilot.models import Source, ReviewRequest, Reviewer
from clinical_intelligence.copilot.store import CaseStore, VersionConflict
from clinical_intelligence.copilot.service import review_packet, compare_packets


def source(text='[patient] I have cough.\n[doctor] We plan a chest X-ray.', **kwargs):
    return Source.create(document_id='visit-1', text=text, input_kind='dialogue', **kwargs)


def fact(doc, quote, **kwargs):
    start = doc.text.index(quote)
    return dict(category='symptom', concept='cough', original_term=quote,
                polarity='present', temporality='current', experiencer='patient',
                attributes=None, assertion_basis='patient_report',
                attribution_confidence='context_supported', clinical_status=None,
                evidence=dict(quote=quote, start=start, end=start+len(quote)), **kwargs)


def packet():
    doc = source()
    f = fact(doc, 'I have cough.')
    plan = fact(doc, 'We plan a chest X-ray.')
    plan.update(category='procedure', concept='chest X-ray', temporality='planned',
                assertion_basis='clinician_assessment', clinical_status='planned')
    return build_packet('case-1', 'patient-1', doc, {'document_id': doc.document_id, 'facts': [f, plan]})


def request(p, action='accept', reviewer_type='human', replacement=None):
    return ReviewRequest(base_version=p.version, fact_id=p.facts[0].fact_id, action=action,
        reason='Checked the cited source and clinical context.',
        evidence_ids=p.facts[0].evidence_ids,
        reviewer=Reviewer(reviewer_id='reviewer-1', reviewer_type=reviewer_type, version='v1'),
        replacement=replacement)


def test_soap_keeps_plan_and_report_and_exact_backtrace():
    p = packet()
    assert p.soap['S'][0].fact_ids == [p.facts[0].fact_id]
    assert 'patient_report' in p.soap['S'][0].text
    assert 'planned' in p.soap['P'][0].text
    assert p.facts[1].action_status == 'planned'
    for e in p.evidence:
        assert p.source.text[e.start:e.end] == e.quote
        assert e.turn_id and e.document_id == p.source.document_id
    assert p.review_required_fact_ids == []
    assert 'Not documented' in render_markdown(p)


def test_invalid_evidence_is_quarantined_not_added_to_soap():
    doc = source()
    f = fact(doc, 'I have cough.')
    f['evidence']['quote'] = 'I have pneumonia.'
    p = build_packet('bad', 'patient-1', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert not p.facts and not any(p.soap.values())
    assert p.extraction_status == 'invalid' and p.rejected_facts


def test_family_subject_is_never_presented_as_patient():
    doc = source('[patient] My father has asthma.')
    f = fact(doc, 'My father has asthma.')
    f.update(concept='asthma', experiencer='family')
    p = build_packet('family', 'patient-1', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert 'family' in p.soap['S'][0].text
    f['experiencer'] = 'patient'
    wrong = build_packet('wrong', 'patient-1', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert 'subject_mismatch' in {i.code for i in wrong.issues}


def test_time_and_unperformed_action_are_flagged():
    doc = source('[doctor] We plan a chest X-ray tomorrow.')
    f = fact(doc, 'We plan a chest X-ray tomorrow.')
    f.update(category='procedure', concept='chest X-ray', temporality='current',
             assertion_basis='clinician_assessment', clinical_status='completed')
    p = build_packet('wrong-time', 'patient-1', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert {'prospective_action_mismatch'} <= {i.code for i in p.issues}
    assert p.review_required_fact_ids
    assert p.facts[0].action_status != 'completed'


def test_conflict_keeps_both_facts():
    doc = source('[patient] I have cough.\n[patient] I do not have cough.')
    f = fact(doc, 'I have cough.')
    other = fact(doc, 'I do not have cough.')
    other['polarity'] = 'absent'
    p = build_packet('conflict', 'patient-1', doc, {'document_id': doc.document_id, 'facts': [f, other]})
    assert len(p.facts) == 2
    assert len(p.conflicts) == 1 and len(p.review_required_fact_ids) == 2


def test_review_and_correction_preserve_source_and_original(tmp_path):
    p = packet()
    store = CaseStore(tmp_path / 'cases.sqlite3')
    store.save(p, expected_version=0)
    original = copy.deepcopy(p.facts[0].original_fact)
    replacement = copy.deepcopy(original)
    replacement['polarity'] = 'uncertain'
    replacement['clinical_status'] = 'requires clarification'
    changed = review_packet(p, request(p, 'correct', replacement=replacement))
    store.save(changed, expected_version=1)
    assert changed.source == p.source
    assert changed.facts[0].original_fact == original
    assert store.get(p.case_id, 1).facts[0].assertion.polarity == 'present'
    assert store.get(p.case_id).facts[0].assertion.polarity == 'uncertain'
    assert changed.reviews[0].before == original
    assert changed.reviews[0].after == replacement
    assert changed.version == 2 and changed.parent_hash == p.content_hash


def test_stale_review_and_save_fail(tmp_path):
    p = packet()
    store = CaseStore(tmp_path / 'cases.sqlite3')
    store.save(p, expected_version=0)
    newer = review_packet(p, request(p))
    store.save(newer, expected_version=1)
    with pytest.raises(VersionConflict):
        store.save(review_packet(p, request(p)), expected_version=1)
    with pytest.raises(ValueError, match='version'):
        review_packet(newer, request(p))


def test_ai_advice_can_be_overridden_by_human():
    p = packet()
    suggested = review_packet(p, request(p, 'escalate', 'ai'))
    assert suggested.facts[0].review_status == 'escalated'
    accepted = review_packet(suggested, request(suggested))
    assert accepted.facts[0].review_status == 'accepted'
    assert [r.reviewer.reviewer_type for r in accepted.reviews] == ['ai', 'human']
    assert accepted.semantic_validation == 'not_clinically_validated'


def test_review_requires_existing_evidence_and_reason():
    p = packet()
    r = request(p)
    r.evidence_ids = ['invented']
    with pytest.raises(ValueError, match='evidence'):
        review_packet(p, r)
    r = request(p)
    r.reason = ' '
    with pytest.raises(ValueError, match='reason'):
        review_packet(p, r)


def test_correction_cannot_invent_citation():
    p = packet()
    replacement = copy.deepcopy(p.facts[0].original_fact)
    replacement['evidence']['quote'] = 'invented'
    with pytest.raises(ValueError, match='evidence'):
        review_packet(p, request(p, 'correct', replacement=replacement))


def test_longitudinal_same_patient_only_and_missing_is_not_resolution():
    p = packet()
    doc = source('[patient] I feel better.', encounter_time='2026-10-14')
    next_visit = build_packet('case-2', 'patient-1', doc, {'document_id': doc.document_id, 'facts': []})
    diff = compare_packets(p, next_visit)
    assert diff['changes'][0]['change'] == 'not_documented_in_later'
    assert diff['changes'][0]['before_fact_ids']
    other = next_visit.model_copy(update={'patient_id': 'another-patient'}).seal()
    with pytest.raises(ValueError, match='patient'):
        compare_packets(p, other)


def test_model_failure_preserves_source_without_fabricating_soap():
    doc = source()
    p = build_packet('failure', 'patient-1', doc, None, extraction_error='upstream 502')
    assert p.source == doc and not p.facts
    assert p.extraction_status == 'failed'
    assert not any(p.soap.values()) and p.issues[0].code == 'extraction_failure'


def test_packet_json_and_readable_view_share_ids_and_hash():
    p = packet()
    payload = json.loads(p.model_dump_json())
    readable = render_markdown(p)
    assert payload['schema_version'] == 'clinical-evidence-copilot/v1'
    assert payload['content_hash'] in readable
    assert all(f['fact_id'] in readable for f in payload['facts'])


@pytest.mark.parametrize('kind', ['dialogue', 'note'])
@pytest.mark.parametrize('quote,category,basis,polarity,time,status,expected_section,action', [
    ('I report nausea today.', 'symptom', 'patient_report', 'present', 'current', None, 'S', 'unknown'),
    ('Patient denies headache.', 'symptom', 'patient_report', 'absent', 'current', None, 'S', 'unknown'),
    ('Exam shows ankle swelling.', 'observation', 'clinician_observation', 'present', 'current', None, 'O', 'unknown'),
    ('Possible tendon injury.', 'diagnosis', 'clinician_assessment', 'uncertain', 'current', 'possible', 'A', 'unknown'),
    ('Physical therapy is scheduled.', 'treatment', 'clinician_assessment', 'present', 'planned', 'scheduled', 'P', 'planned'),
    ('Vaccination was administered last year.', 'procedure', 'documented_history', 'present', 'historical', 'administered', 'S', 'completed'),
    ('Medication was discussed but not started.', 'medication', 'discussion', 'present', 'current', 'not started', 'S', 'not_completed'),
    ('Patient is taking the medication.', 'medication', 'patient_report', 'present', 'current', 'taking', 'S', 'ongoing'),
])
def test_cross_source_semantic_preservation(kind, quote, category, basis, polarity, time, status, expected_section, action):
    text = '[clinician] ' + quote if kind == 'dialogue' else 'Clinical note\n' + quote
    doc = Source.create('diverse-'+kind, text, kind)
    f = fact(doc, quote)
    # This low-level routing control must name the entity actually in its source.
    # The old helper silently supplied cough for every unrelated source.
    entity = {
        'I report nausea today.': 'nausea',
        'Patient denies headache.': 'headache',
        'Exam shows ankle swelling.': 'ankle swelling',
        'Possible tendon injury.': 'tendon injury',
        'Physical therapy is scheduled.': 'physical therapy',
        'Vaccination was administered last year.': 'vaccination',
        'Medication was discussed but not started.': 'medication',
        'Patient is taking the medication.': 'medication',
    }[quote]
    f.update(concept=entity, category=category, assertion_basis=basis,
             polarity=polarity, temporality=time, clinical_status=status)
    # The compound discussion/not-started source needs current proposal-preserving
    # projection; legacy v4 selects the first lexical scope and changes the fact.
    compound = status == 'not started'
    extraction = {'document_id': doc.document_id, 'facts': [f]}
    if compound:
        extraction['clinical_semantics'] = [{'fact_index':0, 'semantics':{
            'frequency':None, 'event_time':None, 'duration':None,
            'action_state':'not_completed', 'completion_scope':None,
            'assertion_basis':'discussion', 'action_type':'administration_event'}}]
    p = build_packet('diverse-case', 'diverse-patient', doc, extraction,
                     projection_version='soap/v6' if compound else 'soap/v4')
    assert p.soap[expected_section][0].fact_ids == [p.facts[0].fact_id]
    if compound:
        # The explicit proposal survives. Its elided second clause is outside
        # grammar/4's independently confirmed event scope, so only that proof
        # remains unknown; a discussion must not overwrite the proposed state.
        proof = p.extraction_metadata['evidence_verification']['assertions'][0]
        assert proof['proposed_claim']['action_state'] == action
        assert p.facts[0].assertion.clinical_status == 'not started'
        assert p.facts[0].action_status == 'unknown'
        assert 'not started' in p.soap[expected_section][0].text
    else:
        assert p.facts[0].action_status == action
    assert p.facts[0].assertion.polarity == polarity
    assert p.facts[0].assertion.temporality == time
    assert p.facts[0].assertion.assertion_basis == basis
    assert bool(p.review_required_fact_ids) == (polarity == 'uncertain' or compound)


@pytest.mark.parametrize('kind', ['dialogue', 'note'])
@pytest.mark.parametrize('quote,concept', [
    ('My mother had diabetes.', 'diabetes'),
    ('Her brother has epilepsy.', 'epilepsy'),
    ("The patient's father has hypertension.", 'hypertension'),
])
def test_subject_discrepancy_controls_across_expressions(kind, quote, concept):
    doc = Source.create('subject-'+kind, ('[patient] ' if kind == 'dialogue' else '')+quote, kind)
    f = fact(doc, quote)
    f.update(concept=concept, experiencer='patient')
    wrong = build_packet('wrong', 'p', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert 'subject_mismatch' in {i.code for i in wrong.issues}
    f['experiencer'] = 'family'
    correct = build_packet('correct', 'p', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert not correct.review_required_fact_ids
    assert correct.facts[0].assertion.experiencer == 'family'


@pytest.mark.parametrize('kind', ['dialogue', 'note'])
@pytest.mark.parametrize('quote', ['We plan imaging tomorrow.', 'We will start rehabilitation.', 'Surgery is scheduled for next month.'])
def test_future_action_discrepancy_controls_across_expressions(kind, quote):
    doc = Source.create('time-'+kind, ('[doctor] ' if kind == 'dialogue' else '')+quote, kind)
    f = fact(doc, quote)
    entity = {'We plan imaging tomorrow.':'imaging',
              'We will start rehabilitation.':'rehabilitation',
              'Surgery is scheduled for next month.':'surgery'}[quote]
    f.update(concept=entity, category='treatment', temporality='current', clinical_status='completed')
    wrong = build_packet('wrong', 'p', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert wrong.facts[0].action_status == 'planned' and wrong.review_required_fact_ids
    f.update(temporality='planned', clinical_status='planned')
    correct = build_packet('correct', 'p', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert not correct.review_required_fact_ids and correct.soap['P']


@pytest.mark.parametrize('kind', ['dialogue', 'note'])
def test_unicode_offsets_and_fake_provenance(kind):
    quote = '恶心 — café 🙂.'
    doc = Source.create('unicode', ('[patient] ' if kind == 'dialogue' else '')+quote, kind)
    f = fact(doc, quote)
    p = build_packet('unicode', 'p', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert p.evidence[0].quote == quote
    wrong = copy.deepcopy(p.facts[0].assertion.model_dump())
    wrong['provenance'][0]['document_id'] = 'wrong-document'
    bad = build_packet('bad', 'p', doc, {'document_id': doc.document_id, 'facts': [wrong]})
    assert bad.rejected_facts and not bad.facts


def test_original_proposal_is_preserved_even_after_repeated_corrections(tmp_path):
    p = packet()
    store = CaseStore(tmp_path/'cases.sqlite3')
    store.save(p, expected_version=0)
    original = copy.deepcopy(p.facts[0].original_fact)
    for time in ['historical', 'unknown', 'current']:
        replacement = p.facts[0].assertion.model_dump()
        replacement['temporality'] = time
        p = review_packet(p, request(p, 'correct', replacement=replacement))
        store.save(p, expected_version=p.version-1)
        assert p.facts[0].original_fact == original
    assert len(store.history(p.case_id)) == 4


def test_store_rejects_source_overwrite_and_tampered_packet(tmp_path):
    p = packet()
    store = CaseStore(tmp_path/'cases.sqlite3')
    store.save(p, expected_version=0)
    changed = review_packet(p, request(p))
    changed.source = source('[patient] Different source.')
    changed.seal()
    with pytest.raises(ValueError, match='Source|consistency'):
        store.save(changed, expected_version=1)
    p.facts[0].assertion.polarity = 'absent'
    with pytest.raises(ValueError, match='integrity'):
        p.verify()


@pytest.mark.parametrize('kind', ['dialogue', 'note'])
@pytest.mark.parametrize('concept,quote', [('cough', 'Cough has resolved.'), ('headache', 'The headache is resolved.')])
def test_resolved_current_absence_is_not_a_time_mismatch(kind, concept, quote):
    doc = Source.create('resolved-'+kind, ('[patient] ' if kind == 'dialogue' else '')+quote, kind)
    f = fact(doc, quote)
    f.update(concept=concept, polarity='absent', clinical_status='resolved per patient')
    p = build_packet('resolved', 'p', doc, {'document_id': doc.document_id, 'facts': [f]})
    assert not p.review_required_fact_ids


@pytest.mark.parametrize('corrupt', ['soap', 'evidence', 'assertion'])
def test_resealed_inconsistent_packet_is_rejected(corrupt):
    p = packet()
    if corrupt == 'soap':
        p.soap['S'][0].text = 'Invented clinical assertion'
    elif corrupt == 'evidence':
        p.evidence[0].quote = 'Invented source'
    else:
        p.facts[0].evidence_ids = ['not-an-evidence-id']
    p.seal()
    with pytest.raises(ValueError, match='consistency'):
        p.verify()


def test_correction_does_not_auto_clear_remaining_discrepancy():
    p = packet()
    replacement = copy.deepcopy(p.facts[0].original_fact)
    replacement.update(temporality='unknown')
    changed = review_packet(p, request(p, 'correct', replacement=replacement))
    assert changed.facts[0].fact_id in changed.review_required_fact_ids


def test_unlogged_resealed_fact_change_cannot_be_saved(tmp_path):
    from clinical_intelligence.copilot.service import project
    p = packet()
    store = CaseStore(tmp_path/'cases.sqlite3')
    store.save(p, expected_version=0)
    changed = review_packet(p, request(p))
    changed.facts[1].assertion.polarity = 'absent'
    project(changed)
    with pytest.raises(ValueError, match='review'):
        store.save(changed, expected_version=1)
