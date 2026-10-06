"""Reusable deterministic queries over the abstraction, never over search results."""
from __future__ import annotations
from datetime import date, timedelta
from itertools import product
from typing import Literal
from pydantic import Field, model_validator
from .domain import CalculationTrace, Model, PatientAbstraction, ServiceEvent, ServiceType, THERAPY_TYPES


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
    if not dates and (spec.start is None or spec.end is None):
        raise ValueError("No episode dates established; supply an explicit review period")
    return spec.start or min(dates), spec.end or max(dates)


def _contribution(event: ServiceEvent, start, end, service_types):
    possible_dates = [d for d in event.date_options if start <= d <= end]
    possible_type = any(t in service_types for t in event.type_options)
    if not possible_dates or not possible_type or event.countable is False:
        return None
    certain = all(start <= d <= end for d in event.date_options) and all(t in service_types for t in event.type_options)
    definite = certain and event.countable is True
    return {"event_id": event.event_id, "encounter_ref": event.encounter_ref,
            "service_date": event.service_date, "date_options": possible_dates,
            "service_type": event.service_type, "type_options": event.type_options,
            "sessions": bounded(int(definite), 1),
            "minutes": bounded(event.minutes_lower if definite else 0, event.minutes_upper),
            "minute_options": event.minute_options if definite else sorted({0, *event.minute_options}),
            "definite": definite, "state": event.state, "claim_ids": event.claim_ids,
            "calculations": [c.model_dump() for c in event.calculations],
            "decisions": [d.model_dump() for d in event.decisions]}


