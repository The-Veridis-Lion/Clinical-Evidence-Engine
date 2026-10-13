"""Frozen scoring contract and raw/evidence comparison, with no model judge."""
from collections import Counter
from statistics import mean, median
import json

from .runtime import read, integrity, chosen, OneRequestLedger, CONFIG
from ..clinical_notes.dataset import write_json, sha
from ..clinical_notes.schema import validate_extraction
from ..luna_rescore.evaluation import project, apply_overlay
from ..luna_round2.evaluation import summarize
from ..luna_grounding.evaluation import semantic_differences
from ..simsum_comparison.evaluation import references, load_jsonl, jsonl


def credit_estimate(usage, rates):
    """Documented standard credit-rate equivalent, not an actual subscription bill."""
    required = ("input_tokens", "cached_input_tokens", "output_tokens")
    if any(type(usage.get(k)) is not int for k in required):
        return None
    if not 0 <= usage["cached_input_tokens"] <= usage["input_tokens"]:
        raise ValueError("Invalid cache subset usage")
    return ((usage["input_tokens"] - usage["cached_input_tokens"]) * rates["input"]
            + usage["cached_input_tokens"] * rates["cached_input"]
            + usage["output_tokens"] * rates["output"]) / 1_000_000


def evaluate(repo, root):
    m = integrity(repo, root)
    docs = chosen(repo)
    rows = OneRequestLedger(root / "requests.sqlite3", m).rows()
    if {r["document_id"] for r in rows} != {d.document_id for d in docs} or any(r["status"] == "reserved" for r in rows):
        raise ValueError("All 100 require terminal outcomes; interrupted reservations must not be replayed")
    values = {}
    for doc in docs:
        row = next(r for r in rows if r["document_id"] == doc.document_id)
        folder = root / "requests" / doc.document_id.replace(":", "_")
        if (folder / "raw-response.json").exists() and sha((folder / "raw-response.json").read_bytes()) != row["raw_hash"]:
            raise ValueError("Raw Sol response changed")
        if row["status"] == "valid":
            values[doc.document_id] = validate_extraction(json.dumps(read(folder / "result.json")), doc).model_dump()
    cached = {x["document_id"]: x["result"] for x in load_jsonl(repo / "artifacts/luna-grounding-v3/comparison/predictions.jsonl") if x["status"] == "valid"}
    outputs = {"luna": cached, "sol": values}
    refs, invalid_refs = references(repo, docs)
    overlay = load_jsonl(repo / "artifacts/luna-offline-rescore-v1/reference_adjudication_overlay.jsonl")
    corrected, applied = apply_overlay(docs, refs, overlay)
    reviews = {x["document_id"]: x for x in load_jsonl(repo / "artifacts/luna-round2-v1/source-review-final.jsonl")}
    scores, all_details = {}, {}
    for condition in ("original", "normalization_and_overlay"):
        scores[condition], all_details[condition] = {}, {}
        for name, output in outputs.items():
            projected, projection = project(output) if condition != "original" else (output, [])
            score, detail, audit = summarize(docs, projected, corrected if condition != "original" else refs, reviews)
            scores[condition][name], all_details[condition][name] = score, {d["document_id"]: d for d in detail}
            jsonl(root / condition / (name + "-mention-comparisons.jsonl"), detail)
            jsonl(root / condition / (name + "-fixed-assertion-audit.jsonl"), audit)
            if condition != "original":
                jsonl(root / (name + "-normalization-projection.jsonl"), projection)
    # The cached comparator must reproduce the separately sealed offline results exactly.
    old_metrics = read(repo / "artifacts/luna-offline-rescore-v1/metrics.json")
    for condition in scores:
        if scores[condition]["luna"] != old_metrics["systems"][condition]["grounded"]:
            raise ValueError("Frozen Luna scores changed")
    latencies = [r["latency"] for r in rows if r["latency"] is not None]
    usage, known = Counter(), 0
    for r in rows:
        u = json.loads(r["usage"]) if r["usage"] else None
        if u:
            known += 1
            usage.update({k: v for k, v in u.items() if type(v) is int})
    wall = sum(read(p)["wall_seconds"] for p in (root / "runs").glob("*.json"))
    new_execution = {"calls": len(rows), "documents_attempted": len(rows), "statuses": dict(Counter(r["status"] for r in rows)),
        "valid_documents": len(values), "coverage": len(values) / 100, "usage_known_requests": known,
        "tokens": dict(usage), "latency_mean_seconds": mean(latencies), "latency_median_seconds": median(latencies),
        "wall_seconds": wall, "valid_documents_per_minute": 60 * len(values) / wall,
        "actual_cost": None, "standard_credit_equivalent": credit_estimate(usage, m["cost_basis"]["standard_credits_per_million"]["gpt-6.1-sol"]),
        "credit_equivalent_scope": "documented rates applied to known reported usage; no actual bill or guaranteed included-quota conversion"}
    prior_execution = read(repo / "artifacts/luna-grounding-v3/comparison/metrics.json")["systems"]["grounded"]["execution"]
    prior_execution = {**prior_execution, "new_calls": 0,
        "standard_credit_equivalent": credit_estimate(prior_execution["tokens"], m["cost_basis"]["standard_credits_per_million"]["gpt-6-luna"])}
    jsonl(root / "predictions.jsonl", [{"document_id": d.document_id, "note_sha256": d.note_sha256,
        "status": next(r["status"] for r in rows if r["document_id"] == d.document_id), "result": values.get(d.document_id)} for d in docs])
    known_targets = {x["document_id"] for x in load_jsonl(repo / "artifacts/luna-grounding-v3/confirmed-semantic-fact-errors.jsonl")}
    known_targets.add("simsum:5359:text")
    queue = []
    relationships = Counter()
    for doc in docs:
        a = all_details["normalization_and_overlay"]["luna"][doc.document_id]
        b = all_details["normalization_and_overlay"]["sol"][doc.document_id]
        difference = len(b["missing_indices"]) + len(b["unmatched_indices"]) - len(a["missing_indices"]) - len(a["unmatched_indices"])
        relationships["sol_better" if difference < 0 else "luna_better" if difference > 0 else "tie"] += 1
        v, prior = values.get(doc.document_id), cached[doc.document_id]
        semantic = semantic_differences(v, prior) if v else []
        if doc.document_id in known_targets or not v or b["missing_indices"] or b["unmatched_indices"] or semantic:
            priority = (int(doc.document_id in known_targets), int(not v), max(difference, 0), int(bool(semantic)), len(b["missing_indices"]) + len(b["unmatched_indices"]))
            queue.append({"document_id": doc.document_id, "note_sha256": doc.note_sha256, "source_text": doc.text,
                "sol": v, "luna": prior, "comparison_luna": a, "comparison_sol": b, "semantic_difference_flags": semantic,
                "priority": list(priority), "known_luna_semantic_error_target": doc.document_id in known_targets,
                "status": "FLAGGED_NOT_AUTOMATICALLY_MODEL_ERROR", "unmatched_difference": difference})
    queue.sort(key=lambda x: (tuple(-v for v in x["priority"]), x["document_id"]))
    jsonl(root / "flagged-cases.jsonl", queue)
    jsonl(root / "review-queue.jsonl", queue[:20])
    metric = {"version": m["version"], "systems": scores, "execution": {"sol": new_execution, "luna": prior_execution},
        "invalid_reference_offsets": invalid_refs, "overlay_corrections": len(applied),
        "paired_score_relationships": dict(relationships), "flagged_documents": len(queue), "review_limit": 20,
        "new_model_calls": len(rows), "citation": {name: {"valid_facts": sum(len(v["facts"]) for v in outputs[name].values()),
            "exact_source_offsets_validated": True} for name in outputs},
        "scope": "same application-level contract; reused development benchmark; silver and fixed nonexpert assertion audit separate; no full clinical gold"}
    write_json(root / "metrics.json", metric, immutable=True)
    integrity(repo, root)
    return metric
