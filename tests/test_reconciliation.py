"""Regression cases target record semantics rather than implementation structure."""
from datetime import date, datetime

import pytest

from clinical_intelligence.domain import AssessmentClaim, CorrectionRelationship, PlanClaim, State
from clinical_intelligence.reconcile import reconcile


def test_cofacilitator_reports_are_one_service_with_both_sources(evidence, service):
    result = reconcile([evidence("primary", [service()]), evidence("coauthor", [service()])])
    assert len(result.events) == 1
    event = result.events[0]
    assert event.countable is True
    assert event.minute_options == [45]
    assert set(event.claim_ids) == {"primary:0", "coauthor:0"}
    assert len(result.source_claims) == 2


def test_one_appointment_can_link_multiple_connection_report_ids(evidence, service):
    result = reconcile([
        evidence("part-a", [service(encounter_ref="CALL-A", appointment_ref="APPT-1")]),
        evidence("part-b", [service(encounter_ref="CALL-B", appointment_ref="APPT-1")]),
    ])
    assert len(result.events) == 1
    assert result.events[0].appointment_refs == ["APPT-1"]


def test_same_day_distinct_encounters_remain_distinct(evidence, service):
    result = reconcile([evidence("a", [service()]), evidence("b", [service(encounter_ref="SYN-E2")])])
    assert len(result.events) == 2
    assert {e.encounter_ref for e in result.events} == {"SYN-E1", "SYN-E2"}


def test_unidentified_positive_report_does_not_establish_count(evidence, service):
    result = reconcile([evidence("a", [service(encounter_ref=None)])])
    event = result.events[0]
    assert event.countable is None
    assert event.state == State.INSUFFICIENT
    assert event.minutes_lower == 0
    assert event.uncertainties


def corrected_group(evidence, service):
    return [
        evidence("content", [service(service_type="group", actual_intervals=[],
                                     breaks=[{"start": 645, "end": 660}])]),
        evidence("original", [service(service_type="group", evidence_kind="attendance",
                                      actual_intervals=[{"start": 600, "end": 690}],
                                      recorded_at=datetime(2026, 2, 2, 12))], declared_id="DOC-ORIGINAL"),
        evidence("correction", [{"factory": CorrectionRelationship, "relation": "corrects",
                                  "signed": True, "target_encounter": "SYN-E1", "field": "departure",
                                  "replacement_time": 675, "original_time": 690,
                                  "service_date": date(2026, 2, 2),
                                  "recorded_at": datetime(2026, 2, 3, 12)}]),
        evidence("copy", [service(service_type="group", evidence_kind="retransmission",
                                  actual_intervals=[{"start": 600, "end": 690}],
                                  recorded_at=datetime(2026, 2, 9, 12)),
                          {"factory": CorrectionRelationship, "relation": "retransmits",
                           "target_encounter": "SYN-E1", "target_document_ref": "DOC-ORIGINAL",
                           "field": "record", "service_date": date(2026, 2, 2)}]),
    ]


def test_departure_correction_survives_later_copy_and_keeps_provenance(evidence, service):
    documents = corrected_group(evidence, service)
    result = reconcile(documents)
    event = result.events[0]
    assert event.minute_options == [60]
    assert event.state == State.RESOLVED
    assert event.countable is True
    assert {"original:0", "correction:0", "copy:0", "copy:1"} <= set(event.claim_ids)
    calculation = next(c for c in event.calculations if c.output == {"minutes": 60})
    assert {"original:0", "correction:0", "content:0"} <= set(calculation.claim_ids)
    # Reconciliation does not rewrite the immutable source interval.
    assert documents[1].claims[0].actual_intervals[0].end == 690


def test_relationship_policy_and_latest_wins_have_different_numeric_consequences(evidence, service):
    documents = corrected_group(evidence, service)
    explicit = reconcile(documents)
    naive = reconcile(documents, policy="latest_wins")
    assert explicit.events[0].minute_options == [60]
    assert naive.events[0].minute_options == [75]


