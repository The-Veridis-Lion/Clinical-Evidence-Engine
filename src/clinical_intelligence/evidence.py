"""Audit-only links from extracted quantitative fields to exact retained text.

This does not extract or correct facts. Missing or ambiguous support stays explicit.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from .domain import (
    AssessmentClaim, ClinicalClaim, CorrectionRelationship, PlanClaim,
    RegisteredDocument, ServiceClaim,
)
from .extraction import locate_passage


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _number(value: int | float) -> str:
    return re.escape(f"{value:g}") + r"(?:\.0+)?"


def _contains_clock(text: str, value: int) -> bool:
    return re.search(r"(?<!\d)" + re.escape(_clock(value)) + r"(?!\d)", text) is not None


def _interval_match(text: str, value: dict) -> bool:
    # Both endpoints must appear in order in the same local evidence unit.
    return re.search(r"(?<!\d)" + re.escape(_clock(value["start"]))
                     + r"(?!\d)[^\n]{0,180}?(?<!\d)"
                     + re.escape(_clock(value["end"])) + r"(?!\d)", text) is not None


def _matches(claim: ClinicalClaim, field: str, value, text: str, *, existing: bool) -> bool:
    lowered = text.casefold()
    if field.startswith(("actual_intervals[", "scheduled_intervals[", "unspecified_intervals[", "breaks[")):
        if not _interval_match(text, value):
            return False
        if existing:
            return True
        if field.startswith("breaks["):
            return bool(re.search(r"break|interrupt|disconnect|connection|reconnect|no\s+(?:therapeutic|clinical)", lowered))
        if field.startswith("scheduled_intervals["):
            return bool(re.search(r"schedul|appointment\s+(?:ran|time)|slot", lowered))
        if field.startswith("actual_intervals["):
            return bool(re.search(r"actual|patient\s+contact|present|participat|psychotherapy|therapy\s+(?:from|with)|resumed", lowered))
        # Unspecified clocks are deliberately not promoted to a stronger role.
        return False
    if field == "reported_minutes":
        duration = re.search(r"(?<![\d.])" + _number(value) + r"\s*(?:[-–]\s*)?min(?:ute)?s?\b", text, re.I)
        return bool(duration and (existing or re.search(r"patient|treatment|psychotherapy|therapy|contact|duration", lowered)))
    if field in {"original_time", "replacement_time"}:
        if not _contains_clock(text, value):
            return False
        cue = r"original|old|replac|previous|initial" if field == "original_time" else r"correct|replac|amend|revis"
        return bool(re.search(cue, lowered))
    if field == "replacement_minutes":
        return bool(re.search(r"(?<![\d.])" + _number(value) + r"\s*minutes?\b", text, re.I)
                    and re.search(r"correct|replac|amend|revis", lowered))
    if field == "required_days":
        return bool(re.search(r"(?<!\d)" + _number(value) + r"\s+(?:[\w-]+\s+){0,3}days?\b", text, re.I)
                    and (existing or re.search(r"goal|require|at\s+least|per\s+week|weekly", lowered)))
    if field == "required_minutes":
        return bool(re.search(r"(?<![\d.])" + _number(value) + r"\s*minutes?\b", text, re.I)
                    and (existing or re.search(r"goal|require|at\s+least|per\s+week|weekly", lowered)))
    if field == "score":
        score = r"(?<![\d.])" + _number(value) + r"(?!\d|\.\d)"
        total = re.search(r"(?:total(?:\s+score)?|score)\s*[:=]?\s*" + score, text, re.I)
        table = re.search(re.escape(claim.instrument) + r"\s*\|\s*" + score, text, re.I)
        return bool(total or table)
    return False


def _fields(claim: ClinicalClaim) -> dict:
    if isinstance(claim, ServiceClaim):
        values = {f"{name}[{index}]": interval.model_dump()
                  for name in ("actual_intervals", "scheduled_intervals", "unspecified_intervals", "breaks")
                  for index, interval in enumerate(getattr(claim, name))}
        if claim.reported_minutes is not None:
            values["reported_minutes"] = claim.reported_minutes
        return values
    if isinstance(claim, PlanClaim):
        return {"required_days": claim.required_days, "required_minutes": claim.required_minutes}
    if isinstance(claim, AssessmentClaim):
        return {"score": claim.score}
    if isinstance(claim, CorrectionRelationship):
        return {name: getattr(claim, name) for name in ("original_time", "replacement_time", "replacement_minutes")
                if getattr(claim, name) is not None}
    return {}


def _source_units(document: RegisteredDocument) -> list[tuple[int, int, str]]:
    # Lines preserve table rows and compound statements; paragraphs handle wrapped text.
    units = {(match.start(), match.end(), match.group())
             for pattern in (r"[^\n]+", r"\S[^\n]*(?:\n(?!\s*\n)[^\n]+)*")
             for match in re.finditer(pattern, document.text)}
    return sorted(units, key=lambda item: (item[1] - item[0], item[0]))


def _references(claim: ClinicalClaim) -> set[str]:
    return {value for name in ("encounter_ref", "appointment_ref", "target_encounter")
            if (value := getattr(claim, name, None))}


def _scope(claim: ClinicalClaim, text: str, peers: Iterable[ClinicalClaim]) -> bool:
    own = _references(claim)
    other = {ref for peer in peers if peer.claim_id != claim.claim_id for ref in _references(peer)} - own
    if any(ref in text for ref in other):
        return False
    # Multi-encounter documents require an explicit encounter/appointment anchor.
    return not other or bool(own and any(ref in text for ref in own))


def _table_passages(claim: ClinicalClaim, document: RegisteredDocument, field: str, value) -> list:
    """Link an identified row together with the header defining its numeric columns."""
    if not isinstance(claim, ServiceClaim) or not _references(claim):
        return []
    header = None
    matches = []
    for line in re.finditer(r"[^\n]+", document.text):
        cells = [cell.strip() for cell in line.group().split("|")]
        labels = [re.sub(r"\s+", " ", cell.casefold()) for cell in cells]
        if any(label in {"encounter", "encounter id", "appointment", "appointment id"} for label in labels):
            header = line, labels
            continue
        if header is None or len(cells) != len(header[1]) or not _references(claim).intersection(cells):
            continue
        columns = dict(zip(header[1], cells))
        supported = False
        if field.startswith("actual_intervals["):
            arrival = columns.get("actual arrival", columns.get("actual start"))
            departure = columns.get("actual departure", columns.get("actual end"))
            supported = bool(arrival and departure and _contains_clock(arrival, value["start"])
                             and _contains_clock(departure, value["end"]))
        elif field.startswith("scheduled_intervals["):
            scheduled = columns.get("scheduled", columns.get("scheduled interval"))
            supported = bool(scheduled and _interval_match(scheduled, value))
        if supported:
            matches.append([locate_passage(document, source.group(), source.start(), source.end())
                            for source in (header[0], line)])
    return matches[0] if len(matches) == 1 else []


def quantitative_evidence(claim: ClinicalClaim, document: RegisteredDocument | None,
                          document_claims: Iterable[ClinicalClaim] = ()) -> dict:
    """Return field references without altering immutable extraction snapshots.

    An exact value match is sufficient inside a claim's accepted passage. Broader
    lookup additionally requires an evidence-role cue and unambiguous event scope.
    Absence of a safe match is reported, never replaced by an unrelated number.
    """
    if document is not None and document.document_id != claim.document_id:
        raise ValueError("Claim and retained source document do not match")
    for passage in claim.passages:
        if document is not None and (passage.document_id != document.document_id or document.text[passage.start:passage.end] != passage.quote):
            raise ValueError("Quantitative evidence requires exact retained source passages")
    peers = tuple(document_claims)
    # In-memory queries can cite persisted passages without a document registry.
    units = _source_units(document) if document is not None else []
    result = {}
    for field, value in _fields(claim).items():
        if value is None:
            result[field] = {"value": None, "status": "unknown", "basis": None, "passages": []}
            continue
        passages = [p for p in claim.passages if _matches(claim, field, value, p.quote, existing=True)]
        basis = "existing_claim_passage"
        if not passages and document is not None:
            passages = _table_passages(claim, document, field, value)
            basis = "exact_table_header_and_row"
        if not passages:
            candidates = [(start, end, text) for start, end, text in units
                          if _scope(claim, text, peers) and _matches(claim, field, value, text, existing=False)]
            # A line and its enclosing paragraph are one location, not competing evidence.
            locations = []
            for candidate in candidates:
                if not any(candidate[0] <= p[0] and candidate[1] >= p[1] for p in locations):
                    locations.append(candidate)
            if len(locations) == 1:
                start, end, text = locations[0]
                passages = [locate_passage(document, text, start, end)]
            basis = "exact_source_context"
        result[field] = {"value": value, "status": "supported" if passages else "not_located",
                         "basis": basis if passages else None,
                         "passages": [p.model_dump() for p in passages]}
    return result
