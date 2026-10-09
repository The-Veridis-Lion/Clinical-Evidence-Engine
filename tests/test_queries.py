"""Deterministic query semantics across resolved and unresolved clinical evidence."""
from datetime import date, timedelta

import pytest

from clinical_intelligence.domain import AssessmentClaim, CorrectionRelationship, PlanClaim
from clinical_intelligence.query import QuerySpec, query_collection, query_patient
from clinical_intelligence.reconcile import reconcile


MONDAY = date(2026, 2, 2)


def plan(ref="PLAN-A", start=MONDAY, end=MONDAY + timedelta(days=6), minutes=150, days=3):
    return {"factory": PlanClaim, "plan_ref": ref, "effective_start": start, "effective_end": end,
            "required_days": days, "required_minutes": minutes, "week_basis": "monday_sunday",
            "service_types": ["individual", "group", "family"], "signed": True}


def add_event(evidence, service, identifier, day, minutes):
    return evidence(identifier, [service(encounter_ref=identifier, service_date=day,
                                         actual_intervals=[], reported_minutes=minutes)])


def conflicted_week(evidence, service, fixed_minutes=(50, 50), candidates=(40, 50), start=MONDAY, add_plan=True):
    documents = [add_event(evidence, service, "SYN-E1", start, fixed_minutes[0]),
                 add_event(evidence, service, "SYN-E2", start + timedelta(days=1), fixed_minutes[1])]
    for i, candidate in enumerate(candidates):
        documents.append(evidence(f"third-report-{i}", [service(encounter_ref="SYN-E3", service_date=start + timedelta(days=2),
                                                              actual_intervals=[], reported_minutes=candidate)]))
    if add_plan:
        documents.append(evidence("plan", [plan(start=start, end=start + timedelta(days=6))]))
    return reconcile(documents)


def result(abstract, family, **fields):
    return query_patient(abstract, QuerySpec(family=family, **fields))["result"]


def test_missing_base_for_signed_correction_cannot_answer_zero(evidence):
    abstract=reconcile([evidence('erratum',[{'factory':CorrectionRelationship,'relation':'corrects',
        'signed':True,'target_encounter':'MISSING-E1','field':'minutes','replacement_minutes':28,
        'service_date':MONDAY}])])
    actual=result(abstract,'utilization',start=MONDAY,end=MONDAY)
    assert actual['totals']['minutes']=={'lower':0,'upper':None,'value':None}
    assert actual['totals']['sessions']['value'] is None
    assert actual['unresolved_service_corrections']==['erratum:0']
    assert 'erratum:0' in actual['calculation']['claim_ids']
    assert result(abstract,'utilization',start=MONDAY+timedelta(days=1),end=MONDAY+timedelta(days=1))['totals']['minutes']['value']==0
    assert result(abstract,'utilization',start=MONDAY,end=MONDAY,service_types=[])['totals']['minutes']['value']==0


def test_unsigned_correction_does_not_create_unknown_utilization(evidence):
    abstract=reconcile([evidence('draft',[{'factory':CorrectionRelationship,'relation':'corrects',
        'signed':False,'target_encounter':'MISSING-E1','field':'minutes','replacement_minutes':28,
        'service_date':MONDAY}])])
    assert result(abstract,'utilization',start=MONDAY,end=MONDAY)['totals']['minutes']['value']==0


def test_unresolved_service_correction_propagates_through_plan_and_cohort(evidence):
    abstract=reconcile([evidence('erratum',[plan(),{'factory':CorrectionRelationship,'relation':'corrects',
        'signed':True,'target_encounter':'MISSING-E1','field':'minutes','replacement_minutes':28,
        'service_date':MONDAY}])])
    assert result(abstract,'compliance')['weeks'][0]['status']=='cannot_determine'
    assert result(abstract,'cohort',min_minutes=10)['conditional_inclusion']
    assert result(abstract,'utilization')['totals']['minutes']['value'] is None


def test_patient_role_and_name_merge_assessments_but_partner_stays_separate(evidence,patient):
    def assessment(who,copy=False):
        return {'factory':AssessmentClaim,'instrument':'PHQ-9','assessment_date':MONDAY,
                'form_ref':'FORM-1','score':8,'reporter':who,'experiencer':who,'copied':copy}
    abstract=reconcile([evidence('original',[assessment(patient.name)]),evidence('copy',[assessment('patient',True)]),
                        evidence('partner',[assessment('partner')])])
    assert len(abstract.assessments)==2
    own=next(a for a in abstract.assessments if a.experiencer==patient.name)
    assert set(own.claim_ids)=={'original:0','copy:0'}
    assert abstract.source_claims[1].experiencer=='patient'


