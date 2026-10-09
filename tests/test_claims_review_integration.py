"""Behavioral offline tests; injected proposals never count as model measurements."""
import copy
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch
import pytest
from clinical_intelligence.claims_review import cli
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.note_extractor import (
    BudgetLedger, RuntimeValidationError, extract_note, note_request, validate_proposal)
from clinical_intelligence.claims_review.prepare import prepare_case
from clinical_intelligence.claims_review.review import add_months, load_policy, markdown, run_review
from verify_claims_review_synthea import verify

ROOT = Path(__file__).resolve().parents[1]


def case(number):
    return CaseInput.model_validate_json((ROOT / f'examples/claims_review/development/DEV-{number:03d}.json').read_text(encoding='utf-8'))


def changed(c, mutate):
    body = c.model_dump(mode='json')
    mutate(body)
    return CaseInput.model_validate_json(json.dumps(body))


def source(c):
    return next(s for s in prepare_case(c, load_policy(), input_label='fixture')['source_candidates'] if s['source_kind'] == 'synthetic_note')


def assertion(s, kind, value, **updates):
    result = dict(kind=kind, statement=s['line_anchors'][1]['quote'], value=value,
                  fact_date=None, date_role='unknown', temporal_status='actual',
                  target_date=None, test_specific=None, provider=None, reporter=None,
                  authenticated=None, span_ids=[s['line_anchors'][1]['span_id']])
    result.update(updates)
    return result


def proposal(c):
    s = source(c)
    facts = []
    if c.case_id in {'DEV-001', 'DEV-002'}:
        facts.append(assertion(s, 'diabetes_context', True))
    if c.case_id == 'DEV-002':
        context = dict(target_date='2026-09-22', test_specific=True,
                       provider='Dr. Simulated Provider', authenticated=True,
                       span_ids=[a['span_id'] for a in s['line_anchors'][1:]])
        facts.extend([
            assertion(s, 'purpose', 'monitoring', **context),
            assertion(s, 'regimen_change', True, fact_date='2026-08-10', date_role='adjustment_start', reporter='patient'),
            assertion(s, 'clinical_rationale', 'implemented_change', **context),
            assertion(s, 'order_intent', True, temporal_status='planned', **context)])
    if c.case_id == 'DEV-003':
        facts.extend([assertion(s, 'purpose', None, target_date='2026-09-25', test_specific=True),
                      assertion(s, 'order_intent', None, target_date='2026-09-25', test_specific=True)])
    if c.case_id == 'DEV-005':
        facts.extend([assertion(s, 'purpose', 'screening', test_specific=True),
                      assertion(s, 'diabetes_context', None)])
    return dict(patient_id=s['patient_id'], source_id=s['source_id'], facts=facts)


class FixtureProvider:
    def __init__(self, *answers):
        self.answers = iter(answers)
        self.requests = []

    def structured_output(self, prompt, schema, *, purpose):
        self.requests.append((prompt, schema, purpose))
        answer = next(self.answers)
        if isinstance(answer, Exception):
            raise answer
        return copy.deepcopy(answer)


def statuses(r):
    return {x.criterion_id: x.status for x in r.criteria}


@pytest.mark.parametrize('number', range(1, 6))
def test_five_fixture_reviews_against_development_constraints(number):
    c = case(number)
    p = FixtureProvider(proposal(c))
    r = run_review(c, mode='fixture', provider=p)
    expected = json.loads((ROOT / 'tests/fixtures/claims_review/development_expected.json').read_text(encoding='utf-8'))['cases'][number-1]
    assert r.status == expected['overall_expectation']['status']
    for item in expected['criterion_expectations']:
        assert statuses(r)[item['criterion_id']] == item['status']
    assert len(p.requests) == 1
    assert r.execution['actual_provider_calls'] == 0
    assert not r.execution['execution_failed']
    for criterion in r.criteria:
        if criterion.evidence_complete:
            assert criterion.clinical_refs and criterion.policy_refs
    for f in r.facts:
        assert f.patient_id == c.claim.patient_id
        for citation in f.citations:
            original = next(s for s in c.sources if s.source_id == citation.source_id)
            assert original.patient_id == citation.patient_id == c.claim.patient_id
            if citation.quote is not None:
                assert original.content[citation.start:citation.end] == citation.quote
    assert 'APPROVED' not in markdown(r) and 'DENIED' not in markdown(r)
    from evaluate_claims_review import evaluate
    assert evaluate(c, r, expected)['passed']


