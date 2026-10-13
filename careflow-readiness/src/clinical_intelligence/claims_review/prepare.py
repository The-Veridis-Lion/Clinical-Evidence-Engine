"""Build source candidates with deterministic boundaries; do not score criteria."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from . import __version__
from .contracts import CaseInput


def digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def line_anchors(source_id: str, text: str) -> list[dict]:
    """Offsets are Python Unicode code-point offsets, not UTF-8 byte offsets."""
    anchors, offset = [], 0
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        quote = line.rstrip("\r\n")
        if quote.strip():
            anchors.append({"span_id": f"{source_id}:L{number:03d}", "start": offset,
                            "end": offset + len(quote), "quote": quote})
        offset += len(line)
    return anchors


def prepare_case(case: CaseInput, policy: dict, *, input_label: str) -> dict:
    """Patient/date screening only. No note inference, coverage decision or gold read."""
    context, claim = case.review_context, case.claim
    canonical_input = case.model_dump(mode="json")
    candidates, excluded, unresolved, linked = [], [], [], defaultdict(list)
    reasons = []
    status = "PREPARED_NOT_EVALUATED"
    if claim.service_concept == "hba1c_screening":
        status = "UNSUPPORTED_SCOPE"
        reasons.append("Screening is outside this monitoring-only preparation workflow; no coverage judgment made.")
    elif claim.service_concept == "unspecified":
        status = "NEEDS_INPUT_REVIEW"
        reasons.append("The claim does not establish a supported service purpose.")
    if claim.service_date is None:
        if status != "UNSUPPORTED_SCOPE":
            status = "NEEDS_INPUT_REVIEW"
        reasons.append("Service date is unknown; it is not replaced by any document date.")
    elif claim.service_date > context.as_of:
        if status != "UNSUPPORTED_SCOPE":
            status = "NEEDS_INPUT_REVIEW"
        reasons.append("Service date is after this review's as_of date; this is not an authorization workflow.")
    # This preparation kit never verifies a billing code, even if an input says verified.
    if claim.mapping_status != "constructed_demo" or claim.procedure_code is not None:
        status = "UNSUPPORTED_SCOPE"
        reasons.append("Billing-code mapping is not implemented; this kit accepts explicitly constructed service concepts only.")
    if context.history_completeness == "not_asserted":
        reasons.append("History completeness is not asserted; missing retrieved history cannot prove an absence of tests.")
    history_end = min(context.history_end, claim.service_date) if claim.service_date else context.history_end
    if claim.service_date is not None and context.history_end < claim.service_date:
        reasons.append("History window ends before the target date; its completeness statement does not cover that gap. Target-date sources are retained separately.")

    for index, source in enumerate(case.sources):
        source_ref = {"input": input_label, "json_pointer": f"/sources/{index}",
                      "source_id": source.source_id, "sha256": digest(source.model_dump(mode="json"))}
        rejection = None
        if source.patient_id != claim.patient_id:
            rejection = "patient_mismatch"
        elif source.available_at is None:
            rejection = "availability_unknown"
        elif source.available_at > context.as_of:
            rejection = "not_available_as_of"
        elif source.recorded_at is not None and source.recorded_at > source.available_at:
            rejection = "inconsistent_recorded_and_available_dates"
        elif source.source_kind == "structured_record" and source.event_date is not None:
            if source.event_date > context.as_of:
                rejection = "future_event_as_of_not_prior_support"
            elif claim.service_date is not None and source.event_date > claim.service_date:
                rejection = "post_service_event_not_prior_support"
            elif source.event_date != claim.service_date and source.record_type in {"observation", "procedure", "encounter"} and not context.history_start <= source.event_date <= history_end:
                rejection = "outside_declared_history_window"
        # Event-window filtering must not conceal disagreement within an explicitly
        # linked event already available for this patient. Keep metadata, not a
        # claim that excluded records provide completed-treatment support.
        if source.event_link_id is not None and rejection not in {
            "patient_mismatch", "availability_unknown", "not_available_as_of",
            "inconsistent_recorded_and_available_dates"
        }:
            linked[(source.patient_id, source.event_link_id)].append({
                "source_id": source.source_id,
                "event_date": source.event_date.isoformat() if source.event_date else None,
                "source_ref": source_ref,
                "candidate_exclusion_reason": rejection,
            })
        if rejection:
            excluded.append({"source_ref": source_ref, "reason": rejection})
            if rejection in {"availability_unknown", "inconsistent_recorded_and_available_dates"}:
                unresolved.append({"source_id": source.source_id, "reason": rejection})
            continue

        entry = source.model_dump(mode="json")
        entry["source_ref"] = source_ref
        if source.source_kind == "synthetic_note":
            entry["temporal_role"] = "requires_semantic_extraction"
            entry["line_anchors"] = line_anchors(source.source_id, source.content)
        else:
            entry["temporal_role"] = "unknown_event_date" if source.event_date is None else (
                "relative_to_target_unknown" if claim.service_date is None else (
                "same_calendar_date_as_target" if source.event_date == claim.service_date else "historical_or_background"))
            # These are raw field pointers, not assertions of clinical correctness.
            entry["field_refs"] = {key: source_ref["json_pointer"] + "/content/" + key.replace("~", "~0").replace("/", "~1") for key in source.content}
            if source.event_date is None:
                unresolved.append({"source_id": source.source_id, "reason": "event_date_unknown"})
        candidates.append(entry)

    event_groups = []
    for (patient_id, event_link_id), entries in sorted(linked.items()):
        dates = sorted({entry["event_date"] for entry in entries if entry["event_date"] is not None})
        event_groups.append({"patient_id": patient_id, "event_link_id": event_link_id,
                             "source_ids": [entry["source_id"] for entry in entries],
                             "members": entries,
                             "documented_event_dates": dates,
                             "has_date_disagreement": len(dates) > 1,
                             "has_unknown_event_date": any(entry["event_date"] is None for entry in entries),
                             "reconciliation": "not_performed", "counted_as_tests": None})
        if len(dates) > 1:
            unresolved.append({"event_link_id": event_link_id,
                               "source_ids": [entry["source_id"] for entry in entries],
                               "reason": "explicit_event_date_disagreement"})
    if not candidates:
        if status == "PREPARED_NOT_EVALUATED":
            status = "NEEDS_INPUT_REVIEW"
        reasons.append("No sources remain in scope; this is not a finding that no clinical events occurred.")
    if unresolved:
        reasons.append("Some source dates or availability are unresolved; affected downstream conclusions must retain that gap.")

    body = {"preparation_version": __version__, "case_id": case.case_id,
            "preparation_status": status, "claim": claim.model_dump(mode="json"),
            "review_context": context.model_dump(mode="json"), "reasons": reasons,
            "claim_metadata_boundary": "service_concept selects a requested workflow; it is not documentary proof of the actual clinical purpose or test performance.",
            "source_candidates": candidates, "excluded_sources": excluded,
            "unresolved_source_metadata": unresolved, "explicit_event_groups": event_groups,
            "policy_reference": {"registry_version": policy["registry_version"],
                "sha256": digest(policy), "review_status": policy["review_status"],
                "human_review_completed": policy["human_review_completed"],
                "criterion_ids": [criterion["criterion_id"] for criterion in policy["criteria"]]},
            "execution": {"live_model_calls": 0, "note_extraction": "not_run",
                "clinical_reconciliation": "not_run", "policy_evaluation": "not_run",
                "uses_gold": False, "note_source_count": sum(entry["source_kind"] == "synthetic_note" for entry in candidates)},
            "input_sha256": digest(canonical_input),
            "temporal_contract": "Date-level inclusive cutoff; source availability, event date and recorded date have separate roles. Mixed note event dates still need semantic extraction."}
    body["output_sha256"] = digest(body)
    return body