@pytest.mark.parametrize('unknown_field',['service_date','service_type'])
def test_missing_date_or_category_preserves_known_duration_without_guessing(evidence,service,unknown_field):
    abstract=reconcile([evidence('unknown',[service(actual_intervals=[],reported_minutes=20,**{unknown_field:None})])])
    actual=result(abstract,'utilization',start=MONDAY,end=MONDAY+timedelta(days=6))
    assert actual['totals']['sessions']=={'lower':0,'upper':1,'value':None}
    assert actual['totals']['therapy_days']=={'lower':0,'upper':1,'value':None}
    assert actual['totals']['minutes']=={'lower':0,'upper':20,'value':None}
    assert actual['totals']['minute_alternatives']==[0,20]
    assert result(abstract,'utilization',start=MONDAY,end=MONDAY,service_types=[])['totals']['minutes']['value']==0


def test_known_encounter_date_can_bind_an_undated_same_encounter_source(evidence,service):
    abstract=reconcile([evidence('dated',[service(reported_minutes=45)]),
                        evidence('undated',[service(service_date=None,reported_minutes=45)])])
    actual=result(abstract,'utilization',start=MONDAY,end=MONDAY)
    assert actual['totals']['minutes']['value']==45
    assert actual['totals']['sessions']['value']==1


def test_duration_conflict_does_not_make_known_sessions_and_dates_uncertain(evidence, service):
    abstract = conflicted_week(evidence, service)
    actual = result(abstract, "utilization")
    assert actual["totals"]["sessions"] == {"lower": 3, "upper": 3, "value": 3}
    assert actual["totals"]["therapy_days"] == {"lower": 3, "upper": 3, "value": 3}
    assert actual["totals"]["minutes"] == {"lower": 140, "upper": 150, "value": None}
    assert actual["totals"]["minute_alternatives"] == [140, 150]
    assert actual["totals"]["hours"]["lower"] == pytest.approx(140 / 60)
    assert actual["totals"]["hours"]["upper"] == pytest.approx(2.5)
    assert actual["by_service_type"]["individual"]["sessions"]["value"] == 3


@pytest.mark.parametrize("fixed,status,alternatives", [
    ((45, 45), "not_met", [130, 140]),
    ((60, 60), "met", [160, 170]),
    ((50, 50), "cannot_determine", [140, 150]),
])
def test_compliance_compares_every_supported_duration_candidate(evidence, service, fixed, status, alternatives):
    abstract = conflicted_week(evidence, service, fixed_minutes=fixed)
    week = result(abstract, "compliance")["weeks"][0]
    assert week["status"] == status
    assert week["actual"]["totals"]["minute_alternatives"] == alternatives
    assert week["conflicts"]  # Uncertainty survives even when the threshold result is definite.
    assert week["requirement"]["minutes"] == 150


def test_missing_duration_keeps_unbounded_upper_instead_of_zero(evidence, service):
    abstract = conflicted_week(evidence, service, candidates=(None,))
    actual = result(abstract, "utilization")
    assert actual["totals"]["sessions"]["value"] == 3
    assert actual["totals"]["therapy_days"]["value"] == 3
    assert actual["totals"]["minutes"] == {"lower": 100, "upper": None, "value": None}
    assert actual["totals"]["minute_alternatives"] is None
    assert actual["totals"]["hours"]["upper"] is None
    assert result(abstract, "compliance")["weeks"][0]["status"] == "cannot_determine"


def test_known_day_shortfall_proves_not_met_even_with_unknown_minutes(evidence, service):
    abstract = reconcile([
        add_event(evidence, service, "first", MONDAY, None),
        add_event(evidence, service, "second", MONDAY + timedelta(days=1), 200),
        evidence("plan", [plan()]),
    ])
    week = result(abstract, "compliance")["weeks"][0]
    assert week["actual"]["totals"]["minutes"]["upper"] is None
    assert week["actual"]["totals"]["therapy_days"]["value"] == 2
    assert week["status"] == "not_met"


