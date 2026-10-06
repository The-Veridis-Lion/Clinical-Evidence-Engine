"""Deterministic utilization for explicitly scoped clinical services."""
from __future__ import annotations
from datetime import date, timedelta
from .domain import CalculationTrace, PatientAbstraction, ServiceEvent, THERAPY_TYPES


def bounded(lower, upper):
    return {"lower": lower, "upper": upper, "value": lower if upper == lower else None}


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


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
    if any(u.explanation in {"Explicit correction creates an invalid interval.",
                             "Explicit correction cannot be applied safely to its target field."}
           for u in event.uncertainties):
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