def utilization(abstraction: PatientAbstraction, start: date, end: date, service_types=None) -> dict:
    service_types = set(service_types or THERAPY_TYPES)
    contributions = [c for e in abstraction.events if (c := _contribution(e, start, end, service_types)) is not None]
    sessions = bounded(sum(c["sessions"]["lower"] for c in contributions), sum(c["sessions"]["upper"] for c in contributions))
    low = sum(c["minutes"]["lower"] for c in contributions)
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
    options = {0}
    for c in contributions:
        if c["minutes"]["upper"] is None or not c["minute_options"]:
            options = None
            break
        options = {a + b for a in options for b in c["minute_options"]}
        if len(options) > 4096:
            options = None
            break
    included = {c["event_id"] for c in contributions}
    excluded = [e for e in abstraction.events if e.event_id not in included and any(start <= d <= end for d in e.date_options)]
    claim_ids = sorted({i for c in contributions for i in c["claim_ids"]})
    totals = {"sessions": sessions, "therapy_days": days, "minutes": bounded(low, high),
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
    # One explicit Monday-Sunday goal applies to the episode's touched weeks, including
    # its final Friday. No proportional reduction for a short review period is assumed.
    return plans[0], plans, None


def compliance(abstraction, start, end):
    rows = []
    week = monday(start)
    while week <= end:
        plan, candidates, ambiguity = _plan_for_week(abstraction, week, week, week + timedelta(days=6))
        eligible = plan.service_types if plan else sorted({t for p in candidates for t in p.service_types} or THERAPY_TYPES)
        actual = utilization(abstraction, max(week, plan.effective_start) if plan else week,
                             min(week + timedelta(days=6), plan.effective_end or date.max) if plan else week + timedelta(days=6), eligible)
        totals = actual["totals"]
        if plan is None:
            status = "cannot_determine"
        elif totals["therapy_days"]["lower"] >= plan.required_days and totals["minutes"]["lower"] >= plan.required_minutes:
            status = "met"
        elif totals["therapy_days"]["upper"] < plan.required_days or (totals["minutes"]["upper"] is not None and totals["minutes"]["upper"] < plan.required_minutes):
            status = "not_met"
        else:
            status = "cannot_determine"
        event_ids = {c["event_id"] for c in actual["contributions"]}
        relevant_conflicts = [c.model_dump() for c in abstraction.conflicts if c.subject_id in event_ids or c.field == "applicable_plan" and any(p.plan_id == c.subject_id for p in candidates)]
        requirement = {"days": plan.required_days, "minutes": plan.required_minutes, "service_types": plan.service_types} if plan else None
        claim_ids = sorted({i for p in candidates for i in p.claim_ids} | set(actual["calculation"]["claim_ids"]))
        trace = CalculationTrace(operation="compare_days_and_minutes_with_applicable_plan",
                                 inputs={"requirement": requirement, "actual": totals, "plan_ids": [p.plan_id for p in candidates]},
                                 output={"status": status}, claim_ids=claim_ids, event_ids=sorted(event_ids),
                                 assumptions=["Both day and minute thresholds must be met.", "Apply comparisons to all supported duration candidates."])
        rows.append({"week_start": week, "week_end": week + timedelta(days=6), "status": status,
                     "requirement": requirement, "candidate_plans": [p.model_dump() for p in candidates], "actual": actual,
                     "ambiguity": ambiguity, "conflicts": relevant_conflicts, "calculation": trace.model_dump()})
        week += timedelta(days=7)
    return rows


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
        result["by_service_type"] = {str(t): utilization(abstraction, start, end, [t])["totals"] for t in spec.service_types}
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
            changes = sorted({p.effective_start for p in abstraction.plans if start < p.effective_start <= end})
            if len(changes) != 1:
                result = {"status": "insufficient_evidence", "explanation": "No unique documented plan change in this period; specify an explicit comparison date if desired."}
                return {"patient": abstraction.patient.model_dump(), "query": spec.model_dump(), "result": result}
            change = changes[0]
        if not start < change <= end:
            raise ValueError("Comparison date must divide the review period into two nonempty periods")
        before, after = utilization(abstraction, start, change - timedelta(days=1), spec.service_types), utilization(abstraction, change, end, spec.service_types)
        differences = {}
        for field in ("sessions", "therapy_days", "minutes", "hours"):
            a, b = after["totals"][field], before["totals"][field]
            differences[field] = bounded(a["lower"] - b["upper"] if b["upper"] is not None else None,
                                         a["upper"] - b["lower"] if a["upper"] is not None else None)
        result = {"change_date": change, "before": before, "after": after, "difference_after_minus_before": differences,
                  "by_service_type": {str(t): {"before": utilization(abstraction, start, change - timedelta(days=1), [t])["totals"],
                                               "after": utilization(abstraction, change, end, [t])["totals"]} for t in spec.service_types},
                  "assumption": "Absolute totals over the stated periods, not a causal or exposure-adjusted effect."}
    elif spec.family in {"assessments", "progress"}:
        assessments = [a for a in abstraction.assessments if any(start <= d <= end for d in a.date_options)]
        result = {"assessments": [a.model_dump() for a in assessments], "score_changes": []}
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
            result["interpretation_limits"] = ["Symptom score change does not establish remission, restored occupational function, or a causal treatment effect.",
                                               "Reporter/experiencer, negation and planned versus completed actions remain explicit in source claims."]
    elif spec.family == "cohort":
        actual = utilization(abstraction, start, end, spec.service_types)
        thresholds = {"sessions": spec.min_sessions, "minutes": spec.min_minutes}
        met = all(v is None or actual["totals"][k]["lower"] >= v for k, v in thresholds.items())
        excluded = any(v is not None and actual["totals"][k]["upper"] is not None and actual["totals"][k]["upper"] < v for k, v in thresholds.items())
        result = {"included": met, "conditional_inclusion": not met and not excluded, "actual": actual}
    else:
        raise ValueError("Unsupported query family")
    return {"patient": abstraction.patient.model_dump(), "query": spec.model_dump(), "result": result}


def query_collection(abstractions: list[PatientAbstraction], spec: QuerySpec) -> dict:
    results = [query_patient(a, spec) for a in abstractions if spec.patient_id is None or a.patient.patient_id == spec.patient_id]
    if not results:
        raise ValueError("No patients match the query")
    answer = {"query": spec.model_dump(), "patients": results}
    if spec.family in {"cohort", "consecutive_under_target"}:
        answer["included_patient_ids"] = [r["patient"]["patient_id"] for r in results if r["result"]["included"]]
        answer["conditional_patient_ids"] = [r["patient"]["patient_id"] for r in results if r["result"]["conditional_inclusion"]]
    return answer


def attach_evidence(answer: dict, abstractions: list[PatientAbstraction], documents) -> dict:
    identifiers = set()
    def visit(value):
        if isinstance(value, dict):
            identifiers.update(value.get("claim_ids", []))
            if "claim_id" in value:
                identifiers.add(value["claim_id"])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(answer)
    docs = {d.document_id: d for d in documents}
    claims = {c.claim_id: c for a in abstractions for c in a.source_claims}
    if not identifiers <= set(claims):
        raise ValueError("Audit result references nonexistent source claims")
    answer["evidence"] = {identifier: {"kind": claims[identifier].kind, "statement": claims[identifier].statement,
                                       "document_id": claims[identifier].document_id,
                                       "declared_id": docs[claims[identifier].document_id].declared_id,
                                       "source_names": docs[claims[identifier].document_id].source_names,
                                       "passages": [p.model_dump() for p in claims[identifier].passages]}
                           for identifier in sorted(identifiers)}
    answer["document_coverage"] = [{"document_id": d.document_id, "declared_id": d.declared_id, "status": d.status,
                                    "source_names": d.source_names} for d in documents]
    return answer