def test_midweek_plan_change_requires_weekly_applicability_clarification(evidence, service):
    abstract = reconcile([
        add_event(evidence, service, "first", MONDAY, 200),
        evidence("old-plan", [plan(end=None)]),
        evidence("new-plan", [plan(ref="PLAN-B", start=MONDAY + timedelta(days=2), minutes=90),
                              {"factory": CorrectionRelationship, "relation": "supersedes_plan", "signed": True,
                               "target_plan_ref": "PLAN-A", "field": "plan"}]),
    ])
    week = result(abstract, "compliance")["weeks"][0]
    assert week["status"] == "cannot_determine"
    assert week["requirement"] is None
    assert len(week["candidate_plans"]) == 2
    assert "No prorating" in week["ambiguity"]


def test_missing_signed_plan_does_not_invent_a_threshold(evidence, service):
    abstract = conflicted_week(evidence, service, add_plan=False)
    week = result(abstract, "compliance")["weeks"][0]
    assert week["status"] == "cannot_determine"
    assert week["requirement"] is None
    assert week["candidate_plans"] == []


@pytest.mark.parametrize("care,status,individual_outcomes", [
    ((60, 60, 60), "met", {"met"}),
    ((60,), "not_met", {"not_met"}),
    ((65, 65), "cannot_determine", {"met", "not_met"}),
])
def test_overlapping_full_week_plans_keep_conflict_but_compare_all_consequences(evidence, service, care, status, individual_outcomes):
    documents = [add_event(evidence, service, f"contact-{index}", MONDAY + timedelta(days=index), minutes)
                 for index, minutes in enumerate(care)]
    documents += [evidence("strict-plan", [plan(ref="PLAN-A", days=3, minutes=150)]),
                  evidence("other-plan", [plan(ref="PLAN-B", days=2, minutes=120)])]
    abstract = reconcile(documents)
    week = result(abstract, "compliance")["weeks"][0]
    assert week["status"] == status
    assert week["requirement"] is None
    assert len(week["candidate_plans"]) == len(week["candidate_comparisons"]) == 2
    assert {candidate["status"] for candidate in week["candidate_comparisons"]} == individual_outcomes
    assert any(conflict["field"] == "applicable_plan" for conflict in week["conflicts"])
    assert {"strict-plan:0", "other-plan:0"} <= set(week["calculation"]["claim_ids"])


def test_overlapping_plan_candidates_use_each_plans_eligible_service_types(evidence, service):
    abstract = reconcile([
        evidence("individual-care", [service(actual_intervals=[], reported_minutes=60)]),
        evidence("individual-plan", [plan(ref="PLAN-A", days=1, minutes=30) | {"service_types": ["individual"]}]),
        evidence("group-plan", [plan(ref="PLAN-B", days=1, minutes=30) | {"service_types": ["group"]}]),
    ])
    week = result(abstract, "compliance")["weeks"][0]
    assert week["status"] == "cannot_determine"
    outcomes = {tuple(item["requirement"]["service_types"]): item["status"] for item in week["candidate_comparisons"]}
    assert outcomes == {("individual",): "met", ("group",): "not_met"}


def comparison_fixture(evidence, service, change=False):
    documents = [add_event(evidence, service, "before", MONDAY + timedelta(days=1), 30),
                 add_event(evidence, service, "after", MONDAY + timedelta(days=8), 60),
                 evidence("old-plan", [plan(end=MONDAY + timedelta(days=13))])]
    if change:
        documents.append(evidence("new-plan", [plan(ref="PLAN-B", start=MONDAY + timedelta(days=7),
                                                    end=MONDAY + timedelta(days=13), minutes=90),
                                               {"factory": CorrectionRelationship, "relation": "supersedes_plan", "signed": True,
                                                "target_plan_ref": "PLAN-A", "field": "plan"}]))
    return reconcile(documents)


def test_before_after_does_not_invent_a_plan_change(evidence, service):
    abstract = comparison_fixture(evidence, service)
    answer = result(abstract, "compare_periods")
    assert answer["status"] == "insufficient_evidence"
    assert "No unique documented plan change" in answer["explanation"]


@pytest.mark.parametrize("use_documented_change", [False, True])
def test_before_after_uses_explicit_or_documented_boundary(evidence, service, use_documented_change):
    abstract = comparison_fixture(evidence, service, change=use_documented_change)
    fields = {} if use_documented_change else {"change_date": MONDAY + timedelta(days=7)}
    answer = result(abstract, "compare_periods", **fields)
    assert answer["change_date"] == MONDAY + timedelta(days=7)
    assert answer["before"]["totals"]["minutes"]["value"] == 30
    assert answer["after"]["totals"]["minutes"]["value"] == 60
    assert answer["difference_after_minus_before"]["minutes"]["value"] == 30
    assert answer["difference_after_minus_before"]["sessions"]["value"] == 0
    assert answer["difference_after_minus_before"]["therapy_days"]["value"] == 0