@pytest.mark.parametrize(('prior', 'expected'), [('2026-01-31', '2026-04-30'), ('2025-11-30', '2026-02-28'), ('2023-11-30', '2024-02-29')])
def test_calendar_month_end(prior, expected):
    assert add_months(date.fromisoformat(prior), 3).isoformat() == expected


def test_equal_calendar_boundary_is_not_short():
    c = changed(case(1), lambda b: [s.update(event_date='2026-06-15') for s in b['sources'] if s['event_link_id'] == 'SYN-D1-HBA1C-PREV'])
    assert statuses(run_review(c))['SHORT_INTERVAL_RATIONALE'] == 'NOT_APPLICABLE'


def test_short_trigger_survives_incomplete_history_and_plan_is_not_implementation():
    c = changed(case(2), lambda b: b['review_context'].update(history_completeness='not_asserted'))
    r = run_review(c)
    assert statuses(r)['TEST_TIMELINE'] == 'INSUFFICIENT_EVIDENCE'
    criterion = next(x for x in r.criteria if x.criterion_id == 'SHORT_INTERVAL_RATIONALE')
    assert criterion.status == 'INSUFFICIENT_EVIDENCE' and criterion.derivation['trigger'] is True
    assert next(f for f in r.facts if f.kind == 'regimen_change').value is None


def test_window_excluded_linked_member_retains_conflict_but_late_member_cannot():
    c = changed(case(4), lambda b: b['review_context'].update(history_start='2026-07-01'))
    r = run_review(c)
    prior = next(e for e in r.timeline if e['event_key'] == 'SYN-D4-ACCESSION-001')
    assert prior['dates'] == ['2026-05-20', '2026-08-20'] and prior['conflicted']
    assert statuses(r)['SHORT_INTERVAL_RATIONALE'] == 'CONFLICTED'
    c = changed(c, lambda b: b['sources'][1].update(available_at='2026-10-09'))
    assert next(e for e in run_review(c).timeline if e['event_key'] == 'SYN-D4-ACCESSION-001')['dates'] == ['2026-08-20']


def test_unknown_availability_is_unresolved_not_late_and_cannot_support():
    c = changed(case(1), lambda b: b['sources'][3].update(available_at=None))
    r = run_review(c)
    assert r.preparation['unresolved_source_metadata']
    assert not any(f.source_id == 'DEV-001-S004' for f in r.facts)
    assert statuses(r)['ORDER_INTENT'] == 'INSUFFICIENT_EVIDENCE'


def test_null_missing_date_retains_score_and_zero_is_not_null():
    r = run_review(case(3))
    historical = next(f for f in r.facts if f.source_id == 'DEV-003-S003' and f.kind == 'test_event')
    assert historical.value == 6.9 and historical.fact_date is None
    c = changed(case(3), lambda b: b['sources'][1]['content'].update(value=0))
    assert next(f for f in run_review(c).facts if f.source_id == 'DEV-003-S002' and f.kind == 'test_event').value == 0


def test_same_text_separate_source_identity_and_wrong_patient_exclusion():
    c = case(2)
    def duplicate(b):
        note = copy.deepcopy(b['sources'][3]);note['source_id'] = 'INDEPENDENT';b['sources'].append(note)
        other = copy.deepcopy(note);other.update(source_id='OTHER', patient_id='OTHER-PATIENT');b['sources'].append(other)
    c = changed(c, duplicate)
    from clinical_intelligence.claims_review.facts import source_key
    prepared = prepare_case(c, load_policy(), input_label='test')
    notes = [s for s in prepared['source_candidates'] if s['source_kind'] == 'synthetic_note']
    assert len(notes) == 2 and source_key(notes[0]) != source_key(notes[1])


def test_required_fields_are_nullable_and_strict():
    s = source(case(2));_, schema = note_request(s, {})
    fields = schema['$defs']['NoteAssertion']
    assert 'authenticated' in fields['required']
    assert {'type': 'null'} in fields['properties']['authenticated']['anyOf']
    raw = proposal(case(2));raw['facts'][0]['value'] = 1
    with pytest.raises(RuntimeValidationError, match='boolean or null'):
        validate_proposal(raw, s, date(2026, 10, 8))


def test_repair_collects_binding_and_schema_errors_then_salvages_valid_facts():
    c = case(2);s = source(c);bad = proposal(c)
    bad['source_id'] = 'WRONG';bad['facts'][0]['value'] = {};bad['facts'][0]['span_ids'] = ['UNKNOWN']
    final = proposal(c);final['facts'][-1]['provider'] = 'Fabricated signer'
    p = FixtureProvider(bad, final)
    facts, record = extract_note(p, s, c.claim.model_dump(mode='json'), c.review_context.as_of)
    assert record['status'] == 'failed' and record['repairs'] == 1 and len(p.requests) == 2
    assert 'unknown span ID' in p.requests[1][0] and 'source_id must match' in p.requests[1][0]
    assert any(f.kind == 'regimen_change' for f in facts) and not any(f.kind == 'order_intent' for f in facts)


