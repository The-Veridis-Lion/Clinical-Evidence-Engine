"""Plan applicability and compliance over reconciled utilization."""
from __future__ import annotations
from datetime import date, timedelta
from itertools import product
from .domain import CalculationTrace, THERAPY_TYPES
from .utilization import monday, utilization


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
        elif (totals["therapy_days"]["upper"] is not None and totals["therapy_days"]["upper"] < plan.required_days) or (totals["minutes"]["upper"] is not None and totals["minutes"]["upper"] < plan.required_minutes):
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
    if (totals["therapy_days"]["upper"] is not None and totals["therapy_days"]["upper"] < plan.required_days) or (totals["minutes"]["upper"] is not None and totals["minutes"]["upper"] < plan.required_minutes):
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
