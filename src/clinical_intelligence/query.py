"""Reusable deterministic queries over the abstraction, never over search results."""
from __future__ import annotations
from datetime import date, timedelta
from itertools import product
from typing import Literal
from pydantic import Field, model_validator
from .domain import CalculationTrace, Model, PatientAbstraction, ServiceEvent, ServiceType, THERAPY_TYPES
from .evidence import quantitative_evidence
from .provenance import add_runtime_provenance


class QuerySpec(Model):
    family: Literal["utilization", "weekly_utilization", "compliance", "encounters", "compare_periods",
                    "consecutive_under_target", "assessments", "progress", "cohort"]
    patient_id: str | None = None
    start: date | None = None
    end: date | None = None
    service_types: list[ServiceType] = Field(default_factory=lambda: sorted(THERAPY_TYPES))
    dates: list[date] = Field(default_factory=list)
    change_date: date | None = None
    consecutive_weeks: int = Field(default=2, ge=2)
    min_sessions: int | None = Field(default=None, ge=0)
    min_minutes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def period_valid(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("Query start must not follow end")
        return self


def bounded(lower, upper):
    return {"lower": lower, "upper": upper, "value": lower if upper == lower else None}


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _period(abstraction, spec):
    dates = [d for e in abstraction.events for d in e.date_options]
    dates += [d for a in abstraction.assessments for d in a.date_options]
    dates += [p.effective_start for p in abstraction.plans]
    dates += [p.effective_end for p in abstraction.plans if p.effective_end]
    dates += [o.observation_date for o in abstraction.observations]
    dates += [a.report_date for a in abstraction.functional_actions]
    if not dates and (spec.start is None or spec.end is None):
        raise ValueError("No episode dates established; supply an explicit review period")
    return spec.start or min(dates), spec.end or max(dates)


def _service_accounting(event: ServiceEvent):
    """Use psychotherapy eligibility only for psychotherapy; other care needs delivery/presence."""
    if set(event.type_options) <= THERAPY_TYPES:
        return event.countable, event.minutes_lower, event.minutes_upper
    # The persisted countable flag excludes all nontherapy from plan accounting.
    # Explicit service queries instead use already-reconciled patient contact.
    if (event.patient_present is False or event.delivered is False
            or any(d.rule == "no_delivered_care_assertion" for d in event.decisions)):
        return False, 0, 0
    definite = (event.patient_present is True and event.delivered is True
                and bool(event.encounter_ref or event.appointment_refs))
    countable = True if definite else None
    lower = min(event.minute_options) if definite and event.minute_options else 0
    upper = max(event.minute_options) if event.minute_options else None
    # An invalid time correction affects duration, not an established service count.
    if any(u.explanation == "Explicit correction creates an invalid interval." for u in event.uncertainties):
        lower, upper = 0, None
    return countable, lower, upper


def _contribution(event: ServiceEvent, start, end, service_types):
    possible_dates = [d for d in event.date_options if start <= d <= end]
    possible_type = any(t in service_types for t in event.type_options)
    countable, lower, upper = _service_accounting(event)
    if not possible_dates or not possible_type or countable is False:
        return None
    # A guaranteed contribution must be eligible under every supported date/type choice.
    certain = all(start <= d <= end for d in event.date_options) and all(t in service_types for t in event.type_options)
    definite = certain and countable is True
    return {"event_id": event.event_id, "encounter_ref": event.encounter_ref,
            "service_date": event.service_date, "date_options": possible_dates,
            "service_type": event.service_type, "type_options": event.type_options,
            "sessions": bounded(int(definite), 1),
            "minutes": bounded(lower if definite else 0, upper),
            "minute_options": event.minute_options if definite else sorted({0, *event.minute_options}),
            "definite": definite, "state": event.state, "claim_ids": event.claim_ids,
            "calculations": [c.model_dump() for c in event.calculations],
            "decisions": [d.model_dump() for d in event.decisions]}


def utilization(abstraction: PatientAbstraction, start: date, end: date, service_types=None) -> dict:
    # None means psychotherapy; explicit types (including an empty set) are respected.
    service_types = set(THERAPY_TYPES if service_types is None else service_types)
    contributions = [c for e in abstraction.events if (c := _contribution(e, start, end, service_types)) is not None]
    sessions = bounded(sum(c["sessions"]["lower"] for c in contributions), sum(c["sessions"]["upper"] for c in contributions))
    low = sum(c["minutes"]["lower"] for c in contributions)
    # One unknown duration leaves the total upper bound unknown too.
    high = None if any(c["minutes"]["upper"] is None for c in contributions) else sum(c["minutes"]["upper"] for c in contributions)
    # Date alternatives are mutually exclusive per contact. Weekly sets have at most
    # 2**7 states; preserve them rather than counting all possible dates as delivered.
    day_sets = {frozenset()}
    for c in contributions:
        updated = {days | {d} for days in day_sets for d in c["date_options"]}
        if c["sessions"]["lower"] == 0:
            updated |= day_sets
        day_sets = updated
    days = bounded(min(map(len, day_sets)), max(map(len, day_sets)))
    # Keep discrete supported totals as well as bounds; intermediate values may be impossible.
    options = {0}
    for c in contributions:
        if c["minutes"]["upper"] is None or not c["minute_options"]:
            options = None
            break
        options = {a + b for a in options for b in c["minute_options"]}
        if len(options) > 4096:
            # Bound output size without discarding the conservative numerical bounds.
            options = None
            break
    included = {c["event_id"] for c in contributions}
    excluded = [e for e in abstraction.events if e.event_id not in included and any(start <= d <= end for d in e.date_options)]
    claim_ids = sorted({i for c in contributions for i in c["claim_ids"]})
    totals = {"sessions": sessions, "distinct_service_days": days,
              # Compatibility alias; plan comparisons explicitly use qualifying therapy days.
              "therapy_days": days, "minutes": bounded(low, high),
              "hours": bounded(low / 60, high / 60 if high is not None else None),
              "minute_alternatives": sorted(options) if options is not None else None}
    trace = CalculationTrace(operation="sum_events_and_count_distinct_local_dates",
                             inputs={"start": str(start), "end": str(end), "service_types": sorted(service_types),
                                     "contributions": [{k: c[k] for k in ("event_id", "sessions", "minutes", "date_options")} for c in contributions]},
                             output=totals, claim_ids=claim_ids, event_ids=sorted(included),
                             assumptions=["Count encounters, not documents/clinicians/platform calls.",
                                          "Bounds express supported alternatives, not averages or probabilities.",
                                          "No undocumented therapy is imputed for missing/cancelled appointments."])
    return {"start": start, "end": end, "totals": totals, "contributions": contributions,
            "excluded_events": [{"event_id": e.event_id, "encounter_ref": e.encounter_ref,
                                 "service_type": e.service_type, "claim_ids": e.claim_ids,
                                 "decisions": [d.model_dump() for d in e.decisions]} for e in excluded],
            "calculation": trace.model_dump()}


def weekly_utilization(abstraction, start, end, service_types=None):
    rows = []
    week = monday(start)
    while week <= end:
        # Utilization respects the requested range; labels still identify full calendar weeks.
        result = utilization(abstraction, max(start, week), min(end, week + timedelta(days=6)), service_types)
        result.update(week_start=week, week_end=week + timedelta(days=6))
        rows.append(result)
        week += timedelta(days=7)
    return rows


def _plan_for_week(abstraction, week, review_start, review_end):
    begin, finish = max(week, review_start), min(week + timedelta(days=6), review_end)
    plans = [p for p in abstraction.plans if p.effective_start <= finish and (p.effective_end or date.max) >= begin]
    if not plans:
        return None, [], "No signed quantitative treatment plan establishes a requirement for this period."
    requirements = {(p.required_days, p.required_minutes, tuple(sorted(p.service_types))) for p in plans}
    overlapping = any(max(p.effective_start, q.effective_start) <= min(p.effective_end or date.max, q.effective_end or date.max)
                      for i, p in enumerate(plans) for q in plans[i+1:])
    if overlapping:
        return None, plans, "Signed plans overlap without settled precedence; clarification of applicable requirements is needed."
    if len(requirements) > 1 or any(week < p.effective_start <= week + timedelta(days=6) for p in plans):
        return None, plans, "A plan begins/changes during the week; the record does not specify how the weekly goal applies. No prorating is invented."
    # Weekly goals apply to touched weeks; no partial-week prorating is assumed.
    return plans[0], plans, None


def compliance(abstraction, start, end):
    rows = []
    week = monday(start)
    while week <= end:
        # A narrow query window must not hide care from the week being assessed.
        plan, candidates, ambiguity = _plan_for_week(abstraction, week, week, week + timedelta(days=6))
        eligible = plan.service_types if plan else sorted({t for p in candidates for t in p.service_types} or THERAPY_TYPES)
        actual = utilization(abstraction, max(week, plan.effective_start) if plan else week,
                             min(week + timedelta(days=6), plan.effective_end or date.max) if plan else week + timedelta(days=6), eligible)
        totals = actual["totals"]
        candidate_comparisons = []
        if plan is None:
            status = "cannot_determine"
            if ambiguity and ambiguity.startswith("Signed plans overlap") and all(p.effective_start <= week for p in candidates):
                # When precedence is disputed but full-week application is clear, a
                # common consequence across all candidate plans is still established.
                for candidate in candidates:
                    care = utilization(abstraction, week, min(week + timedelta(days=6), candidate.effective_end or date.max), candidate.service_types)
                    candidate_comparisons.append({"plan_id": candidate.plan_id, "status": threshold_status(care["totals"], candidate),
                                                  "actual": care, "requirement": {"days": candidate.required_days, "minutes": candidate.required_minutes,
                                                                                   "service_types": candidate.service_types}})
                outcomes = {c["status"] for c in candidate_comparisons}
                if len(outcomes) == 1:
                    status = next(iter(outcomes))
        elif totals["therapy_days"]["lower"] >= plan.required_days and totals["minutes"]["lower"] >= plan.required_minutes:
            # Both lower bounds meet the goals, so every supported candidate passes.
            status = "met"
        elif totals["therapy_days"]["upper"] < plan.required_days or (totals["minutes"]["upper"] is not None and totals["minutes"]["upper"] < plan.required_minutes):
            # Even the best supported value misses a goal, so the outcome is definite.
            status = "not_met"
        else:
            status = "cannot_determine"
        event_ids = {c["event_id"] for c in actual["contributions"]}
        relevant_conflicts = [c.model_dump() for c in abstraction.conflicts if c.subject_id in event_ids or c.field == "applicable_plan" and any(p.plan_id == c.subject_id for p in candidates)]
        requirement = {"days": plan.required_days, "minutes": plan.required_minutes, "service_types": plan.service_types} if plan else None
        claim_ids = sorted({i for p in candidates for i in p.claim_ids} | set(actual["calculation"]["claim_ids"]))
        trace = CalculationTrace(operation="compare_days_and_minutes_with_applicable_plan",
                                 inputs={"requirement": requirement, "actual": totals, "plan_ids": [p.plan_id for p in candidates],
                                         "candidate_comparisons": candidate_comparisons},
                                 output={"status": status}, claim_ids=claim_ids, event_ids=sorted(event_ids),
                                 assumptions=["Both day and minute thresholds must be met.", "Apply comparisons to all supported duration candidates."])
        rows.append({"week_start": week, "week_end": week + timedelta(days=6), "status": status,
                     "requirement": requirement, "candidate_plans": [p.model_dump() for p in candidates], "actual": actual,
                     "candidate_comparisons": candidate_comparisons,
                     "ambiguity": ambiguity, "conflicts": relevant_conflicts, "calculation": trace.model_dump()})
        week += timedelta(days=7)
    return rows


def threshold_status(totals, plan):
    if totals["therapy_days"]["lower"] >= plan.required_days and totals["minutes"]["lower"] >= plan.required_minutes:
        return "met"
    if totals["therapy_days"]["upper"] < plan.required_days or (totals["minutes"]["upper"] is not None and totals["minutes"]["upper"] < plan.required_minutes):
        return "not_met"
    return "cannot_determine"


def consecutive_under_target(abstraction, start, end, length=2):
    weeks = compliance(abstraction, start, end)
    definite, conditional = [], []
    for i in range(len(weeks) - length + 1):
        window = weeks[i:i+length]
        if all(w["status"] == "not_met" for w in window):
            definite.append([w["week_start"] for w in window])
        elif all(w["status"] in {"not_met", "cannot_determine"} for w in window):
            # A single contact cannot occur in both competing weeks. Check compatible
            # date assignments before asserting a possible consecutive-week window.
            ambiguous = [e for e in abstraction.events if len(e.date_options) > 1 and e.countable is not False]
            possible = not ambiguous
            for assignment in product(*(e.date_options for e in ambiguous)) if ambiguous else []:
                scenario = abstraction.model_copy(deep=True)
                chosen = dict(zip((e.event_id for e in ambiguous), assignment))
                for event in scenario.events:
                    if event.event_id in chosen:
                        event.service_date = chosen[event.event_id]
                        event.date_options = [chosen[event.event_id]]
                candidate = compliance(scenario, window[0]["week_start"], window[-1]["week_end"])
                if all(w["status"] in {"not_met", "cannot_determine"} for w in candidate):
                    possible = True
                    break
            if possible:
                conditional.append([w["week_start"] for w in window])
    return {"included": bool(definite), "conditional_inclusion": not definite and bool(conditional),
            "definite_windows": definite, "conditional_windows": conditional, "weeks": weeks}


def query_patient(abstraction: PatientAbstraction, spec: QuerySpec) -> dict:
    start, end = _period(abstraction, spec)
    if spec.family == "utilization":
        result = utilization(abstraction, start, end, spec.service_types)
        details = {str(t): utilization(abstraction, start, end, [t]) for t in spec.service_types}
        result["by_service_type"] = {t: row["totals"] for t, row in details.items()}
        result["by_service_type_details"] = details
    elif spec.family == "weekly_utilization":
        result = {"overall": utilization(abstraction, start, end, spec.service_types),
                  "weeks": weekly_utilization(abstraction, start, end, spec.service_types)}
    elif spec.family == "compliance":
        result = {"weeks": compliance(abstraction, start, end)}
    elif spec.family == "encounters":
        dates = spec.dates or sorted({d for e in abstraction.events for d in e.date_options if start <= d <= end})
        result = {"dates": [{"date": d, **utilization(abstraction, d, d, spec.service_types)} for d in dates]}
    elif spec.family == "consecutive_under_target":
        result = consecutive_under_target(abstraction, start, end, spec.consecutive_weeks)
    elif spec.family == "compare_periods":
        change = spec.change_date
        if change is None:
            # Infer a boundary only from one documented plan change, never from question text.
            changes = sorted({p.effective_start for p in abstraction.plans if start < p.effective_start <= end})
            if len(changes) != 1:
                result = {"status": "insufficient_evidence", "explanation": "No unique documented plan change in this period; specify an explicit comparison date if desired."}
                return attach_evidence({"patient": abstraction.patient.model_dump(), "query": spec.model_dump(), "result": result}, [abstraction])
            change = changes[0]
        if not start < change <= end:
            raise ValueError("Comparison date must divide the review period into two nonempty periods")
        before, after = utilization(abstraction, start, change - timedelta(days=1), spec.service_types), utilization(abstraction, change, end, spec.service_types)
        differences = {}
        for field in ("sessions", "distinct_service_days", "therapy_days", "minutes", "hours"):
            # Subtract opposite bounds to retain conservative difference estimates.
            a, b = after["totals"][field], before["totals"][field]
            differences[field] = bounded(a["lower"] - b["upper"] if b["upper"] is not None else None,
                                         a["upper"] - b["lower"] if a["upper"] is not None else None)
        trace = CalculationTrace(operation="subtract_before_from_after",
                                 inputs={"before": before["totals"], "after": after["totals"], "change_date": str(change)},
                                 output=differences,
                                 claim_ids=sorted(set(before["calculation"]["claim_ids"] + after["calculation"]["claim_ids"])),
                                 event_ids=sorted(set(before["calculation"]["event_ids"] + after["calculation"]["event_ids"])),
                                 assumptions=["Intervals are disjoint; bounds are conservative when an event has competing dates across the comparison boundary."])
        result = {"change_date": change, "before": before, "after": after, "difference_after_minus_before": differences,
                  "calculation": trace.model_dump(),
                  "by_service_type": {str(t): {"before": utilization(abstraction, start, change - timedelta(days=1), [t])["totals"],
                                               "after": utilization(abstraction, change, end, [t])["totals"]} for t in spec.service_types},
                  "assumption": "Absolute totals over the stated periods, not a causal or exposure-adjusted effect."}
    elif spec.family in {"assessments", "progress"}:
        assessments = [a for a in abstraction.assessments if any(start <= d <= end for d in a.date_options)]
        result = {"assessments": [a.model_dump() for a in assessments], "score_changes": []}
        # Compare the same instrument and experiencer; uncertain dates cannot order a trend.
        histories = sorted({(a.instrument.casefold(), a.experiencer.casefold()) for a in assessments})
        for instrument, experiencer in histories:
            sequence = [a for a in assessments if a.instrument.casefold() == instrument and a.experiencer.casefold() == experiencer and a.assessment_date is not None]
            for a, b in zip(sequence, sequence[1:]):
                differences = sorted({y - x for x in a.score_options for y in b.score_options})
                result["score_changes"].append(CalculationTrace(operation="assessment_score_change", inputs={"from_date": str(a.assessment_date), "to_date": str(b.assessment_date),
                                                                                                             "from_scores": a.score_options, "to_scores": b.score_options},
                                                                output={"instrument": instrument, "difference_options": differences}, claim_ids=a.claim_ids + b.claim_ids).model_dump())
        if spec.family == "progress":
            result["observations"] = [o.model_dump() for o in sorted(abstraction.observations, key=lambda o: (o.observation_date, o.claim_id)) if start <= o.observation_date <= end]
            result["functional_actions"] = [a.model_dump() for a in sorted(abstraction.functional_actions, key=lambda a: (a.report_date, a.claim_id)) if start <= a.report_date <= end]
            result["interpretation_limits"] = ["Symptom score change does not establish remission, restored occupational function, or a causal treatment effect.",
                                               "Reporter/experiencer, negation and planned versus completed actions remain explicit in source claims."]
    elif spec.family == "cohort":
        actual = utilization(abstraction, start, end, spec.service_types)
        thresholds = {"sessions": spec.min_sessions, "minutes": spec.min_minutes}
        # Definite and conditional membership use the same bounds as patient queries.
        met = all(v is None or actual["totals"][k]["lower"] >= v for k, v in thresholds.items())
        excluded = any(v is not None and actual["totals"][k]["upper"] is not None and actual["totals"][k]["upper"] < v for k, v in thresholds.items())
        result = {"included": met, "conditional_inclusion": not met and not excluded, "actual": actual,
                  # User-supplied query thresholds are distinct from clinical source facts.
                  "comparison": {"thresholds": thresholds, "threshold_source": "QuerySpec",
                                 "operation": "all requested lower bounds >= thresholds; otherwise check upper bounds"}}
    else:
        raise ValueError("Unsupported query family")
    # Normal queries include evidence and runtime traces automatically.
    return attach_evidence({"patient": abstraction.patient.model_dump(), "query": spec.model_dump(), "result": result}, [abstraction])


def query_collection(abstractions: list[PatientAbstraction], spec: QuerySpec) -> dict:
    results = [query_patient(a, spec) for a in abstractions if spec.patient_id is None or a.patient.patient_id == spec.patient_id]
    if not results:
        raise ValueError("No patients match the query")
    answer = {"query": spec.model_dump(), "patients": results}
    if spec.family in {"cohort", "consecutive_under_target"}:
        answer["included_patient_ids"] = [r["patient"]["patient_id"] for r in results if r["result"]["included"]]
        answer["conditional_patient_ids"] = [r["patient"]["patient_id"] for r in results if r["result"]["conditional_inclusion"]]
    return attach_evidence(answer, abstractions)


def attach_evidence(answer: dict, abstractions: list[PatientAbstraction], documents=None) -> dict:
    # Resolve persisted references at runtime; no semantic citation search occurs.
    identifiers = set()
    def visit(value):
        if isinstance(value, dict):
            identifiers.update(value.get("claim_ids", []))
            if "claim_id" in value:
                identifiers.add(value["claim_id"])
            for key, item in value.items():
                if key not in {"evidence", "provenance"}:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(answer)
    docs = {d.document_id: d for d in documents or []}
    claims = {c.claim_id: c for a in abstractions for c in a.source_claims}
    document_claims = {}
    for claim in claims.values():
        document_claims.setdefault(claim.document_id, []).append(claim)
    if not identifiers <= set(claims):
        raise ValueError("Audit result references nonexistent source claims")
    evidence = {}
    for identifier in sorted(identifiers):
        claim = claims[identifier]
        document = docs.get(claim.document_id)
        evidence[identifier] = {
            "kind": claim.kind, "statement": claim.statement, "document_id": claim.document_id,
            "declared_id": document.declared_id if document else None,
            "source_names": document.source_names if document else [],
            "passages": [p.model_dump() for p in claim.passages],
            "quantitative_fields": quantitative_evidence(claim, document, document_claims[claim.document_id]),
            # Unknown registry availability differs from an explicitly missing source.
            "retained_source_available": document is not None if documents is not None else None,
        }
    answer["evidence"] = evidence
    answer["document_coverage"] = [{"document_id": d.document_id, "declared_id": d.declared_id,
                                    "status": d.status, "source_names": d.source_names} for d in docs.values()]
    return add_runtime_provenance(answer, abstractions)