def test_same_day_encounters_are_two_sessions_and_one_treatment_day(evidence, service):
    abstract = reconcile([add_event(evidence, service, "a", MONDAY, 30),
                          add_event(evidence, service, "b", MONDAY, 45)])
    answer = result(abstract, "encounters", dates=[MONDAY])["dates"][0]
    assert answer["totals"]["sessions"]["value"] == 2
    assert answer["totals"]["therapy_days"]["value"] == 1
    assert answer["totals"]["minutes"]["value"] == 75


def longitudinal(evidence, service, second_crosses=False):
    documents = [evidence("plan", [plan(end=MONDAY + timedelta(days=13))])]
    for offset in (0, 7):
        for day_index in range(3):
            day = MONDAY + timedelta(days=offset + day_index)
            identifier = f"week-{offset}-event-{day_index}"
            minute_value = 45
            if second_crosses and offset == 7 and day_index == 2:
                minute_value = 55
            documents.append(add_event(evidence, service, identifier, day, minute_value))
            if second_crosses and offset == 7 and day_index == 2:
                documents.append(evidence("conflicting-third", [service(encounter_ref=identifier, service_date=day,
                                                                          actual_intervals=[], reported_minutes=65)]))
    return reconcile(documents)


def test_consecutive_not_met_weeks_are_demonstrated_windows(evidence, service):
    answer = result(longitudinal(evidence, service), "consecutive_under_target")
    assert answer["included"] is True
    assert answer["conditional_inclusion"] is False
    assert answer["definite_windows"] == [[MONDAY, MONDAY + timedelta(days=7)]]
    assert [week["status"] for week in answer["weeks"]] == ["not_met", "not_met"]


def test_unknown_threshold_week_creates_conditional_not_demonstrated_window(evidence, service):
    answer = result(longitudinal(evidence, service, second_crosses=True), "consecutive_under_target")
    assert answer["included"] is False
    assert answer["conditional_inclusion"] is True
    assert answer["definite_windows"] == []
    assert answer["conditional_windows"] == [[MONDAY, MONDAY + timedelta(days=7)]]
    assert [week["status"] for week in answer["weeks"]] == ["not_met", "cannot_determine"]


def rename_patient(abstract, patient_id):
    clone = abstract.model_copy(deep=True)
    clone.patient.patient_id = patient_id
    for claim in clone.source_claims:
        claim.patient_id = patient_id
    for event in clone.events:
        event.patient_id = patient_id
    for plan_item in clone.plans:
        plan_item.patient_id = patient_id
    return clone


def test_collection_cohort_filters_definite_conditional_and_excluded_patients(evidence, service):
    patients = [rename_patient(conflicted_week(evidence, service, fixed_minutes=(45, 45)), "LOW"),
                rename_patient(conflicted_week(evidence, service, fixed_minutes=(60, 60)), "HIGH"),
                rename_patient(conflicted_week(evidence, service), "CROSSING")]
    answer = query_collection(patients, QuerySpec(family="cohort", min_sessions=3, min_minutes=150))
    assert answer["included_patient_ids"] == ["HIGH"]
    assert answer["conditional_patient_ids"] == ["CROSSING"]
    selected = query_collection(patients, QuerySpec(family="cohort", patient_id="HIGH", min_minutes=150))
    assert len(selected["patients"]) == 1


def test_collection_consecutive_filter_separates_definite_and_conditional(evidence, service):
    patients = [rename_patient(longitudinal(evidence, service), "DEFINITE"),
                rename_patient(longitudinal(evidence, service, second_crosses=True), "CONDITIONAL")]
    answer = query_collection(patients, QuerySpec(family="consecutive_under_target"))
    assert answer["included_patient_ids"] == ["DEFINITE"]
    assert answer["conditional_patient_ids"] == ["CONDITIONAL"]


def test_weekly_and_compliance_calculations_reference_source_claims(evidence, service):
    abstract = conflicted_week(evidence, service)
    weekly = result(abstract, "weekly_utilization")
    assert len(weekly["weeks"]) == 1
    assert weekly["overall"]["totals"] == weekly["weeks"][0]["totals"]
    identifiers = {claim.claim_id for claim in abstract.source_claims}
    trace = weekly["weeks"][0]["calculation"]
    assert trace["event_ids"]
    assert set(trace["claim_ids"]) <= identifiers
    compliance_trace = result(abstract, "compliance")["weeks"][0]["calculation"]
    assert "plan:0" in compliance_trace["claim_ids"]
    assert set(compliance_trace["claim_ids"]) <= identifiers


