"""Evaluator-only labels. Independent scores freeze before any A/B comparison."""
from collections import Counter
from copy import deepcopy
from statistics import mean
import json

from .runtime import read, lines, selected, integrity, requests
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.schema import validate_extraction
from ..luna_rescore.evaluation import project, apply_overlay
from ..luna_round2.evaluation import baseline, summarize
from ..simsum_comparison.evaluation import references, load_jsonl


def outputs(repo, root, name):
    docs = selected(repo)
    if name == "V2":
        return baseline(repo, docs)
    if name == "A":
        path = root / "A/final-predictions.jsonl"
        if not path.exists():
            raise ValueError("Freeze every A source-review decision before evaluation")
        return {r["document_id"]: r["result"] for r in load_jsonl(path)}
    if name != "B":
        raise ValueError("Unknown system")
    result = {}
    for doc in docs:
        p = root / "B/requests" / doc.document_id.replace(":", "_") / "result.json"
        if p.exists():
            result[doc.document_id] = validate_extraction(json.dumps(read(p)), doc).model_dump()
    return result


def source_diagnostics(values):
    facts = [(doc_id, i, f) for doc_id, v in values.items() for i, f in enumerate(v["facts"])]
    nonliteral = [{"document_id": d, "fact_index": i, "fact": f} for d, i, f in facts
                  if f["original_term"] not in f["evidence"]["quote"]]
    return {"facts": len(facts), "nonliteral_original_terms": len(nonliteral),
            "documents_with_nonliteral_terms": len({r["document_id"] for r in nonliteral}),
            "literal_original_term_rate": 1 - len(nonliteral) / len(facts) if facts else None}, nonliteral


def atomic_controls(docs, values):
    by_id = {d.document_id: d for d in docs}
    repeated = []
    for doc_id, quote in [("simsum:4613:text", "mucus production alongside the cough"),
                          ("simsum:2278:text", "frequent coughing"),
                          ("simsum:7407:text", "morning cough"),
                          ("simsum:2899:advanced_text", "describes cough as unprecedented")]:
        start = by_id[doc_id].text.index(quote)
        found = [i for i, f in enumerate(values.get(doc_id, {"facts": []})["facts"])
                 if (f["concept"] or "").strip().casefold() == "cough"
                 and max(start, f["evidence"]["start"]) < min(start + len(quote), f["evidence"]["end"])]
        repeated.append({"document_id": doc_id, "source_quote": quote, "source_start": start,
                         "matching_fact_indices": found, "covered": bool(found)})
    clinical = []
    for doc_id, marker, mechanism in [("simsum:192:advanced_text", "no noted change/exacerbation", "change_negated_as_symptom_absent"),
                                      ("simsum:8698:text", "not reported", "nonreport_promoted_to_absent"),
                                      ("simsum:1522:advanced_text", "OTC antipyretics", "antipyretics_changed_to_antibiotics")]:
        doc = by_id[doc_id]
        start = doc.text.index(marker)
        relevant = [f for f in values.get(doc_id, {"facts": []})["facts"] if
                    max(start, f["evidence"]["start"]) < min(start + len(marker), f["evidence"]["end"])]
        bad = [f for f in relevant if
               ((mechanism == "change_negated_as_symptom_absent" and (f["concept"] or "").casefold() == "cough" and f["polarity"] == "absent") or
                (mechanism == "nonreport_promoted_to_absent" and f["category"] == "symptom" and f["polarity"] == "absent") or
                (mechanism == "antipyretics_changed_to_antibiotics" and (f["concept"] or "").casefold() == "antibiotics"))]
        clinical.append({"document_id": doc_id, "mechanism": mechanism, "bad_facts": bad,
                         "relevant_facts": relevant, "errors": len(bad),
                         "no_detected_error_does_not_prove_fact_was_retained": True})
    vitals = values.get("simsum:1522:advanced_text", {"facts": []})["facts"]
    aliases = {"temperature": {"temperature", "body temperature", "temp", "t"},
               "blood_pressure": {"blood pressure", "bp", "systolic blood pressure", "diastolic blood pressure"},
               "pulse": {"pulse", "heart rate", "pulse rate", "hr"},
               "respiratory_rate": {"respiratory rate", "respiration rate", "rr"},
               "oxygen_saturation": {"oxygen saturation", "o2 saturation", "spo2", "o2 sat", "oxygen saturation (spo2)"}}
    typed = {k: [i for i, f in enumerate(vitals) if (f["concept"] or "").strip().casefold() in terms
                 and f["category"] in {"observation", "laboratory_result"} and f.get("attributes")
                 and f["attributes"].get("value") is not None] for k, terms in aliases.items()}
    return {"repeated_symptom_control_cases": repeated, "repeated_controls_covered": sum(r["covered"] for r in repeated),
            "prior_semantic_error_controls": clinical, "known_semantic_error_facts": sum(r["errors"] for r in clinical),
            "typed_vital_control_fact_indices": typed, "typed_vital_control_facets": sum(bool(v) for v in typed.values()),
            "scope": "Predefined prior source-confirmed probes; semantic review and missed normalization remain separate; not full-document clinical gold"}


