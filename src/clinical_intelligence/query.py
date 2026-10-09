"""Query specifications, request dispatch, and public result assembly."""
from __future__ import annotations
from datetime import date, timedelta
from typing import Literal
from pydantic import Field, model_validator
from .domain import CalculationTrace, Model, PatientAbstraction, ServiceType, THERAPY_TYPES
from .utilization import bounded, utilization, weekly_utilization
from .plan_queries import compliance, consecutive_under_target
from .provenance import attach_evidence


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


def _period(abstraction, spec):
    dates = [d for e in abstraction.events for d in e.date_options]
    dates += [d for a in abstraction.assessments for d in a.date_options]
    dates += [p.effective_start for p in abstraction.plans]
    dates += [p.effective_end for p in abstraction.plans if p.effective_end]
    dates += [o.observation_date for o in abstraction.observations if o.observation_date]
    dates += [a.report_date for a in abstraction.functional_actions]
    dates += [r.service_date for r in abstraction.relationships if r.service_date]
    if not dates and (spec.start is None or spec.end is None):
        raise ValueError("No episode dates established; supply an explicit review period")
    return spec.start or min(dates), spec.end or max(dates)


def _compare_periods(abstraction, spec, start, end):
    change = spec.change_date
    if change is None:
        # Infer a boundary only from one documented plan change, never from question text.
        changes = sorted({p.effective_start for p in abstraction.plans if start < p.effective_start <= end})
        if len(changes) != 1:
            result = {"status": "insufficient_evidence", "explanation": "No unique documented plan change in this period; specify an explicit comparison date if desired."}
            return result
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
    return result


def _clinical_progress(abstraction, spec, start, end):
    assessments = [a for a in abstraction.assessments if any(start <= d <= end for d in a.date_options)]
    result = {"assessments": [a.model_dump() for a in assessments],
              "undated_assessments": [a.model_dump() for a in abstraction.assessments if not a.date_options],
              "score_changes": [],
              "historical_assessment_mentions": [a.model_dump() for a in abstraction.historical_assessments]}
    # Compare the same instrument and experiencer; uncertain dates cannot order a trend.
    histories = sorted({(a.instrument.casefold(), a.experiencer.casefold()) for a in assessments if a.instrument is not None and a.experiencer != 'not specified'})
    for instrument, experiencer in histories:
        sequence = [a for a in assessments if a.instrument is not None and a.instrument.casefold() == instrument and a.experiencer.casefold() == experiencer and a.assessment_date is not None]
        for a, b in zip(sequence, sequence[1:]):
            if not a.score_options or not b.score_options:
                continue
            differences = sorted({y - x for x in a.score_options for y in b.score_options})
            result["score_changes"].append(CalculationTrace(operation="assessment_score_change", inputs={"from_date": str(a.assessment_date), "to_date": str(b.assessment_date),
                                                                                                         "from_scores": a.score_options, "to_scores": b.score_options},
                                                            output={"instrument": instrument, "difference_options": differences}, claim_ids=a.claim_ids + b.claim_ids).model_dump())
    if spec.family == "progress":
        result["observations"] = [o.model_dump() for o in sorted((o for o in abstraction.observations if o.observation_date), key=lambda o: (o.observation_date, o.claim_id)) if start <= o.observation_date <= end]
        result["undated_observations"] = [o.model_dump() for o in abstraction.observations if o.observation_date is None]
        result["functional_actions"] = [a.model_dump() for a in sorted(abstraction.functional_actions, key=lambda a: (a.report_date, a.claim_id)) if start <= a.report_date <= end]
        result["interpretation_limits"] = ["Symptom score change does not establish remission, restored occupational function, or a causal treatment effect.",
                                           "Undated evidence is retained separately; membership in the requested period is unknown.",
                                           "Reporter/experiencer, negation and planned versus completed actions remain explicit in source claims."]
    return result


def _query_patient_result(abstraction: PatientAbstraction, spec: QuerySpec) -> dict:
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
        result = _compare_periods(abstraction, spec, start, end)
    elif spec.family in {"assessments", "progress"}:
        result = _clinical_progress(abstraction, spec, start, end)
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
    return {"patient": abstraction.patient.model_dump(), "query": spec.model_dump(), "result": result}


def query_patient(abstraction: PatientAbstraction, spec: QuerySpec, documents=None) -> dict:
    """Assemble one patient answer with its final document context."""
    return attach_evidence(_query_patient_result(abstraction, spec), [abstraction], documents)


def query_collection(abstractions: list[PatientAbstraction], spec: QuerySpec, documents=None) -> dict:
    results = [_query_patient_result(a, spec) for a in abstractions if spec.patient_id is None or a.patient.patient_id == spec.patient_id]
    if not results:
        raise ValueError("No patients match the query")
    answer = {"query": spec.model_dump(), "patients": results}
    if spec.family in {"cohort", "consecutive_under_target"}:
        answer["included_patient_ids"] = [r["patient"]["patient_id"] for r in results if r["result"]["included"]]
        answer["conditional_patient_ids"] = [r["patient"]["patient_id"] for r in results if r["result"]["conditional_inclusion"]]
    return attach_evidence(answer, abstractions, documents)