def test_provider_failure_preserves_structured_facts_and_no_retries():
    p = FixtureProvider(TimeoutError('test timeout'))
    r = run_review(case(1), mode='fixture', provider=p)
    assert r.execution['execution_failed'] and len(p.requests) == 1
    assert statuses(r)['ORDER_INTENT'] == 'SUPPORTED' and r.status == 'NEEDS_HUMAN_REVIEW'
    assert any(f.kind == 'test_event' for f in r.facts)


def test_missing_paperwork_cannot_be_negative_intent():
    c = case(3);s = source(c);raw = proposal(c);raw['facts'][-1]['value'] = False
    with pytest.raises(RuntimeValidationError, match='not affirmative'):
        validate_proposal(raw, s, c.review_context.as_of)


def test_unrelated_or_negative_signature_and_uncited_date_cannot_be_support():
    c = case(2);s = source(c);raw = proposal(c)
    raw['facts'][-1]['span_ids'] = [s['line_anchors'][1]['span_id']]
    raw['facts'][-1]['target_date'] = '2026-09-23'
    with pytest.raises(RuntimeValidationError) as error:
        validate_proposal(raw, s, c.review_context.as_of)
    assert 'signature context' in str(error.value) and 'explicit date' in str(error.value)


def test_unicode_repeated_lines_have_distinct_exact_offsets():
    c = changed(case(2), lambda b: b['sources'][3].update(content='\u03b1 HbA1c\n\u03b1 HbA1c\nUnsigned'))
    s = source(c)
    raw = dict(patient_id=s['patient_id'], source_id=s['source_id'], facts=[assertion(s, 'test_mention', None)])
    p = validate_proposal(raw, s, c.review_context.as_of)
    from clinical_intelligence.claims_review.note_extractor import adapt
    citation = adapt(p, s)[0].citations[0]
    assert citation.start == 8 and s['content'][citation.start:citation.end] == '\u03b1 HbA1c'


def test_unknown_target_no_metadata_date_borrowing_and_scope_guard():
    c = changed(case(1), lambda b: b['claim'].update(service_date=None))
    r = run_review(c)
    assert r.target.service_date is None and statuses(r)['TEST_TIMELINE'] == 'INSUFFICIENT_EVIDENCE'
    r = run_review(case(1), requested_policy='unmapped-historical-version')
    assert r.status == 'UNSUPPORTED_SCOPE' and set(statuses(r).values()) == {'NOT_EVALUATED'}


def test_runtime_does_not_read_expected_and_offline_cli_never_creates_provider(tmp_path):
    original = Path.read_text
    def protected(path, *args, **kwargs):
        assert 'expected' not in path.name
        return original(path, *args, **kwargs)
    output = tmp_path / 'review.json'
    with patch.object(cli, 'live_provider', side_effect=AssertionError('offline provider constructed')), patch.object(Path, 'read_text', protected):
        assert cli.main(['run', '--case', str(ROOT / 'examples/claims_review/development/DEV-001.json'), '--output', str(output)]) == 0
        assert cli.main(['render', '--packet', str(output), '--output', str(tmp_path / 'review.md')]) == 0
        assert cli.main(['prepare', '--case', str(ROOT / 'examples/claims_review/development/DEV-001.json'), '--output', str(tmp_path / 'prepared.json')]) == 0
    assert json.loads(output.read_text(encoding='utf-8'))['execution']['note_extraction'] == 'not_run'


def test_invalid_input_replaces_old_success_and_returns_failure(tmp_path):
    input_path = tmp_path / 'bad.json';input_path.write_text('{}', encoding='utf-8')
    output = tmp_path / 'old.json';output.write_text('{"status":"old success"}', encoding='utf-8')
    assert cli.main(['run', '--case', str(input_path), '--output', str(output)]) == 1
    assert json.loads(output.read_text(encoding='utf-8'))['stage'] == 'input'


def test_budget_reserves_before_inference_and_survives_restart(tmp_path):
    path = tmp_path / 'ledger.json'
    ledger = BudgetLedger(path)
    for i in range(20):
        assert BudgetLedger(path).consume({'attempt': i}) == i+1
    with pytest.raises(RuntimeError, match='ceiling'):
        ledger.consume({})
    assert len(json.loads(path.read_text(encoding='utf-8'))['calls']) == 20


