"""Forward runtime traces over persisted claims and calculation inputs."""
from __future__ import annotations

from itertools import product

from .domain import AssessmentClaim, CorrectionRelationship, PatientAbstraction, ServiceClaim
from .evidence import quantitative_evidence


def completeness(parts):
    states = [p.get("completeness", "missing") for p in parts]
    if not states or all(s == "complete" for s in states):
        return "complete"
    return "missing" if all(s == "missing" for s in states) else "partial"


class RuntimeProvenance:
    """SourceRefs point into the existing evidence index; quotes are not copied."""

    def __init__(self, abstractions, evidence):
        self.claims = {c.claim_id: c for a in abstractions for c in a.source_claims}
        self.events = {e.event_id: e for a in abstractions for e in a.events}
        self.assessments = {a.assessment_id: a for p in abstractions for a in p.assessments}
        self.evidence = evidence
        # Reuse event field traces within this request, never across mutable snapshots.
        self._duration_cache = {}

    def contribution(self, fact_id, field, value, claim_fields, *, included=True, reason="Source-supported input"):
        refs, gaps = [], []
        for claim_id, source_field in sorted(set(claim_fields)):
            item = self.evidence.get(claim_id)
            if item is None:
                gaps.append(f"Missing source claim: {claim_id}")
                continue
            # Escape arbitrary IDs using the standard JSON-pointer token rules.
            token = claim_id.replace("~", "~0").replace("/", "~1")
            path = f"/evidence/{token}"
            if source_field is None:
                passages = item["passages"]
                path += "/passages"
            else:
                found = item["quantitative_fields"].get(source_field, {})
                passages = found.get("passages", [])
                path += f"/quantitative_fields/{source_field}/passages"
            if not passages:
                gaps.append(f"No direct support: {claim_id}.{source_field or field}")
            if item.get("retained_source_available") is False:
                gaps.append(f"Original document unavailable: {item['document_id']}")
            for index, passage in enumerate(passages):
                refs.append({"document_id": item["document_id"], "declared_id": item["declared_id"],
                             "source_names": item["source_names"], "claim_id": claim_id,
                             "passage_id": f"{passage['document_id']}:{passage['start']}:{passage['end']}",
                             "evidence_path": f"{path}/{index}"})
        return {"fact_id": fact_id, "field": field, "value": value, "included": included,
                "reason": reason, "source_refs": refs, "gaps": sorted(set(gaps)),
                "completeness": "complete" if refs and not gaps else "partial" if refs else "missing"}

    def trace(self, operation, contributions, *, alternatives=(), gaps=()):
        pieces = [*contributions, *alternatives]
        state = completeness(pieces)
        if gaps:
            state = "partial" if pieces else "missing"
        all_gaps = list(gaps)
        def collect(value):
            if isinstance(value, dict):
                all_gaps.extend(value.get("gaps", []))
                for key, item in value.items():
                    if key != "gaps":
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        collect(pieces)
        return {"operation": operation, "completeness": state, "contributions": contributions,
                "alternatives": list(alternatives), "gaps": sorted(set(all_gaps))}

    def duration(self, event):
        if event.event_id in self._duration_cache:
            return self._duration_cache[event.event_id]
        alternatives = []
        for calculation in event.calculations:
            fields = []
            claims = [self.claims[i] for i in calculation.claim_ids if i in self.claims]
            reported = calculation.inputs.get("reported_minutes")
            if reported is not None:
                matches = [(c.claim_id, "reported_minutes") for c in claims
                           if isinstance(c, ServiceClaim) and c.reported_minutes == reported]
                matches += [(c.claim_id, "replacement_minutes") for c in claims
                            if isinstance(c, CorrectionRelationship) and c.replacement_minutes == reported]
                fields.append(self.contribution(event.event_id, "reported_minutes", reported, matches))
            for interval_index, interval in enumerate(calculation.inputs.get("actual_intervals", [])):
                matches = [(c.claim_id, f"actual_intervals[{i}]") for c in claims if isinstance(c, ServiceClaim)
                           for i, source in enumerate(c.actual_intervals) if source.model_dump() == interval]
                corrections = [c for c in claims if isinstance(c, CorrectionRelationship)
                               and c.relation == "corrects" and c.field in {"arrival", "departure"}]
                if not matches and corrections:
                    # Corrected clocks need both the unchanged endpoint and replacement evidence.
                    for source in (c for c in claims if isinstance(c, ServiceClaim)):
                        for i, original in enumerate(source.actual_intervals):
                            if any((r.field == "departure" and original.start == interval["start"] and r.replacement_time == interval["end"]
                                    or r.field == "arrival" and original.end == interval["end"] and r.replacement_time == interval["start"])
                                   for r in corrections):
                                matches.append((source.claim_id, f"actual_intervals[{i}]"))
                    matches += [(c.claim_id, "replacement_time") for c in corrections]
                fields.append(self.contribution(event.event_id, f"actual_intervals[{interval_index}]", interval, matches,
                                               reason="Union contact intervals; apply only persisted explicit corrections"))
            for interval_index, interval in enumerate(calculation.inputs.get("breaks", [])):
                matches = [(c.claim_id, f"breaks[{i}]") for c in claims if isinstance(c, ServiceClaim)
                           for i, source in enumerate(c.breaks) if source.model_dump() == interval]
                fields.append(self.contribution(event.event_id, f"breaks[{interval_index}]", interval, matches, included=False,
                                               reason="Exclude geometric overlap with patient contact; never add the gap"))
            for correction in (c for c in claims if isinstance(c, CorrectionRelationship) and c.relation == "corrects"):
                for name in ("original_time", "replacement_time", "replacement_minutes"):
                    value = getattr(correction, name)
                    if value is not None:
                        fields.append(self.contribution(event.event_id, name, value, [(correction.claim_id, name)],
                                                       included=name != "original_time", reason="Retain original and explicitly corrected field separately"))
            alternatives.append({"value": calculation.output.get("minutes"),
                                 "calculation_trace": calculation.model_dump(), "contributions": fields,
                                 "completeness": completeness(fields) if fields else "missing"})
        # Equal-duration reports remain evidence alternatives, never additional care.
        self._duration_cache[event.event_id] = alternatives
        return alternatives

    def event_contributions(self, row):
        event = self.events[row["event_id"]]
        duration = self.duration(event)
        minutes = self.contribution(event.event_id, "minutes", row["minutes"], [],
                                    reason="Use supported event alternatives once, not once per document")
        minutes.update(alternatives=duration, completeness=completeness(duration) if duration else "missing", gaps=[])
        minutes["source_refs"] = [ref for option in duration for field in option["contributions"]
                                  for ref in field["source_refs"]]
        if not duration:
            minutes["gaps"] = ["No persisted duration calculation supports this bound"]
        sources = [(i, None) for i in event.claim_ids if i in self.claims]
        counts = [self.contribution(event.event_id, "sessions", row["sessions"], sources,
                                   reason="Count one qualifying encounter across linked reports"),
                  self.contribution(event.event_id, "distinct_service_days", row["date_options"], sources,
                                    reason="Union qualifying local dates; each encounter chooses one date")]
        # Eligibility is a decision over all retained claims, including excluded evidence.
        decisions = [{**d.model_dump(), "source_refs": self.contribution(event.event_id, "decision", d.rule,
                     [(i, None) for i in d.claim_ids])["source_refs"]} for d in event.decisions]
        for contribution in [minutes, *counts]:
            contribution["decisions"] = decisions
        for count in counts:
            count["inputs"] = [self.contribution(event.event_id, name, getattr(event, name),
                               [(c.claim_id, None) for c in self.claims.values()
                                if isinstance(c, ServiceClaim) and c.claim_id in event.claim_ids],
                               reason="Persisted eligibility and identity inputs; see reconciliation decisions")
                               for name in ("encounter_ref", "date_options", "type_options", "patient_present", "delivered")]
        return [minutes, *counts]

    def utilization(self, node):
        parts = []
        for row in node["contributions"]:
            row["provenance"] = self.trace("resolved_event_contribution", self.event_contributions(row))
            parts.extend(row["provenance"]["contributions"])
        for row in node.get("excluded_events", []):
            event = self.events[row["event_id"]]
            excluded = self.contribution(event.event_id, "excluded_event", 0,
                                         [(i, None) for i in event.claim_ids], included=False,
                                         reason="; ".join(d.explanation for d in event.decisions))
            row["provenance"] = self.trace("exclude_nonqualifying_event", [excluded])
            parts.append(excluded)
        alternatives = []
        rows = node["contributions"]
        choices = [r["minute_options"] for r in rows]
        size = 1
        for values in choices:
            size *= len(values)
        if node["totals"]["minute_alternatives"] is not None and size <= 4096:
            for assignment in product(*choices):
                contributions = []
                for row, value in zip(rows, assignment):
                    event = self.events[row["event_id"]]
                    options = [o for o in self.duration(event) if o["value"] == value]
                    contributions.append({"fact_id": event.event_id, "field": "minutes", "value": value,
                                          "alternatives": options, "completeness": completeness(options) if options else "partial",
                                          "reason": "Supported duration choice" if options else "Conditional eligibility: zero is a bound, not observed absence"})
                alternatives.append({"value": sum(assignment), "contributions": contributions,
                                     "completeness": completeness(contributions)})
        gaps = [] if node["totals"]["minute_alternatives"] is not None and size <= 4096 else ["Exact scenario expansion unavailable; conservative bounds and event traces retained"]
        node["provenance"] = self.trace(node["calculation"]["operation"], parts, alternatives=alternatives, gaps=gaps)
        node["provenance"]["outputs"] = node["totals"]
        node["provenance"]["derivations"] = {
            "sessions": "Sum encounter contributions once per event_id",
            "distinct_service_days": "Cardinality of the union of qualifying local dates",
            "minutes": "Sum one supported duration choice per included event",
            "hours": "Divide minute bounds by 60",
        }

    def plan(self, plan):
        return [self.contribution(plan["plan_id"], name, plan[name],
                                 [(i, name) for i in plan["claim_ids"]], reason="Applicable persisted treatment-plan threshold")
                for name in ("required_days", "required_minutes")]

    def decorate(self, value):
        if isinstance(value, list):
            for item in value:
                self.decorate(item)
            return
        if not isinstance(value, dict):
            return
        # Traverse only clinical results; evidence and provenance are terminal indexes.
        for key, item in list(value.items()):
            if key not in {"evidence", "provenance", "calculation", "calculations", "decisions", "query", "candidate_plans"}:
                self.decorate(item)
        if "totals" in value and "contributions" in value and "calculation" in value:
            self.utilization(value)
        elif "candidate_plans" in value and "actual" in value:
            actual = value["actual"]["provenance"]
            thresholds = [c for p in value["candidate_plans"] for c in self.plan(p)]
            branches = []
            requirement = value["requirement"]
            if requirement:
                for option in actual["alternatives"]:
                    days = value["actual"]["totals"]["distinct_service_days"]
                    status = ("met" if days["lower"] >= requirement["days"] and option["value"] >= requirement["minutes"]
                              else "not_met" if days["upper"] < requirement["days"] or option["value"] < requirement["minutes"]
                              else "cannot_determine")
                    branches.append({"minutes": option["value"], "days": days, "status": status,
                                     "contributions": option["contributions"], "completeness": option["completeness"]})
            value["provenance"] = self.trace(value["calculation"]["operation"],
                                             [*actual["contributions"], *thresholds], alternatives=branches,
                                             gaps=[value["ambiguity"]] if value["ambiguity"] else [])
            value["provenance"]["comparison"] = {"operation": "actual_days >= required_days AND actual_minutes >= required_minutes",
                                                    "actual": value["actual"]["totals"], "requirement": requirement, "status": value["status"]}
        elif "assessment_id" in value and "score_options" in value:
            parts = [self.contribution(value["assessment_id"], "score", score,
                     [(i, "score") for i in value["claim_ids"] if isinstance(self.claims.get(i), AssessmentClaim)
                      and self.claims[i].score == score], reason="Distinct assessment completion; imported copies add no completion")
                     for score in value["score_options"]]
            value["provenance"] = self.trace("assessment_score_alternatives", parts)
        elif "difference_after_minus_before" in value:
            before, after = value["before"]["provenance"], value["after"]["provenance"]
            parts = [{**c, "period": period} for period, trace in (("before", before), ("after", after)) for c in trace["contributions"]]
            value["provenance"] = self.trace("subtract_before_from_after", parts)
            value["provenance"]["outputs"] = value["difference_after_minus_before"]
        elif value.get("operation") == "assessment_score_change":
            parts = [self.contribution(i, "score", self.claims[i].score, [(i, "score")])
                     for i in value["claim_ids"] if isinstance(self.claims.get(i), AssessmentClaim)]
            value["provenance"] = self.trace(value["operation"], parts)
        elif "definite_windows" in value:
            parts = [c for week in value["weeks"] for c in week["provenance"]["contributions"]]
            value["provenance"] = self.trace("consecutive_week_decisions", parts)
        elif "included" in value and "actual" in value:
            value["provenance"] = self.trace("cohort_threshold_comparison", value["actual"]["provenance"]["contributions"])
            value["provenance"]["comparison"] = value.get("comparison", {})
        elif value.get("status") == "insufficient_evidence" and "explanation" in value:
            value["provenance"] = self.trace("insufficient_evidence_decision", [], gaps=[value["explanation"]])
        elif "claim_id" in value and "statement" in value:
            fields = ("polarity", "temporality", "reporter", "experiencer") if value.get("kind") == "observation" else ("status", "actor", "reporter")
            parts = [self.contribution(value["claim_id"], field, value[field], [(value["claim_id"], None)]) for field in fields if field in value]
            value["provenance"] = self.trace("direct_source_claim", parts)


def add_runtime_provenance(answer, abstractions):
    runtime = RuntimeProvenance(abstractions, answer["evidence"])
    runtime.decorate(answer.get("result", answer.get("patients", [])))
    def collect(value):
        states = []
        if isinstance(value, dict):
            if "provenance" in value:
                states.append(value["provenance"])
            for key, item in value.items():
                if key not in {"evidence", "provenance"}:
                    states.extend(collect(item))
        elif isinstance(value, list):
            for item in value:
                states.extend(collect(item))
        return states
    # Embedded patient envelopes share the collection's single evidence index.
    for patient in answer.get("patients", []):
        patient["provenance_completeness"] = completeness(collect(patient["result"]))
        patient["evidence_scope"] = "collection_root"
    answer["provenance_completeness"] = completeness(collect(answer))
    return answer


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