def test_same_week_conflicting_date_still_guarantees_one_treatment_day(evidence, service):
    abstract = reconcile([
        evidence("earlier", [service(service_date=MONDAY, actual_intervals=[], reported_minutes=30)]),
        evidence("later", [service(service_date=MONDAY + timedelta(days=1), actual_intervals=[], reported_minutes=30)]),
        evidence("plan", [plan(days=1, minutes=20)]),
    ])
    utilization = result(abstract, "utilization")
    assert utilization["totals"]["sessions"]["value"] == 1
    assert utilization["totals"]["therapy_days"]["value"] == 1
    assert result(abstract, "compliance")["weeks"][0]["status"] == "met"


def test_partial_week_filter_does_not_erase_known_monday_care_from_weekly_compliance(evidence, service):
    abstract = reconcile([add_event(evidence, service, "monday-care", MONDAY, 30),
                          evidence("plan", [plan(days=1, minutes=20)])])
    week = result(abstract, "compliance", start=MONDAY + timedelta(days=1), end=MONDAY + timedelta(days=6))["weeks"][0]
    # A whole-week goal cannot be refuted by filtering out a documented day in that week.
    assert week["status"] != "not_met"


def test_date_alternatives_do_not_create_impossible_consecutive_under_target_window(evidence, service):
    abstract = reconcile([
        evidence("week-one-date", [service(service_date=MONDAY, actual_intervals=[], reported_minutes=30)]),
        evidence("week-two-date", [service(service_date=MONDAY + timedelta(days=7), actual_intervals=[], reported_minutes=30)]),
        evidence("plan", [plan(days=1, minutes=20, end=MONDAY + timedelta(days=13))]),
    ])
    answer = result(abstract, "consecutive_under_target")
    assert answer["included"] is False
    assert answer["conditional_inclusion"] is False
    # Whichever week owns this single delivered contact meets its goal: both cannot fail.
    assert answer["definite_windows"] == answer["conditional_windows"] == []


def test_assessment_score_changes_never_cross_between_experiencers(evidence):
    def measure(day, score, experiencer):
        return {"factory": AssessmentClaim, "instrument": "PHQ-9", "assessment_date": day,
                "score": score, "reporter": experiencer, "experiencer": experiencer}
    abstract = reconcile([
        evidence("patient-baseline", [measure(MONDAY, 18, "Taylor Example")]),
        evidence("partner-own-score", [measure(MONDAY + timedelta(days=1), 5, "Morgan Example")]),
        evidence("patient-followup", [measure(MONDAY + timedelta(days=4), 12, "Taylor Example")]),
    ])
    changes = result(abstract, "assessments")["score_changes"]
    assert [change["output"]["difference_options"] for change in changes] == [[-6]]
    assert {"patient-baseline:0", "patient-followup:0"} == set(changes[0]["claim_ids"])


def test_assessment_query_includes_possible_completion_date_without_inventing_one(evidence):
    def measure(day):
        return {"factory": AssessmentClaim, "instrument": "PHQ-9", "assessment_date": day,
                "form_ref": "FORM-1", "score": 14, "reporter": "Taylor Example", "experiencer": "Taylor Example"}
    abstract = reconcile([evidence("first-date", [measure(MONDAY)]),
                          evidence("other-date", [measure(MONDAY + timedelta(days=1))])])
    answer = result(abstract, "assessments", start=MONDAY + timedelta(days=1), end=MONDAY + timedelta(days=1))
    assert len(answer["assessments"]) == 1
    item = answer["assessments"][0]
    assert item["assessment_date"] is None
    assert item["date_options"] == [MONDAY, MONDAY + timedelta(days=1)]
    assert item["state"] == "conflicted"
    assert answer["score_changes"] == []




def test_public_requests_assemble_provenance_once(evidence, service, monkeypatch):
    from clinical_intelligence import provenance
    abstract = conflicted_week(evidence, service)
    calls = []
    original = provenance.add_runtime_provenance
    def assemble(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(provenance, "add_runtime_provenance", assemble)
    query_patient(abstract, QuerySpec(family="compliance"))
    assert len(calls) == 1
    calls.clear()
    query_collection([abstract], QuerySpec(family="compliance"))
    assert len(calls) == 1