def test_final_full_encounter_conflict_stays_one_countable_service(evidence, service):
    documents = [
        evidence("earlier", [service(actual_intervals=[{"start": 540, "end": 590}],
                                     reported_minutes=50, recorded_at=datetime(2026, 2, 2, 12))]),
        evidence("later", [service(actual_intervals=[{"start": 550, "end": 590}],
                                   reported_minutes=40, recorded_at=datetime(2026, 2, 3, 12))]),
    ]
    event = reconcile(documents).events[0]
    assert event.countable is True
    assert event.state == State.CONFLICTED
    assert event.minute_options == [40, 50]
    assert (event.minutes_lower, event.minutes_upper) == (40, 50)
    assert set(event.conflicts[0].claim_ids) == {"earlier:0", "later:0"}
    assert reconcile(documents, policy="latest_wins").events[0].minute_options == [40]


def test_interval_and_reported_duration_disagreement_is_not_hidden(evidence, service):
    event = reconcile([evidence("a", [service(reported_minutes=30)])]).events[0]
    assert event.state == State.CONFLICTED
    assert event.minute_options == [30, 45]


def test_patient_presence_disagreement_leaves_eligibility_unknown(evidence, service):
    event = reconcile([
        evidence("a", [service()]),
        evidence("b", [service(patient_present=False, actual_intervals=[])]),
    ]).events[0]
    assert event.state == State.CONFLICTED
    assert event.countable is None
    assert event.minutes_lower == 0
    assert any(c.field == "patient_present" for c in event.conflicts)


def test_signed_absence_wins_over_draft_and_charge_without_deleting_them(evidence, service):
    event = reconcile([
        evidence("roster", [service(evidence_kind="attendance", delivered=False,
                                    patient_present=False, actual_intervals=[])]),
        evidence("draft", [service(evidence_kind="draft", signed=False, reported_minutes=90)]),
        evidence("charge", [service(evidence_kind="billing", signed=False)]),
    ]).events[0]
    assert event.countable is False
    assert (event.minutes_lower, event.minutes_upper) == (0, 0)
    assert set(event.claim_ids) == {"roster:0", "draft:0", "charge:0"}


def test_unsigned_explicit_no_show_is_not_replaced_by_scheduling_callback(evidence, service):
    event = reconcile([
        evidence("desk-disposition", [service(evidence_kind="attendance", signed=False,
                                               delivered=False, patient_present=False, actual_intervals=[])]),
        evidence("scheduling-support", [service(encounter_ref=None, appointment_ref="SYN-E1",
                                                 evidence_kind="attendance", service_type="administrative",
                                                 signed=False, delivered=True, patient_present=None,
                                                 actual_intervals=[]),
                                        service(appointment_ref="SYN-E1", evidence_kind="attendance", signed=False,
                                                delivered=False, patient_present=False, actual_intervals=[])]),
    ]).events[0]
    assert event.countable is False
    assert event.minutes_lower == event.minutes_upper == 0
    assert set(event.claim_ids) == {"desk-disposition:0", "scheduling-support:0", "scheduling-support:1"}


@pytest.mark.parametrize("role", ["schedule", "draft", "billing"])
def test_prospective_or_administrative_record_alone_does_not_create_delivered_service(evidence, service, role):
    event = reconcile([evidence("prospective", [service(encounter_ref=None, evidence_kind=role, signed=False,
                                                        delivered=None, patient_present=None, actual_intervals=[],
                                                        scheduled_intervals=[{"start": 600, "end": 690}])])]).events[0]
    assert event.countable is False
    assert event.minutes_lower == event.minutes_upper == 0
    assert event.claim_ids == ["prospective:0"]
    assert event.decisions


@pytest.mark.parametrize("service_type,present", [("medication", True), ("collateral", False), ("coordination", False)])
def test_nontherapy_or_absent_patient_contact_is_excluded(evidence, service, service_type, present):
    event = reconcile([evidence("a", [service(service_type=service_type, patient_present=present)])]).events[0]
    assert event.countable is False
    assert event.minutes_lower == event.minutes_upper == 0


def test_family_patient_interval_excludes_partner_only_time(evidence, service):
    event = reconcile([evidence("a", [service(service_type="family",
                                             scheduled_intervals=[{"start": 780, "end": 825}],
                                             actual_intervals=[{"start": 795, "end": 825}])])]).events[0]
    assert event.minute_options == [30]


