"""Saved-packet patient queries: engineering contracts, not clinical accuracy."""
import copy
import json

import pytest

from clinical_intelligence.copilot.models import Source
from clinical_intelligence.copilot.service import build_packet, project
from clinical_intelligence.copilot.patient_queries import (
    capabilities, interpretation_prompt, interpretation_schema,
    query_patient_packets, validate_interpretation,
)


def packet(case, text, *, concept='cough', category='symptom', event_time=None,
           temporality='current', action='unknown', duration=None, frequency=None,
           value=None, unit=None, experiencer='patient', polarity='present', scope=None,
           record_time=None):
    source = Source.create('source-' + case, text, encounter_time=record_time)
    fact = dict(category=category, concept=concept, original_term=text, polarity=polarity,
                temporality=temporality, experiencer=experiencer,
                attributes=dict(severity=None, duration=duration, value=value, unit=unit),
                assertion_basis='documented_history', attribution_confidence='context_supported',
                clinical_status=action, evidence=dict(start=0, end=len(text), quote=text))
    semantics = dict(version='clinical-fact-semantics/2', event_time=event_time,
                     duration=duration, frequency=frequency, action_state=action,
                     completion_scope=scope, assertion_basis='documented_history',
                     action_type=None)
    return build_packet(case, 'patient-one', source,
                        dict(document_id=source.document_id, facts=[fact],
                             clinical_semantics=[dict(fact_index=0, semantics=semantics)]),
                        projection_version='soap/v6')


def workspace(*bindings, encounters=None):
    # Binding tuples are packet, explicit encounter ID (or None), record date.
    documents = [dict(case_id=p.case_id, document_id='uploaded-' + p.case_id,
                      encounter_id=identity, encounter_time=day, status='ready')
                 for p, identity, day in bindings]
    return dict(patient=dict(patient_id='patient-one'), documents=documents,
                encounters=encounters if encounters is not None else [
                    dict(encounter_id=identity, encounter_time=day)
                    for _, identity, day in bindings if identity], evidence_version='saved-42')


def run(ws, packets, family, **filters):
    return query_patient_packets(ws, packets, dict(family=family, filters=filters))


def test_visits_count_explicit_encounters_not_files_or_days_and_keep_unknown_membership():
    a = packet('a', 'Patient reports cough.')
    b = packet('b', 'Patient reports fever.', concept='fever')
    c = packet('c', 'Patient reports nausea.', concept='nausea')
    d = packet('d', 'Patient reports dizziness.', concept='dizziness')
    ws = workspace((a, 'visit-a', '2026-10-01'), (b, 'visit-a', '2026-10-01'),
                   (c, 'visit-b', '2026-10-01'), (d, None, None))
    result = run(ws, [a, b, c, d], 'visit_count')
    assert result['answer']['visit_count'] == 2
    assert result['evidence_version'] == 'saved-42'
    assert any(m['reason'] == 'document_has_no_explicit_encounter_id' for m in result['missing_data'])
    metadata = [r for r in result['source_refs'] if r['reference_kind'].startswith('metadata_only')]
    assert metadata and all(r['quote'] is None and r['start'] is None for r in metadata)
    assert result['model_calls'] == 0 and result['model_used_for_interpretation'] is False


def test_frequency_is_actual_explicit_visits_per_week_not_prescription_frequency():
    p = packet('freq', 'Physiotherapy is planned twice weekly.', concept='physiotherapy',
               category='treatment', action='planned', frequency='twice weekly', temporality='planned')
    ws = workspace((p, 'scheduled-only', '2026-10-01'), encounters=[
        dict(encounter_id='scheduled-only', encounter_time='2026-10-01', status='scheduled'),
        dict(encounter_id='actual-a', encounter_time='2026-10-05', status='completed'),
        dict(encounter_id='actual-b', encounter_time='2026-10-05', status='completed')])
    result = run(ws, [p], 'visit_frequency', start='2026-10-01', end='2026-10-14')
    assert result['answer']['visit_count'] == 2
    assert [w['visit_count'] for w in result['answer']['weeks']] == [0, 2, 0]
    assert result['answer']['prescribed_frequency_used'] is False
    assert result['answer']['weeks'][0]['observed_start'] == '2026-10-01'