def test_synthea_slice_trace_and_gaps():
    directory = ROOT / 'examples/claims_review/synthea'
    assert verify(directory)['verified_subset_rows'] == 8
    c = CaseInput.model_validate_json((directory / 'SYNTHEA-START-001.json').read_text(encoding='utf-8'))
    r = run_review(c)
    assert r.status == 'NEEDS_HUMAN_REVIEW' and set(statuses(r).values()) == {'INSUFFICIENT_EVIDENCE'}
    assert not any(f.kind == 'test_event' and f.fact_date == c.claim.service_date for f in r.facts)
    assert r.execution['actual_provider_calls'] == 0 and all(s['original_locator']['original_ehr_available_at'] is None for s in r.preparation['source_candidates'])


def test_affirmative_rationale_counterevidence_and_conflict_are_not_missing_data():
    c = changed(case(2), lambda b: b['sources'][3].update(content=
        'The asserted treatment-change rationale for HbA1c on 2026-09-22 is contradicted: the adjustment did not occur.\n'
        'The adjustment was started on 2026-08-10.'))
    s = source(c)
    negative = assertion(s, 'clinical_rationale', False, target_date='2026-09-22', test_specific=True,
                         span_ids=[s['line_anchors'][0]['span_id']])
    base = dict(patient_id=s['patient_id'], source_id=s['source_id'])
    r = run_review(c, mode='fixture', provider=FixtureProvider({**base, 'facts': [negative]}))
    assert statuses(r)['SHORT_INTERVAL_RATIONALE'] == 'NOT_SUPPORTED'
    positive = assertion(s, 'clinical_rationale', 'implemented_change', target_date='2026-09-22', test_specific=True,
                         span_ids=[a['span_id'] for a in s['line_anchors']])
    change = assertion(s, 'regimen_change', True, fact_date='2026-08-10', date_role='adjustment_start')
    r = run_review(c, mode='fixture', provider=FixtureProvider({**base, 'facts': [negative, positive, change]}))
    assert statuses(r)['SHORT_INTERVAL_RATIONALE'] == 'CONFLICTED'


def test_no_target_sources_produce_no_fabricated_test():
    c = changed(case(1), lambda b: b.update(sources=[]))
    r = run_review(c)
    assert r.facts == [] and r.timeline == [] and r.status == 'NEEDS_HUMAN_REVIEW'
    assert set(statuses(r).values()) == {'INSUFFICIENT_EVIDENCE'}


def test_false_authentication_and_cancelled_order_stay_false():
    c = changed(case(1), lambda b: b['sources'][3]['content'].update(authentication_status='unsigned', order_status='cancelled'))
    r = run_review(c)
    f = next(f for f in r.facts if f.kind == 'order_intent')
    assert f.value is False and f.authenticated is False and statuses(r)['ORDER_INTENT'] == 'INSUFFICIENT_EVIDENCE'


def test_future_target_and_requested_date_cannot_manufacture_performance():
    c = changed(case(2), lambda b: b['claim'].update(service_date='2026-11-22'))
    r = run_review(c)
    assert statuses(r)['TEST_TIMELINE'] == 'INSUFFICIENT_EVIDENCE' and r.status == 'NEEDS_HUMAN_REVIEW'


def test_negative_signature_is_rejected_when_claimed_positive():
    c = changed(case(2), lambda b: b['sources'][3].update(content='HbA1c for 2026-09-22. Not signed by Dr. Simulated Provider.'))
    s = source(c)
    fact = assertion(source(case(2)), 'order_intent', True, test_specific=True, target_date='2026-09-22',
                     provider='Dr. Simulated Provider', authenticated=True, span_ids=[s['line_anchors'][0]['span_id']])
    with pytest.raises(RuntimeValidationError, match='negative authentication'):
        validate_proposal(dict(patient_id=s['patient_id'], source_id=s['source_id'], facts=[fact]), s, c.review_context.as_of)


@pytest.mark.parametrize('rationale_time', ['planned', 'unknown'])
def test_rationale_assertion_time_is_not_the_change_implementation_time(rationale_time):
    c = case(2);raw = proposal(c)
    next(f for f in raw['facts'] if f['kind'] == 'clinical_rationale')['temporal_status'] = rationale_time
    assert statuses(run_review(c, mode='fixture', provider=FixtureProvider(raw)))['SHORT_INTERVAL_RATIONALE'] == 'SUPPORTED'
    raw['facts'] = [f for f in raw['facts'] if f['kind'] != 'regimen_change']
    assert statuses(run_review(c, mode='fixture', provider=FixtureProvider(raw)))['SHORT_INTERVAL_RATIONALE'] == 'INSUFFICIENT_EVIDENCE'