def assessment(score=14, day=date(2026, 2, 6), form="SYN-Q1", copied=False):
    return {"factory": AssessmentClaim, "instrument": "PHQ-9", "assessment_date": day,
            "form_ref": form, "score": score, "reporter": "Taylor Example",
            "experiencer": "Taylor Example", "copied": copied}


def test_copied_assessment_uses_completion_identity_not_receipt(evidence):
    result = reconcile([
        evidence("measure", [assessment()]),
        evidence("import", [assessment(copied=True) | {"recorded_at": datetime(2026, 2, 16)}]),
    ])
    assert len(result.assessments) == 1
    item = result.assessments[0]
    assert item.assessment_date == date(2026, 2, 6)
    assert item.score_options == [14]
    assert set(item.claim_ids) == {"measure:0", "import:0"}
    assert result.events == []


def test_distinct_completion_dates_without_form_ids_remain_distinct(evidence):
    result = reconcile([evidence("a", [assessment(day=date(2026, 2, 2), form=None, score=18)]),
                        evidence("b", [assessment(day=date(2026, 2, 6), form=None, score=14)])])
    assert len(result.assessments) == 2
    assert [a.score_options for a in result.assessments] == [[18], [14]]


def test_incompatible_scores_for_same_form_are_retained(evidence):
    result = reconcile([evidence("a", [assessment(score=14)]), evidence("b", [assessment(score=15)])])
    assert len(result.assessments) == 1
    assert result.assessments[0].state == State.CONFLICTED
    assert result.assessments[0].score_options == [14, 15]


def test_assessment_date_conflict_preserves_alternatives_without_choosing_earliest(evidence):
    result = reconcile([evidence("first", [assessment(day=date(2026, 2, 6))]),
                        evidence("second", [assessment(day=date(2026, 2, 7), copied=True)])])
    assert len(result.assessments) == 1
    assessment_item = result.assessments[0]
    assert assessment_item.state == State.CONFLICTED
    assert assessment_item.assessment_date is None
    assert assessment_item.date_options == [date(2026, 2, 6), date(2026, 2, 7)]
    assert set(assessment_item.claim_ids) == {"first:0", "second:0"}


def test_assessment_keeps_multiple_reporters_for_one_experiencer(evidence):
    result = reconcile([evidence("self-report", [assessment()]),
                        evidence("copied-review", [assessment(copied=True) | {"reporter": "Clinician Reviewer"}])])
    assert len(result.assessments) == 1
    assessment_item = result.assessments[0]
    assert assessment_item.experiencer == "Taylor Example"
    assert assessment_item.reporters == ["Clinician Reviewer", "Taylor Example"]


def test_same_form_reference_for_different_experiencers_does_not_merge_their_scores(evidence):
    result = reconcile([evidence("patient", [assessment(score=18)]),
                        evidence("partner", [assessment(score=5) | {"reporter": "Morgan Example", "experiencer": "Morgan Example"}])])
    assert len(result.assessments) == 2
    assert {item.experiencer: item.score_options for item in result.assessments} == {
        "Taylor Example": [18], "Morgan Example": [5],
    }


def plan(ref, start=date(2026, 2, 2), end=date(2026, 2, 27), minutes=150):
    return {"factory": PlanClaim, "plan_ref": ref, "effective_start": start, "effective_end": end,
            "required_days": 3, "required_minutes": minutes, "week_basis": "monday_sunday",
            "service_types": ["individual", "group", "family"], "signed": True}


def test_explicit_plan_change_truncates_only_prior_effective_period(evidence):
    result = reconcile([
        evidence("old", [plan("PLAN-A")]),
        evidence("new", [plan("PLAN-B", start=date(2026, 2, 16), minutes=90),
                         {"factory": CorrectionRelationship, "relation": "supersedes_plan",
                          "signed": True, "target_plan_ref": "PLAN-A", "field": "plan"}]),
    ])
    assert result.plans[0].effective_end == date(2026, 2, 15)
    assert result.plans[1].effective_start == date(2026, 2, 16)
    assert "new:1" in result.plans[0].claim_ids
    assert not any(c.field == "applicable_plan" for c in result.conflicts)


def test_overlapping_signed_plans_without_supersession_remain_conflicted(evidence):
    result = reconcile([evidence("a", [plan("PLAN-A")]),
                        evidence("b", [plan("PLAN-B", start=date(2026, 2, 16), minutes=90)])])
    assert len(result.plans) == 2
    assert any(c.field == "applicable_plan" for c in result.conflicts)


