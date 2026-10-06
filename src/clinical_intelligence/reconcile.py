"""Clinical policy: preserve source statements; derive facts without model arbitration."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
from .domain import (Assessment, AssessmentClaim, CalculationTrace, ClinicalObservation, Conflict,
                     CorrectionRelationship, DocumentExtraction, EvidenceKind, PatientAbstraction,
                     PlanClaim, ReconciliationDecision, ServiceClaim, ServiceEvent, State,
                     THERAPY_TYPES, TimeInterval, TreatmentPlan, Uncertainty)
from .temporal import treatment_minutes

POLICY_VERSION = "3"


def stable_id(*values) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _conflict(subject, field, values, claims, explanation):
    return Conflict(conflict_id=stable_id(subject, field, values), subject_id=subject, field=field,
                    values=[str(v) for v in values], claim_ids=sorted(set(claims)), explanation=explanation)


def _groups(claims: list[ServiceClaim]) -> list[list[ServiceClaim]]:
    """Union only explicitly linked encounter/appointment references, within patient."""
    parents = list(range(len(claims)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    refs = {}
    # Same-day reports are not enough to merge contacts; require an explicit shared ID.
    for i, claim in enumerate(claims):
        for prefix, ref in (("encounter", claim.encounter_ref), ("appointment", claim.appointment_ref)):
            if not ref:
                continue
            key = (claim.patient_id, prefix, ref)
            if key in refs:
                parents[root(i)] = root(refs[key])
            refs[key] = i
    groups = defaultdict(list)
    for i, claim in enumerate(claims):
        groups[root(i)].append(claim)
    return list(groups.values())


def _corrected_variants(source, corrections, event_id, decisions, conflicts, uncertainties):
    # Work on copies so the original claim remains available for audit.
    variants = [(list(source.actual_intervals), source.reported_minutes, source.patient_present, [])]
    for field in ("arrival", "departure", "minutes", "presence"):
        choices = [r for r in corrections if r.field == field]
        if not choices:
            continue
        values = {(r.replacement_time, r.replacement_minutes, r.replacement_presence) for r in choices}
        if len(values) > 1:
            conflicts.append(_conflict(event_id, "correction_" + field, sorted(map(str, values)),
                                       [r.claim_id for r in choices], "Explicit corrections disagree; retain each supported replacement as an alternative."))
        updated = []
        for intervals, reported, presence, evidence in variants:
            applied_any = False
            for correction in choices:
                replacement = list(intervals)
                duration, present = reported, presence
                applied = False
                if field in {"arrival", "departure"} and intervals and correction.replacement_time is not None:
                    index = 0 if field == "arrival" else len(intervals) - 1
                    old_value = intervals[index].start if field == "arrival" else intervals[index].end
                    if correction.original_time is None or old_value == correction.original_time:
                        value = intervals[index].model_dump()
                        value["start" if field == "arrival" else "end"] = correction.replacement_time
                        try:
                            replacement[index] = TimeInterval(**value)
                            # The old reported duration may be stale after a clock correction.
                            duration = None
                            applied = True
                        except ValueError:
                            uncertainties.append(Uncertainty(subject_id=event_id, claim_ids=[source.claim_id, correction.claim_id],
                                                               explanation="Explicit correction creates an invalid interval.", needed_evidence="Valid corrected contact interval"))
                elif field == "minutes" and correction.replacement_minutes is not None:
                    replacement, duration, applied = [], correction.replacement_minutes, True
                elif field == "presence" and correction.replacement_presence is not None:
                    present, applied = correction.replacement_presence, True
                if applied:
                    applied_any = True
                    updated.append((replacement, duration, present, evidence + [correction.claim_id]))
                    decisions.append(ReconciliationDecision(rule="explicit_field_correction", claim_ids=[source.claim_id, correction.claim_id],
                                                           explanation=f"Apply signed {field} correction only to its identified source field; preserve original evidence."))
            if not applied_any:
                updated.append((intervals, reported, presence, evidence))
        variants = updated
    return variants


def _event(group: list[ServiceClaim], relationships: list[CorrectionRelationship], document_refs: dict[str, str | None],
           policy: str) -> ServiceEvent:
    group = sorted(group, key=lambda c: c.claim_id)
    ids = [c.claim_id for c in group]
    encounter_refs = sorted({c.encounter_ref for c in group if c.encounter_ref})
    appointment_refs = sorted({c.appointment_ref for c in group if c.appointment_ref})
    event_id = stable_id(group[0].patient_id, encounter_refs or appointment_refs or ids)
    decisions = [ReconciliationDecision(rule="explicit_identity", claim_ids=ids,
                                        explanation="Reports linked by explicit encounter/appointment identity describe one contact, not one contact per document or clinician.")]
    conflicts, uncertainties, calculations = [], [], []

    applicable_relations = [r for r in relationships if r.target_encounter in encounter_refs
                            or (r.target_document_ref is not None and any(document_refs.get(c.document_id) == r.target_document_ref for c in group))]
    # Signed care records establish positive authority; later copies add no new authority.
    active = [c for c in group if c.evidence_kind in {EvidenceKind.CLINICAL, EvidenceKind.ATTENDANCE} and c.signed]
    retransmitted_docs = {r.document_id for r in applicable_relations if r.relation == "retransmits"}
    active = [c for c in active if c.document_id not in retransmitted_docs]
    excluded = [c.claim_id for c in group if c not in active]
    if excluded:
        decisions.append(ReconciliationDecision(rule="evidence_role", claim_ids=excluded,
                                               explanation="Copies, draft templates, billing quantities and scheduled slots are retained but do not independently establish delivered patient treatment."))
    # Explicit no-show/absence records can establish nondelivery without a signature.
    negative = [c for c in group if c.evidence_kind in {EvidenceKind.SCHEDULE, EvidenceKind.ATTENDANCE, EvidenceKind.CLINICAL}
                and (c.delivered is False or c.patient_present is False)]
    if not active:
        active = negative
    if policy == "latest_wins":
        # Deliberately naive comparator: copied original attendance counts as latest evidence.
        eligible = [c for c in group if c.evidence_kind in {EvidenceKind.CLINICAL, EvidenceKind.ATTENDANCE, EvidenceKind.RETRANSMISSION}]
        if eligible:
            active = [max(eligible, key=lambda c: (c.recorded_at.isoformat() if c.recorded_at else "", c.claim_id))]
        decisions.append(ReconciliationDecision(rule="naive_latest_document", claim_ids=[c.claim_id for c in active],
                                               explanation="Experiment only: latest recorded timestamp wins; correction relationships ignored."))

    # Rejected schedule/copy metadata must not override authoritative dates or types.
    identity_sources = active or group
    dates = sorted({c.service_date for c in identity_sources})
    types = sorted({c.service_type for c in identity_sources})
    if len(dates) != 1:
        conflicts.append(_conflict(event_id, "service_date", dates, [c.claim_id for c in identity_sources], "Authoritative linked sources disagree on service date; temporal attribution is unresolved."))
    if len(types) != 1:
        conflicts.append(_conflict(event_id, "service_type", types, [c.claim_id for c in identity_sources], "Authoritative linked sources disagree on service type; attribution is unresolved."))

    presence_values = {c.patient_present for c in active if c.patient_present is not None}
    delivered_values = {c.delivered for c in active if c.delivered is not None}
    presence = next(iter(presence_values)) if len(presence_values) == 1 else None
    delivered = next(iter(delivered_values)) if len(delivered_values) == 1 else None
    for field, values in (("delivered", delivered_values),):
        if len(values) > 1:
            conflicts.append(_conflict(event_id, field, sorted(values), [c.claim_id for c in active], "Authoritative sources disagree; no timestamp-based arbitration."))

    # Break lists are sets per source, not a union of incompatible accounts.
    break_sets = {tuple(sorted((i.start, i.end) for i in c.breaks)) for c in active if c.breaks}
    if not break_sets:
        # Clinical group description still contributes breaks if the experiment picked a roster.
        break_sets = {tuple(sorted((i.start, i.end) for i in c.breaks)) for c in group
                      if c.breaks and c.evidence_kind == EvidenceKind.CLINICAL and c.signed}
    break_sets = break_sets or {()}
    if len(break_sets) > 1:
        conflicts.append(_conflict(event_id, "breaks", sorted(break_sets), [c.claim_id for c in group if c.breaks],
                                   "Sources describe incompatible nontherapeutic intervals; compute alternatives rather than unioning them."))
    break_claim_ids = [c.claim_id for c in group if c.breaks and c.signed and c.evidence_kind == EvidenceKind.CLINICAL]
    options = set()
    presence_values = set()
    # Each source supplies a candidate duration; competing reports are not added together.
    for source in active:
        corrections = []
        if policy != "latest_wins":
            # Apply only signed corrections that match this source's target and date.
            corrections = [r for r in applicable_relations if r.relation == "corrects" and r.signed
                           and (r.service_date is None or r.service_date == source.service_date)
                           and (r.target_document_ref is None or r.target_document_ref == document_refs.get(source.document_id))]
        for intervals, reported, present, correction_ids in _corrected_variants(source, corrections, event_id, decisions, conflicts, uncertainties):
            if present is not None:
                presence_values.add(present)
            if intervals:
                for breaks in sorted(break_sets):
                    value = treatment_minutes(intervals, [TimeInterval(start=a, end=b) for a, b in breaks])
                    options.add(value)
                    calculations.append(CalculationTrace(operation="interval_union_minus_nontherapeutic_time",
                                                         inputs={"actual_intervals": [i.model_dump() for i in intervals],
                                                                 "breaks": [{"start": a, "end": b} for a, b in breaks]},
                                                         output={"minutes": value}, claim_ids=[source.claim_id] + correction_ids + break_claim_ids,
                                                         event_ids=[event_id], assumptions=["Local same-day half-open intervals; overlapping intervals counted once."]))
            if reported is not None:
                options.add(reported)
                calculations.append(CalculationTrace(operation="reported_patient_treatment_duration", inputs={"reported_minutes": reported},
                                                     output={"minutes": reported}, claim_ids=[source.claim_id] + correction_ids, event_ids=[event_id]))

    presence = next(iter(presence_values)) if len(presence_values) == 1 else None
    if len(presence_values) > 1:
        conflicts.append(_conflict(event_id, "patient_present", sorted(presence_values), ids + [r.claim_id for r in applicable_relations],
                                   "Source-specific corrections leave incompatible patient-presence claims."))

    # Eligibility can be certain even when the event's exact duration is conflicted.
    therapy_possible = any(t in THERAPY_TYPES for t in types)
    therapy_certain = bool(types) and all(t in THERAPY_TYPES for t in types)
    prospective_only = not active and all(c.evidence_kind in {EvidenceKind.SCHEDULE, EvidenceKind.DRAFT, EvidenceKind.BILLING} for c in group)
    if prospective_only:
        countable = False
        lower, upper = 0, 0
        decisions.append(ReconciliationDecision(rule="no_delivered_care_assertion", claim_ids=ids,
                                               explanation="Scheduling, draft and billing evidence alone contributes no delivered therapy. This is an exclusion from accounting, not a finding that an undocumented clinical contact was absent."))
    elif not therapy_possible or presence is False or delivered is False:
        countable = False
        lower, upper = 0, 0
        decisions.append(ReconciliationDecision(rule="patient_present_therapy_only", claim_ids=ids,
                                               explanation="Exclude nontherapy, absent-patient contacts, cancelled appointments and no-shows from patient therapy counts/minutes."))
    elif presence is True and delivered is True and therapy_certain:
        countable = True
        # Missing time leaves an unknown upper bound, not a zero-minute finding.
        lower, upper = (min(options), max(options)) if options else (0, None)
    else:
        countable = None
        lower, upper = 0, max(options) if options else None
    if any(u.explanation == "Explicit correction creates an invalid interval." for u in uncertainties):
        lower, upper = 0, None
    if not encounter_refs and not appointment_refs:
        # Without identity, a positive report may duplicate another documented contact.
        countable = None if countable is True else countable
        lower = 0
        uncertainties.append(Uncertainty(subject_id=event_id, claim_ids=ids, explanation="No explicit encounter or appointment identity; duplicate clinical reporting cannot be ruled out.",
                                           needed_evidence="Encounter identifier or an explicit relationship linking the report"))
    if countable is not False and not options:
        uncertainties.append(Uncertainty(subject_id=event_id, claim_ids=ids, explanation="No explicit actual patient-contact interval or duration.",
                                           needed_evidence="Actual patient attendance/treatment interval or completed patient-treatment duration"))
    if countable is None:
        uncertainties.append(Uncertainty(subject_id=event_id, claim_ids=ids, explanation="Delivered patient therapy is not established consistently.",
                                           needed_evidence="Final patient-specific delivery/presence record"))
    if len(options) > 1 and countable is not False:
        conflicts.append(_conflict(event_id, "patient_treatment_minutes", sorted(options),
                                   [c.claim_id for c in active] + break_claim_ids,
                                   "Incompatible authoritative time/duration claims remain alternatives; neither is an explicit correction of the other."))
    if conflicts:
        state = State.CONFLICTED
    elif uncertainties:
        state = State.INSUFFICIENT
    else:
        state = State.RESOLVED
    return ServiceEvent(event_id=event_id, patient_id=group[0].patient_id,
                        encounter_ref=encounter_refs[0] if len(encounter_refs) == 1 else None,
                        appointment_refs=appointment_refs, service_date=dates[0] if len(dates) == 1 else None,
                        service_type=types[0] if len(types) == 1 else None, date_options=dates, type_options=types,
                        delivered=delivered, patient_present=presence, countable=countable, state=state,
                        minute_options=sorted(options), minutes_lower=lower, minutes_upper=upper,
                        claim_ids=sorted(set(ids + [r.claim_id for r in applicable_relations])),
                        decisions=decisions, conflicts=conflicts, uncertainties=uncertainties, calculations=calculations)


def reconcile(extractions: list[DocumentExtraction], policy: str = "explicit") -> PatientAbstraction:
    if not extractions:
        raise ValueError("No extracted patient evidence")
    if len({x.patient.patient_id for x in extractions}) != 1:
        raise ValueError("Reconciliation accepts one patient at a time")
    claims = [c for x in extractions for c in x.claims]
    relationships = [c for c in claims if isinstance(c, CorrectionRelationship)]
    refs = {x.document_id: x.declared_id for x in extractions}
    events = [_event(group, relationships, refs, policy) for group in _groups([c for c in claims if isinstance(c, ServiceClaim)])]
    events.sort(key=lambda e: (e.service_date or date.min, e.event_id))
    conflicts = [c for e in events for c in e.conflicts]
    uncertainties = [u for e in events for u in e.uncertainties]

    # Equivalent signed plan claims share one requirement while retaining every source.
    plan_groups = defaultdict(list)
    for c in claims:
        if isinstance(c, PlanClaim) and c.signed:
            key = (c.plan_ref, c.effective_start, c.effective_end, c.required_days, c.required_minutes, tuple(sorted(c.service_types)))
            plan_groups[key].append(c)
    plans = [TreatmentPlan(plan_id=stable_id(extractions[0].patient.patient_id, key), patient_id=group[0].patient_id,
                           effective_start=group[0].effective_start, effective_end=group[0].effective_end,
                           required_days=group[0].required_days, required_minutes=group[0].required_minutes,
                           service_types=group[0].service_types, claim_ids=[c.claim_id for c in group])
             for key, group in plan_groups.items()]
    plan_claims = {c.claim_id: c for c in claims if isinstance(c, PlanClaim)}
    # End an older plan only when an explicit signed relationship identifies its successor.
    for relationship in relationships:
        if relationship.relation != "supersedes_plan" or not relationship.signed:
            continue
        new_plans = [p for p in plans if any(plan_claims[i].document_id == relationship.document_id for i in p.claim_ids if i in plan_claims)]
        old_plans = [p for p in plans if any((relationship.target_plan_ref is not None and plan_claims[i].plan_ref == relationship.target_plan_ref)
                                           or (relationship.target_document_ref is not None and refs.get(plan_claims[i].document_id) == relationship.target_document_ref)
                                           for i in p.claim_ids if i in plan_claims)]
        if len(new_plans) == 1 and len(old_plans) == 1 and new_plans[0].effective_start > old_plans[0].effective_start:
            old_plans[0].effective_end = min(old_plans[0].effective_end or date.max, new_plans[0].effective_start - timedelta(days=1))
            old_plans[0].claim_ids.append(relationship.claim_id)
        else:
            uncertainties.append(Uncertainty(subject_id=relationship.claim_id, claim_ids=[relationship.claim_id],
                                               explanation="Plan supersession does not identify one older and one new plan.", needed_evidence="Unambiguous plan references/effective dates"))
    plans.sort(key=lambda p: (p.effective_start, p.plan_id))
    for i, p in enumerate(plans):
        for q in plans[i+1:]:
            if max(p.effective_start, q.effective_start) <= min(p.effective_end or date.max, q.effective_end or date.max):
                conflicts.append(_conflict(p.plan_id, "applicable_plan", [p.plan_id, q.plan_id], p.claim_ids + q.claim_ids,
                                           "Signed plan intervals overlap; no explicit relationship establishes precedence."))

    # Explicit form reference links copied summaries to their original completion date.
    assessment_claims = [c for c in claims if isinstance(c, AssessmentClaim)]
    form_dates = defaultdict(set)
    for c in assessment_claims:
        if c.form_ref:
            form_dates[(c.instrument.casefold(), c.form_ref, c.experiencer.casefold())].add(c.assessment_date)
    by_identity = defaultdict(list)
    for c in assessment_claims:
        key = (c.instrument.casefold(), c.form_ref or str(c.assessment_date), c.experiencer.casefold())
        if not c.form_ref:
            matching = [k for k, dates in form_dates.items() if k[0] == key[0] and k[2] == key[2] and c.assessment_date in dates]
            if len(matching) == 1:
                key = matching[0]
        by_identity[key].append(c)
    assessments = []
    for key, group in by_identity.items():
        scores = sorted({c.score for c in group})
        dates = sorted({c.assessment_date for c in group})
        aid = stable_id(extractions[0].patient.patient_id, key)
        # A shared form ID does not resolve incompatible scores or completion dates.
        state = State.CONFLICTED if len(scores) > 1 or len(dates) > 1 else State.RESOLVED
        if state == State.CONFLICTED:
            conflicts.append(_conflict(aid, "assessment", [f"{c.assessment_date}:{c.score}" for c in group], [c.claim_id for c in group],
                                       "One assessment identity has incompatible score/completion-date claims."))
        assessments.append(Assessment(assessment_id=aid, patient_id=group[0].patient_id, instrument=group[0].instrument,
                                      assessment_date=dates[0] if len(dates) == 1 else None, date_options=dates,
                                      form_ref=next((c.form_ref for c in group if c.form_ref), None),
                                      experiencer=group[0].experiencer, reporters=sorted({c.reporter for c in group}),
                                      score_options=scores, state=state, claim_ids=[c.claim_id for c in group],
                                      decisions=[ReconciliationDecision(rule="assessment_identity", claim_ids=[c.claim_id for c in group],
                                                                       explanation="Group by explicit form identity, or patient/instrument/completion date when form ID is absent; receipt/review is not a new questionnaire.")]))
    assessments.sort(key=lambda a: (a.assessment_date or date.min, a.instrument, a.assessment_id))
    return PatientAbstraction(patient=extractions[0].patient, source_claims=claims, events=events, plans=plans,
                              assessments=assessments, observations=[c for c in claims if isinstance(c, ClinicalObservation)],
                              relationships=relationships, conflicts=conflicts, uncertainties=uncertainties)