def execution(root, name):
    rows = [r for r in requests(root) if r["stage"] == name]
    tokens = Counter()
    known = 0
    for r in rows:
        u = json.loads(r["usage"]) if r["usage"] else None
        if u:
            known += 1
            tokens.update({k: v for k, v in u.items() if type(v) is int})
    return {"calls": len(rows), "calls_per_selected_document": len(rows) / 100,
            "statuses": dict(Counter(r["status"] for r in rows)), "usage_known_calls": known,
            "tokens": dict(tokens), "summed_request_seconds": sum(r["latency"] or 0 for r in rows),
            "mean_request_seconds": mean(r["latency"] for r in rows if r["latency"] is not None) if rows else None,
            "wall_seconds": sum(read(p)["wall_seconds"] for p in (root / name / "runs").glob("*.json")),
            "cost_usd": None if rows else 0, "cost_note": "Actual subscription billing unavailable; no invented price; reasoning is included in output tokens"}


def evaluate(repo, root, name):
    integrity(repo, root)
    docs = selected(repo)
    expected = {d.document_id for d in docs}
    own = [r for r in requests(root) if r["stage"] == name]
    if name == "B" and ({r["document_id"] for r in own} != expected or any(r["status"] == "reserved" for r in own)):
        raise ValueError("All 100 B initial requests must have terminal outcomes")
    if name == "A":
        flag_ids = set(read(root / "A/targeted-contracts.json"))
        if read(root / "A/offline-decision.json")["proceed"] and ({r["document_id"] for r in own} != flag_ids or any(r["status"] == "reserved" for r in own)):
            raise ValueError("Every flagged A case must finish once")
    values = outputs(repo, root, name)
    original, invalid = references(repo, docs)
    overlay = load_jsonl(repo / "artifacts/luna-offline-rescore-v1/reference_adjudication_overlay.jsonl")
    corrected, applied = apply_overlay(docs, original, [r for r in overlay if r["document_id"] in expected])
    audit = {r["document_id"]: r for r in load_jsonl(repo / "artifacts/luna-round2-v1/source-review-final.jsonl")}
    projected, _ = project(values)
    silver, _, _ = summarize(docs, projected, original, audit)
    metric, detail, assertions = summarize(docs, projected, corrected, audit)
    fields, nonliteral = source_diagnostics(values)
    result = {"system": name, "documents": 100, "original_silver": silver["silver"],
              "corrected": metric["silver"], "fixed_source_audit": metric["audited"],
              "source_fields": fields, "atomic_controls": atomic_controls(docs, values),
              "execution": execution(root, name) if name != "V2" else read(repo / "artifacts/luna-source-constrained-v1/comparison/metrics.json")["systems"]["historical_single_pass_effective"]["execution"],
              "invalid_original_reference_offsets": invalid, "overlay_edits_applied": len(applied),
              "universal_clinical_correctness_not_established": True}
    if name == "V2":
        previous = read(repo / "artifacts/luna-source-constrained-v1/comparison/metrics.json")["systems"]["historical_single_pass_effective"]
        if any(result[k] != previous[k] for k in ["corrected", "original_silver", "fixed_source_audit"]):
            raise ValueError("Historical corrected V2 baseline failed exact reproduction")
    lines(root / name / "mention-comparisons.jsonl", detail)
    lines(root / name / "assertion-audit.jsonl", assertions)
    lines(root / name / "nonliteral-original-terms.jsonl", nonliteral)
    write_json(root / name / "independent-metrics.json", result, immutable=True)
    return result