def test_incompatible_explicit_minute_corrections_preserve_corrected_alternatives(evidence, service):
    result = reconcile([
        evidence("original", [service(actual_intervals=[], reported_minutes=50)]),
        evidence("correct-a", [{"factory": CorrectionRelationship, "relation": "corrects",
                                "signed": True, "target_encounter": "SYN-E1", "field": "minutes",
                                "replacement_minutes": 40}]),
        evidence("correct-b", [{"factory": CorrectionRelationship, "relation": "corrects",
                                "signed": True, "target_encounter": "SYN-E1", "field": "minutes",
                                "replacement_minutes": 60}]),
    ])
    event = result.events[0]
    assert event.state == State.CONFLICTED
    assert event.minute_options == [40, 60]
    assert (event.minutes_lower, event.minutes_upper) == (40, 60)
    assert {"original:0", "correct-a:0", "correct-b:0"} <= set(event.claim_ids)


def test_document_specific_presence_correction_does_not_change_other_source(evidence, service):
    result = reconcile([
        evidence("first", [service(patient_present=False)], declared_id="DOC-A"),
        evidence("second", [service(patient_present=False)], declared_id="DOC-B"),
        evidence("correct", [{"factory": CorrectionRelationship, "relation": "corrects",
                              "signed": True, "target_encounter": "SYN-E1",
                              "target_document_ref": "DOC-A", "field": "presence",
                              "replacement_presence": True}]),
    ])
    event = result.events[0]
    assert event.state == State.CONFLICTED
    assert event.patient_present is None
    assert event.countable is None
    assert event.minutes_lower == 0
    assert any(c.field == "patient_present" for c in event.conflicts)


def test_chained_explicit_plan_changes_preserve_each_prior_period(evidence):
    result = reconcile([
        evidence("old", [plan("PLAN-A", end=None)]),
        evidence("middle", [plan("PLAN-B", start=date(2026, 2, 9), end=None, minutes=120),
                            {"factory": CorrectionRelationship, "relation": "supersedes_plan",
                             "signed": True, "target_plan_ref": "PLAN-A", "field": "plan"}]),
        evidence("new", [plan("PLAN-C", start=date(2026, 2, 16), end=None, minutes=90),
                         {"factory": CorrectionRelationship, "relation": "supersedes_plan",
                          "signed": True, "target_plan_ref": "PLAN-B", "field": "plan"}]),
    ])
    assert [p.effective_end for p in result.plans] == [date(2026, 2, 8), date(2026, 2, 15), None]
    assert not any(c.field == "applicable_plan" for c in result.conflicts)


def test_reconciliation_and_calculation_references_resolve_to_source_claims(evidence, service):
    result = reconcile(corrected_group(evidence, service))
    identifiers = {c.claim_id for c in result.source_claims}
    for event in result.events:
        assert set(event.claim_ids) <= identifiers
        for calculation in event.calculations:
            assert calculation.claim_ids
            assert set(calculation.claim_ids) <= identifiers
        for decision in event.decisions:
            assert set(decision.claim_ids) <= identifiers


def clock_correction(**changes):
    value = {"factory": CorrectionRelationship, "relation": "corrects", "signed": True,
             "target_encounter": "SYN-E1", "field": "arrival", "replacement_time": 550}
    value.update(changes)
    return value


def test_correction_document_and_encounter_constraints_do_not_leak(evidence, service):
    original = evidence("original", [
        service(actual_intervals=[{"start": 540, "end": 600}]),
        service(encounter_ref="SYN-E2", actual_intervals=[{"start": 660, "end": 720}]),
    ], declared_id="DOC-ORIGINAL")
    result = reconcile([original, evidence("correction", [clock_correction(
        target_document_ref="DOC-ORIGINAL", service_date=date(2026, 2, 2))])])
    events = {event.encounter_ref: event for event in result.events}
    assert events["SYN-E1"].minute_options == [50]
    assert events["SYN-E2"].minute_options == [60]
    assert sum(event.minutes_lower for event in events.values()) == 110
    assert "correction:0" not in events["SYN-E2"].claim_ids
    assert original.claims[0].actual_intervals[0].start == 540
    assert original.claims[1].actual_intervals[0].start == 660