def test_undated_and_conflicting_encounters_do_not_count_and_do_not_fall_back_to_upload_order():
    p = packet('unknown-encounter', 'Patient reports cough.')
    ws = workspace((p, 'v', None), encounters=[dict(encounter_id='v', encounter_time=None)])
    assert run(ws, [p], 'visit_count')['answer']['visit_count'] == 0
    ws['encounters'] = [dict(encounter_id='v', encounter_time='2026-10-01'),
                        dict(encounter_id='v', encounter_time='2026-10-02')]
    result = run(ws, [p], 'visit_count')
    assert result['answer']['visit_count'] == 0
    assert result['missing_data'][0]['reason'] == 'missing_or_conflicting_encounter_date'


def test_completed_duration_normalizes_fixed_units_and_does_not_use_calendar_span():
    a = packet('duration-a', 'On 2026-10-01 the patient completed physiotherapy for 30 minutes.',
               concept='physiotherapy', category='treatment', action='completed', duration='30 minutes',
               event_time='2026-10-01', scope='single_event')
    b = packet('duration-b', 'On 2026-10-09 the patient completed physiotherapy for 1.5 hours.',
               concept='physiotherapy', category='treatment', action='completed', duration='1.5 hours',
               event_time='2026-10-09', scope='single_event')
    ws = workspace((a, 'a', '2026-10-01'), (b, 'b', '2026-10-09'))
    result = run(ws, [a, b], 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 120
    assert result['answer']['documented_hours'] == 2
    assert result['answer']['minutes'] == dict(lower=120, upper=120, value=120)
    assert len(result['answer']['events']) == 2
    for ref in result['source_refs']:
        source = next(p.source for p in [a, b] if p.case_id == ref['case_id'])
        assert source.text[ref['start']:ref['end']] == ref['quote']


@pytest.mark.parametrize('category,action,duration,time,reason', [
    ('symptom', 'completed', '30 minutes', '2026-10-01', 'outside_query_category'),
    ('treatment', 'ongoing', '30 minutes', '2026-10-01', 'no_completed_treatment_assertion'),
    ('treatment', 'planned', '30 minutes', '2026-10-01', 'no_completed_treatment_assertion'),
    ('treatment', 'completed', 'daily', '2026-10-01', 'missing_or_nonexact_documented_duration'),
    ('treatment', 'completed', '2 months', '2026-10-01', 'missing_or_nonexact_documented_duration'),
    ('treatment', 'completed', '30 minutes', None, 'event_date_unknown_or_not_exact'),
])
def test_noncompleted_frequency_symptom_duration_and_unknown_date_never_supply_actual_total(
        category, action, duration, time, reason):
    text = f'Patient documented {action} physiotherapy for {duration}.'
    p = packet('exclude', text, concept='physiotherapy', category=category, action=action,
               duration=duration, event_time=time)
    result = run(workspace((p, 'v', '2026-10-01')), [p], 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 0
    assert reason in [r['reason'] for r in result['missing_data'] + result['excluded_records']]


def test_duplicate_same_source_and_packet_revisions_are_not_counted_twice():
    a = packet('duplicate-a', 'On 2026-10-01 the patient completed therapy for 30 minutes.',
               concept='therapy', category='treatment', action='completed', duration='30 minutes',
               event_time='2026-10-01', scope='single_event')
    b = packet('duplicate-b', a.source.text, concept='therapy', category='treatment',
               action='completed', duration='30 minutes', event_time='2026-10-01', scope='single_event')
    revised = a.model_copy(deep=True)
    revised.version = 2
    revised.parent_hash = a.content_hash
    revised = project(revised)
    ws = workspace((a, 'v', '2026-10-01'), (b, 'v', '2026-10-01'))
    result = run(ws, [a, revised, b], 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 30
    assert len(result['source_refs']) == 2
    assert {r['reason'] for r in result['excluded_records']} >= {
        'superseded_packet_revision', 'duplicate_same_source_assertion'}
    assert next(r for r in result['computed_from'] if r['case_id'] == a.case_id)['packet_version'] == 2


def test_different_original_sources_do_not_create_two_identical_historical_treatments():
    a = packet('history-a', 'History: on 2026-10-01 patient completed therapy for 30 minutes.',
               concept='therapy', category='treatment', action='completed', duration='30 minutes',
               event_time='2026-10-01', temporality='historical', scope='single_event')
    b = packet('history-b', 'Prior care: patient completed therapy for 30 minutes on 2026-10-01.',
               concept='therapy', category='treatment', action='completed', duration='30 minutes',
               event_time='2026-10-01', temporality='historical', scope='single_event')
    result = run(workspace((a, 'a', '2026-10-02'), (b, 'b', '2026-10-09')),
                 [a, b], 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 0
    assert result['answer']['minutes']['upper'] is None
    assert len(result['missing_data']) == 2
    assert all('identity' in r['reason'] for r in result['missing_data'])


def test_same_day_single_events_bound_to_distinct_encounters_remain_separate():
    a = packet('same-day-a', 'On 2026-10-01 patient completed morning therapy for 30 minutes.',
               concept='therapy', category='treatment', action='completed', duration='30 minutes',
               event_time='2026-10-01', scope='single_event')
    b = packet('same-day-b', 'On 2026-10-01 patient completed afternoon therapy for 30 minutes.',
               concept='therapy', category='treatment', action='completed', duration='30 minutes',
               event_time='2026-10-01', scope='single_event')
    result = run(workspace((a, 'morning', '2026-10-01'), (b, 'afternoon', '2026-10-01')),
                 [a, b], 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 60
    assert len(result['answer']['events']) == 2


@pytest.mark.parametrize('second_date', ['2026-09-03', 'September 3, 2026', '3 September 2026'])
@pytest.mark.parametrize('temporality,record_day', [('historical', '2026-09-08'),
                                                 ('current', '2026-09-08')])
def test_retellings_use_normalized_event_day_not_raw_spelling_or_later_encounter(
        second_date, temporality, record_day):
    packets = [packet(f'retelling-{i}', f'Record {i}: completed therapy for 40 minutes on {day}.',
        concept='therapy', category='treatment', action='completed', duration='40 minutes',
        event_time=day, scope='single_event', temporality=temporality)
        for i, day in enumerate(['2026-09-03', second_date])]
    result = run(workspace(*[(p, f'review-{i}', record_day) for i, p in enumerate(packets)]),
                 packets, 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 0
    assert result['answer']['complete'] is False
    assert result['answer']['minutes']['upper'] is None
    retained = result['answer']['unaggregated_durations']
    assert [r['event_time'] for r in retained] == ['2026-09-03', second_date]
    assert {r['event_date'] for r in retained} == {'2026-09-03'}
    assert all(r['event_identity']['encounter_id'] is None for r in retained)
    assert len(result['calculation_steps'][0]['inputs']['duration_identity_assessment']) == 2


@pytest.mark.parametrize('second_time,expected', [('2026-09-03T14:00:00', 80),
                                               ('2026-09-03 09:00:00', 0),
                                               ('September 3, 2026', 0)])
def test_same_day_explicit_times_distinguish_sessions_but_date_only_does_not(second_time, expected):
    packets = [packet(f'clock-{i}', f'Record {i}: completed therapy for 40 minutes at {time}.',
        concept='therapy', category='treatment', action='completed', duration='40 minutes',
        event_time=time, scope='single_event', temporality='historical')
        for i, time in enumerate(['2026-09-03T09:00:00', second_time])]
    result = run(workspace(*[(p, 'review', '2026-09-08') for p in packets]),
                 packets, 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == expected
    assert result['answer']['complete'] is (expected == 80)
    if expected:
        assert all(r['event_identity']['basis'] == 'explicit_event_timestamp'
                   for r in result['answer']['events'])
        assert all(r['event_identity']['event_timestamp']
                   for r in result['calculation_steps'][0]['inputs']['contributions'])


def test_conflicting_same_day_durations_stay_unknown_while_other_dates_supply_subtotal():
    packets = [packet(f'conflict-{i}', f'Record {i}: completed therapy for {minutes} minutes on {day}.',
        concept='therapy', category='treatment', action='completed', duration=f'{minutes} minutes',
        event_time=day, scope='single_event', temporality='historical')
        for i, (day, minutes) in enumerate([('2026-09-03', 40), ('September 3, 2026', 45),
                                           ('2026-09-06', 50)])]
    result = run(workspace(*[(p, f'review-{i}', '2026-09-08') for i, p in enumerate(packets)]),
                 packets, 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 50
    assert result['answer']['complete'] is False
    assert len(result['answer']['unaggregated_durations']) == 2
    assert result['answer']['events'][0]['event_date'] == '2026-09-06'


@pytest.mark.parametrize('times,encounters,expected', [
    (['2026-09-03T09:00:00', '2026-09-03T09:00:00-04:00'], ['review', 'review'], 0),
    (['2026-09-03T09:00:00-04:00', '2026-09-03T14:00:00-04:00'], ['a', 'b'], 80),
    (['2026-09-03T23:30:00-04:00', '2026-09-04T03:30:00Z'], ['a', 'b'], 0),
    (['2026-09-03T09:00:00', '2026-09-03T14:00:00'], ['a', 'b'], 0),
])
def test_timestamps_only_distinguish_events_with_comparable_timezone_context(times, encounters, expected):
    packets = [packet(f'timezone-{i}', f'Record {i}: completed therapy for 40 minutes at {time}.',
        concept='therapy', category='treatment', action='completed', duration='40 minutes',
        event_time=time, scope='single_event', temporality='historical')
        for i, time in enumerate(times)]
    result = run(workspace(*[(p, encounter, '2026-09-08') for p, encounter in zip(packets, encounters)]),
                 packets, 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == expected
    assert result['answer']['complete'] is (expected == 80)


@pytest.mark.parametrize('temporality,record_day', [('historical', '2026-09-08'),
                                                 ('current', '2026-09-03')])
def test_same_original_source_spelling_variants_are_one_assertion(temporality, record_day):
    text = 'Patient completed therapy for 40 minutes on September 3, 2026.'
    packets = [packet(f'copy-{i}', text, concept='therapy', category='treatment',
        action='completed', duration='40 minutes', event_time=day, scope='single_event',
        temporality=temporality) for i, day in enumerate(['2026-09-03', 'September 3, 2026'])]
    result = run(workspace(*[(p, f'review-{i}', record_day) for i, p in enumerate(packets)]),
                 packets, 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 40
    assert len(result['source_refs']) == 2
    assert result['answer']['events'][0]['event_time_variants'] == ['2026-09-03', 'September 3, 2026']
    assert any(r['reason'] == 'duplicate_same_source_assertion' for r in result['excluded_records'])


def test_noncomparable_treatments_retain_individual_totals_without_combined_exposure():
    a = packet('types-a', 'On 2026-10-01 patient completed therapy for 30 minutes.',
               concept='therapy', category='treatment', action='completed', duration='30 minutes',
               event_time='2026-10-01', scope='single_event')
    b = packet('types-b', 'On 2026-10-01 patient completed occupational therapy for 45 minutes.',
               concept='occupational therapy', category='treatment', action='completed', duration='45 minutes',
               event_time='2026-10-01', scope='single_event')
    result = run(workspace((a, 'v', '2026-10-01'), (b, 'v', '2026-10-01')),
                 [a, b], 'documented_duration_sum')
    assert result['answer']['documented_minutes'] is None
    assert result['answer']['comparable_total'] is False
    assert len(result['answer']['groups']) == 2
    assert any(r['reason'] == 'noncomparable_duration_groups' for r in result['missing_data'])


@pytest.mark.parametrize('duration,scope', [('6 weeks', 'course'), ('30 minutes', 'course'),
                                            ('45 minutes', None)])
def test_course_duration_and_unknown_scope_remain_original_not_contact_minutes(duration, scope):
    p = packet('course', f'On 2026-10-01 patient completed physiotherapy for {duration}.',
               concept='physiotherapy', category='treatment', action='completed', duration=duration,
               event_time='2026-10-01', scope=scope)
    result = run(workspace((p, 'v', '2026-10-01')), [p], 'documented_duration_sum')
    assert result['answer']['documented_minutes'] == 0
    assert result['answer']['minutes']['upper'] is None
    assert result['answer']['complete'] is False
    retained = result['answer']['unaggregated_durations'][0]
    assert retained['attributes']['duration'] == duration
    assert retained['source_refs'][0]['quote'] == p.source.text


def test_legacy_saved_packet_still_supplies_current_record_status():
    original = packet('legacy', 'Patient reports cough.')
    p = build_packet('legacy', 'patient-one', original.source,
                     dict(document_id=original.source.document_id,
                          facts=[original.facts[0].original_fact]), projection_version='soap/v5')
    result = run(workspace((p, 'v', '2026-10-01')), [p], 'symptom_timeline')
    assert result['answer']['events'][0]['time_basis'] == 'encounter_record'
    assert result['answer']['events'][0]['event_time'] is None
    assert result['source_refs'][0]['quote'] == original.source.text


def test_unavailable_extraction_keeps_registered_encounter_and_unknown_clinical_data():
    p = packet('unavailable', 'Patient reports cough.')
    ws = workspace((p, 'v', '2026-10-01'))
    result = run(ws, [], 'visit_count')
    assert result['answer']['visit_count'] == 1
    assert result['answer']['attendance_confirmation'] == 'NOT_ESTABLISHED_BY_REGISTRATION'
    assert result['answer']['complete'] is False
    assert result['source_refs'][0]['reference_kind'] == 'metadata_only_encounter_association'
    duration = run(ws, [], 'documented_duration_sum')
    assert duration['answer']['minutes']['upper'] is None
    assert duration['answer']['complete'] is False


def test_current_symptom_record_time_is_useful_without_becoming_event_time():
    a = packet('current', 'Patient reports cough.')
    b = packet('historical', 'Patient had cough in childhood.', temporality='historical')
    c = packet('unmentioned', 'Patient reports nausea.', concept='nausea')
    ws = workspace((a, 'a', '2026-10-01'), (b, 'b', '2026-10-02'), (c, 'c', '2026-10-09'))
    result = run(ws, [a, b, c], 'symptom_timeline', concept='cough',
                 start='2026-10-01', end='2026-10-31')
    assert len(result['answer']['events']) == 1
    row = result['answer']['events'][0]
    assert row['record_time'] == '2026-10-01' and row['display_date'] == '2026-10-01'
    assert row['event_time'] is None and row['event_date'] is None
    assert row['time_basis'] == 'encounter_record'
    assert result['answer']['recorded_mentions'][0]['temporality'] == 'historical'
    assert all(r['polarity'] == 'present' for r in result['answer']['events'])
    assert len(result['answer']['undated_records']) == 2


def test_relative_event_time_preserves_wording_and_normalizes_only_with_record_anchor():
    p = packet('relative', 'Patient reports cough yesterday.', event_time='yesterday')
    ws = workspace((p, 'v', '2026-01-01'))
    row = run(ws, [p], 'symptom_timeline')['answer']['events'][0]
    assert row['event_time'] == 'yesterday' and row['event_date'] == '2025-12-31'
    assert row['record_date'] == '2026-01-01' and row['time_basis'] == 'explicit_relative_event_time'
    ws['documents'][0]['encounter_time'] = None
    result = run(ws, [p], 'symptom_timeline')
    assert result['answer']['events'] == []
    assert result['answer']['undated_records'][0]['event_time'] == 'yesterday'


@pytest.mark.parametrize('wording,expected', [('September 7, 2026', '2026-09-07'),
    ('7 September 2026', '2026-09-07'), ('Jan 3, 2025', '2025-01-03'),
    ('29 February 2024', '2024-02-29'), ('May 1 2026', '2026-05-01'),
    ('31 December 2026', '2026-12-31')])
def test_complete_english_event_dates_normalize_without_changing_original(wording, expected):
    p = packet('english-date', f'Patient cough was documented on {wording}.', event_time=wording)
    result = run(workspace((p, 'v', '2026-10-01')), [p], 'symptom_timeline')
    event = result['answer']['events'][0]
    assert event['event_date'] == expected
    assert event['event_time'] == event['original_event_time'] == wording
    assert event['normalization_basis'] == 'explicit_complete_english_event_time'


@pytest.mark.parametrize('wording', ['September 7', '7 September', 'May', 'May be 7, 2026',
    'February 29, 2025', 'September 7-9, 2026', 'between May 1 and May 3, 2026'])
def test_missing_year_ranges_invalid_dates_and_similar_words_do_not_supply_event_day(wording):
    p = packet('ambiguous-date', f'Patient reports cough; event wording: {wording}.', event_time=wording)
    result = run(workspace((p, 'v', '2026-10-01')), [p], 'symptom_timeline')
    event = result['answer']['events'][0]
    assert event['event_date'] is None and event['event_time'] == wording
    assert event['time_basis'] == 'encounter_record'


def test_query_preserves_explicit_status_without_inventing_resolution_from_absence():
    a = packet('resolved-status', 'Patient reports cough has resolved.')
    # Preserve the actual source-extracted field; do not infer a qualifier by
    # searching quotes, and keep its absence explicit for another saved fact.
    original = a.facts[0].original_fact.copy()
    original['clinical_status'] = 'resolved'
    a = build_packet(a.case_id, a.patient_id, a.source,
        dict(document_id=a.source.document_id, facts=[original]), projection_version='soap/v5')
    b = packet('absent-status', 'Patient denies cough.', polarity='absent')
    result = run(workspace((a, 'a', '2026-10-01'), (b, 'b', '2026-10-02')),
                 [a, b], 'symptom_timeline')
    first, second = result['answer']['events']
    assert first['clinical_status'] == first['status_qualifier'] == 'resolved'
    assert second['clinical_status'] == second['status_qualifier'] == 'unknown'


def test_observation_comparability_separates_subject_concept_and_scale():
    values = [packet('obs-a', 'On 2026-10-01 patient pain score was 3 of 10.',
                     category='observation', concept='pain', event_time='2026-10-01', value='3', unit='0-10'),
              packet('obs-b', 'On 2026-10-02 patient pain score was 3 of 5.',
                     category='observation', concept='pain', event_time='2026-10-02', value='3', unit='0-5'),
              packet('obs-c', 'On 2026-10-03 family pain score was 3 of 10.',
                     category='observation', concept='pain', event_time='2026-10-03',
                     value='3', unit='0-10', experiencer='family')]
    ws = workspace(*[(p, p.case_id, f'2026-10-0{i + 1}') for i, p in enumerate(values)])
    result = run(ws, values, 'observation_history')
    assert len(result['answer']['histories']) == 3
    assert all(h['clinical_trend'] == 'NOT_INFERRED' for h in result['answer']['histories'])


def test_workspace_ownership_hash_binding_and_filter_validation():
    p = packet('security', 'Patient reports cough.')
    ws = workspace((p, 'v', '2026-10-01'))
    wrong = copy.deepcopy(ws)
    wrong['patient']['patient_id'] = 'other-patient'
    with pytest.raises(ValueError, match='belong'):
        run(wrong, [p], 'visit_count')
    broken = p.model_copy(deep=True)
    broken.source = Source.create('replacement', 'Different text.')
    with pytest.raises(ValueError):
        run(ws, [broken], 'visit_count')
    for filters in [dict(start='10/01/2026'), dict(start='2026-10-02', end='2026-10-01'),
                    dict(sql='select *'), dict(experiencer='all')]:
        with pytest.raises(ValueError):
            run(ws, [p], 'visit_count', **filters)
    with pytest.raises(ValueError):
        run(ws, [p], 'invented_family')
    stale = copy.deepcopy(ws)
    stale['documents'][0]['packet_version'] = p.version + 1
    with pytest.raises(ValueError, match='reload'):
        run(stale, [p], 'visit_count')
    changed_source = copy.deepcopy(ws)
    changed_source['documents'][0]['source_hash'] = 'another-source'
    with pytest.raises(ValueError, match='binding'):
        run(changed_source, [p], 'visit_count')


def test_natural_language_schema_is_strict_finite_and_rejects_executable_extras():
    shape = interpretation_schema()
    for node in [shape, *shape['$defs'].values()]:
        if node.get('type') == 'object':
            assert node['additionalProperties'] is False
            assert set(node['required']) == set(node['properties'])
    ready = dict(status='ready', query_spec=dict(family='visit_count', filters={}),
                 clarification_question=None, explanation=None)
    assert validate_interpretation(json.dumps(ready))['query_spec']['family'] == 'visit_count'
    for mutation in [dict(code='return 7'), dict(query_spec=dict(family='sql', filters={})),
                     dict(status='unsupported')]:
        with pytest.raises(ValueError):
            validate_interpretation({**ready, **mutation})
    clarification = validate_interpretation(dict(status='needs_clarification', query_spec=None,
        clarification_question='Which explicit date range?', explanation='Relative dates need an anchor.'))
    assert clarification['query_spec'] is None
    prompt = interpretation_prompt('How many visits last week?', dict(patient_id='p', source='PRIVATE CHART'))
    assert 'PRIVATE CHART' not in prompt and 'machine time' in prompt
    assert 'last week' in prompt


def test_query_reuses_saved_packets_without_mutation_or_model_dispatch():
    p = packet('immutable', 'Patient reports cough.')
    before = p.model_dump_json()
    ws = workspace((p, 'v', '2026-10-01'))
    for family in capabilities()['families']:
        result = run(ws, {p.case_id: p}, family['family'])
        assert result['model_calls'] == 0
        assert result['computed_from'][0]['content_hash'] == p.content_hash
    assert p.model_dump_json() == before