def materialize_a(repo, root):
    from .approach_a import materialize
    docs = selected(repo)
    original = baseline(repo, docs)
    decisions = load_jsonl(root / "A/source-review-actions.jsonl")
    by_doc = {}
    for r in decisions:
        key = (r["document_id"], r["proposal_index"])
        if key in {(d, i) for d, decisions in by_doc.items() for i in decisions}:
            raise ValueError("Duplicate A source decision")
        by_doc.setdefault(r["document_id"], {})[r["proposal_index"]] = r
    result, changes = [], []
    for doc in docs:
        folder = root / "A/requests" / doc.document_id.replace(":", "_")
        records = read(folder / "proposal-validation.json") if (folder / "proposal-validation.json").exists() else []
        own = by_doc.get(doc.document_id, {})
        for decision in own.values():
            if decision["note_sha256"] != doc.note_sha256 or decision["decision"] not in {"accept", "reject", "unresolved"}:
                raise ValueError("Source decision identity/status mismatch")
            e = decision["source_evidence"]
            if not 0 <= e["start"] < e["end"] <= len(doc.text) or doc.text[e["start"]:e["end"]] != e["quote"]:
                raise ValueError("Source review evidence is not literal")
        value = materialize(original[doc.document_id], records, own)
        validate_extraction(json.dumps(value), doc)
        result.append({"document_id": doc.document_id, "note_sha256": doc.note_sha256, "result": value})
        for r in records:
            decision = own.get(r["proposal_index"])
            changes.append({"document_id": doc.document_id, **r, "source_review": decision,
                            "accepted": bool(decision and decision["decision"] == "accept")})
    lines(root / "A/final-predictions.jsonl", result)
    lines(root / "A/change-log.jsonl", changes)
    write_json(root / "A/materialization-freeze.json", {"decisions_sha256": sha((root / "A/source-review-actions.jsonl").read_bytes()),
        "predictions_sha256": sha((root / "A/final-predictions.jsonl").read_bytes()),
        "original_facts_preserved_in_immutable_historical_artifacts": True,
        "accepted_changes": sum(r["accepted"] for r in changes)}, immutable=True)
    return {"accepted_changes": sum(r["accepted"] for r in changes), "reviewed_model_proposals": len(changes)}


def compare(repo, root):
    # Refuse cross-comparison until both independent evaluations are immutable.
    systems = {n: read(root / n / "independent-metrics.json") for n in ["V2", "A", "B"]}
    details = {n: {r["document_id"]: r for r in load_jsonl(root / n / "mention-comparisons.jsonl")} for n in systems}
    paired = []
    for d in selected(repo):
        counts = {n: {"tp": len(rows[d.document_id]["overlap_pairs"]),
                      "fp": len(rows[d.document_id]["unmatched_indices"]),
                      "fn": len(rows[d.document_id]["missing_indices"])} for n, rows in details.items()}
        base_error = counts["V2"]["fp"] + counts["V2"]["fn"]
        better = {n: counts[n]["fp"] + counts[n]["fn"] < base_error for n in ["A", "B"]}
        label = "both" if all(better.values()) else "A_only" if better["A"] else "B_only" if better["B"] else "neither"
        paired.append({"document_id": d.document_id, "note_sha256": d.note_sha256,
                       "systems": counts, "improved_mention_error_count": label})
    lines(root / "paired-document-comparison.jsonl", paired)
    result = {"systems": systems, "mention_improvement_overlap": dict(Counter(r["improved_mention_error_count"] for r in paired)),
              "total_new_calls": len(requests(root)), "approaches_not_combined": True,
              "scope": "Benchmark overlap is not full clinical correctness; source-review gains/regressions reported separately"}
    write_json(root / "comparison-metrics.json", result, immutable=True)
    return result