def test_source_constraints_hold_inside_appointment_linked_group(evidence, service):
    result = reconcile([
        evidence("original", [service(appointment_ref="APPT-1", actual_intervals=[{"start": 540, "end": 600}]),
                              service(encounter_ref="SYN-E2", appointment_ref="APPT-1",
                                      actual_intervals=[{"start": 660, "end": 720}])], declared_id="DOC-ORIGINAL"),
        evidence("correction", [clock_correction(target_document_ref="DOC-ORIGINAL")]),
    ])
    event = result.events[0]
    assert len(result.events) == 1
    assert event.minute_options == [50, 60]
    corrected = next(trace for trace in event.calculations if trace.output == {"minutes": 50})
    unchanged = next(trace for trace in event.calculations if trace.output == {"minutes": 60})
    assert "correction:0" in corrected.claim_ids
    assert "correction:0" not in unchanged.claim_ids


@pytest.mark.parametrize("target", [
    {"target_document_ref": "DOC-OTHER"},
    {"service_date": date(2026, 2, 3)},
])
def test_contradictory_correction_targets_are_not_redirected(evidence, service, target):
    result = reconcile([
        evidence("original", [service(actual_intervals=[{"start": 540, "end": 600}])], declared_id="DOC-ORIGINAL"),
        evidence("correction", [clock_correction(**target)]),
    ])
    assert result.events[0].minute_options == [60]
    assert "correction:0" not in result.events[0].claim_ids
    assert any("correction:0" in uncertainty.claim_ids for uncertainty in result.uncertainties)
    assert result.relationships[0].claim_id == "correction:0"


@pytest.mark.parametrize("target", [
    {"target_encounter": None, "target_document_ref": "DOC-ORIGINAL"},
    {"target_encounter": "SYN-E1", "target_document_ref": None},
])
def test_document_only_and_encounter_only_corrections_remain_supported(evidence, service, target):
    result = reconcile([
        evidence("original", [service(actual_intervals=[{"start": 540, "end": 600}])], declared_id="DOC-ORIGINAL"),
        evidence("correction", [clock_correction(**target)]),
    ])
    assert result.events[0].minute_options == [50]
    assert result.events[0].state == State.RESOLVED


@pytest.mark.parametrize("reverse", [False, True])
def test_departure_correction_is_invariant_to_interval_order(evidence, service, reverse):
    intervals = [{"start": 540, "end": 570}, {"start": 600, "end": 630}]
    if reverse:
        intervals.reverse()
    original = evidence("original", [service(actual_intervals=intervals)])
    event = reconcile([original, evidence("correction", [clock_correction(
        field="departure", original_time=630, replacement_time=615)])]).events[0]
    assert event.minute_options == [45]
    assert event.state == State.RESOLVED
    assert {"original:0", "correction:0"} <= set(event.calculations[0].claim_ids)
    assert [interval.model_dump() for interval in original.claims[0].actual_intervals] == intervals


def test_arrival_correction_uses_earliest_contact_not_first_list_element(evidence, service):
    event = reconcile([
        evidence("original", [service(actual_intervals=[{"start": 600, "end": 630}, {"start": 540, "end": 570}])]),
        evidence("correction", [clock_correction(original_time=540)]),
    ]).events[0]
    assert event.minute_options == [50]
    assert event.state == State.RESOLVED


def test_unmatched_clock_correction_keeps_uncertainty_and_original_evidence(evidence, service):
    event = reconcile([
        evidence("original", [service(actual_intervals=[{"start": 540, "end": 600}])], declared_id="DOC-ORIGINAL"),
        evidence("correction", [clock_correction(target_document_ref="DOC-ORIGINAL", field="departure",
                                                 original_time=630, replacement_time=615)]),
    ]).events[0]
    assert event.state == State.INSUFFICIENT
    assert event.countable is True
    assert event.minute_options == [60]
    assert (event.minutes_lower, event.minutes_upper) == (0, None)
    assert {"original:0", "correction:0"} <= set(event.claim_ids)
    assert any(set(item.claim_ids) == {"original:0", "correction:0"} for item in event.uncertainties)
    assert not any(item.rule == "explicit_field_correction" for item in event.decisions)
