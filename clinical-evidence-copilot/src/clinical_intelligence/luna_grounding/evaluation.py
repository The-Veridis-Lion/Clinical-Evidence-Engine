"""Unchanged evaluation contract; bounded error-only review and frozen promotion gate."""
import json
import sqlite3
from collections import Counter
from statistics import mean, median

from .contract import PROMOTION_RULE
from .runtime import read, jsonl, folder, integrity
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.schema import validate_extraction
from ..luna_round2.evaluation import baseline, summarize, ledger_rows
from ..simsum_comparison.__main__ import documents
from ..simsum_comparison.evaluation import references, load_jsonl


def gate_checks(candidate, previous):
    a, b = candidate["silver"]["all"], previous["silver"]["all"]
    return {"operational_f1_strictly_better": a["overlap"]["f1"] > b["overlap"]["f1"],
            "structural_success_not_lower": a["structural_success_rate"] >= b["structural_success_rate"],
            "audited_f1_not_lower": candidate["audited"]["f1"] >= previous["audited"]["f1"],
            "audited_complete_case_rate_not_lower": candidate["audited"]["complete_case_rate"] >= previous["audited"]["complete_case_rate"]}


def semantic_differences(new, old):
    """Flags only: a baseline difference is never automatically declared an error."""
    differences = []
    for i, f in enumerate(new["facts"]):
        same = [(j, b) for j, b in enumerate(old["facts"])
                if f["concept"] is not None and f["concept"] == b["concept"]
                and f["evidence"]["start"] < b["evidence"]["end"]
                and b["evidence"]["start"] < f["evidence"]["end"]]
        keys = ("polarity", "temporality", "experiencer")
        if same and not any(all(f[k] == b[k] for k in keys) for _, b in same):
            differences.append({"new_fact_index": i, "baseline_fact_indices": [j for j, _ in same],
                                "dimensions": list(keys), "status": "REQUIRES_SOURCE_REVIEW_NOT_PROVEN_ERROR"})
    return differences


def evaluate(repo, root, phase):
    m = integrity(repo, root)
    docs = documents(repo)
    if phase == "comparison":
        docs = [d for d in docs if d.document_id in m["comparison_ids"]]
    rows = ledger_rows(root, phase)
    if {r["document_id"] for r in rows} != {d.document_id for d in docs} or any(r["status"] == "reserved" for r in rows):
        raise ValueError("All selected documents require terminal outcomes")
    values = {}
    for r in rows:
        p = folder(root, phase, r["document_id"])
        if (p / "raw-response.json").exists():
            assert sha((p / "raw-response.json").read_bytes()) == r["raw_hash"]
        if r["status"] == "valid":
            values[r["document_id"]] = validate_extraction(json.dumps(read(p / "result.json")),
                                                         next(d for d in docs if d.document_id == r["document_id"])).model_dump()
    refs, invalid_refs = references(repo, docs)
    reviews = {r["document_id"]: r for r in load_jsonl(repo / "artifacts/luna-round2-v1/source-review-final.jsonl")}
    systems, details, audit_details = {}, {}, {}
    cached = {}
    for name, output in (("grounded", values), ("historical_single_pass_effective", baseline(repo, docs)),
                         ("historical_single_pass_first", baseline(repo, docs, first=True))):
        cached[name] = output
        systems[name], details[name], audit_details[name] = summarize(docs, output, refs, reviews)
        if phase == "final":
            systems[name]["subsets"] = {label: summarize(sub, output, refs, reviews)[0]
                for label, sub in (("selection_100", [d for d in docs if d.document_id in m["comparison_ids"]]),
                                   ("remaining_200", [d for d in docs if d.document_id not in m["comparison_ids"]]))}
    runs = [read(p) for p in (root / phase / "runs").glob("*.json")]
    wall = sum(r["wall_seconds"] for r in runs if r["new_dispatches"])
    latencies = [r["latency"] for r in rows if r["latency"] is not None]
    usages = [json.loads(r["usage"]) for r in rows if r["usage"] and json.loads(r["usage"]) is not None]
    totals = Counter()
    for usage in usages:
        totals.update({k: v for k, v in usage.items() if isinstance(v, int)})
    systems["grounded"]["execution"] = {"calls": len(rows), "statuses": dict(Counter(r["status"] for r in rows)),
        "coverage": len(values) / len(docs), "wall_seconds": wall,
        "latency_mean_seconds": mean(latencies), "latency_median_seconds": median(latencies),
        "valid_documents_per_minute": 60 * len(values) / wall if wall else None,
        "usage_known_requests": len(usages), "tokens": dict(totals), "cost": None,
        "cost_limitation": "subscription provider; documented per-token billing not available"}
    systems["grounded"]["citation"] = {"valid_normalized_facts": sum(len(v["facts"]) for v in values.values()),
        "all_saved_offsets_exact": True, "semantic_support_not_established_by_exact_citation": True}
    with sqlite3.connect(f"file:{(repo / 'artifacts/clinical-notes-v2/requests.sqlite3').as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        historical_rows = [dict(r) for r in db.execute("SELECT * FROM requests")
                           if r["document_id"] in {d.document_id for d in docs}]
    for name, first_only in (("historical_single_pass_first", True), ("historical_single_pass_effective", False)):
        used = [r for r in historical_rows if not first_only or r["attempt"] == 1]
        latency = [r["latency_seconds"] for r in used if r["latency_seconds"] is not None]
        systems[name]["execution"] = {"new_calls": 0, "historical_calls": len(used),
            "latency_mean_seconds": mean(latency) if latency else None,
            "latency_median_seconds": median(latency) if latency else None,
            "wall_seconds": None, "wall_limitation": "cached subset of a historical concurrent run; no comparable subset wall time"}
    output = {"version": m["version"], "phase": phase, "systems": systems,
              "promotion_rule": PROMOTION_RULE, "invalid_reference_offsets": invalid_refs,
              "scorer_unchanged": True, "metrics_scope": "five symptom mentions; source-audited polarity/subject subset; universal-fact accuracy unavailable"}
    write_json(root / phase / "metrics.json", output, immutable=True)
    for name in systems:
        jsonl(root / phase / (name + "-silver-comparisons.jsonl"), details[name])
        jsonl(root / phase / (name + "-audited-comparisons.jsonl"), audit_details[name])
    jsonl(root / phase / "predictions.jsonl", [{"document_id": d.document_id, "note_sha256": d.note_sha256,
          "status": next(r["status"] for r in rows if r["document_id"] == d.document_id),
          "result": values.get(d.document_id)} for d in docs])
    old_details = {r["document_id"]: r for r in details["historical_single_pass_effective"]}
    reviewed = {r["document_id"]: r for r in audit_details["grounded"]}
    flagged, structural = [], []
    for d, detail in zip(docs, details["grounded"]):
        v, b = values.get(d.document_id), cached["historical_single_pass_effective"].get(d.document_id)
        missing, unmatched = detail["missing_indices"], detail["unmatched_indices"]
        differences = semantic_differences(v, b) if v and b else []
        audited = reviewed.get(d.document_id)
        audit_bad = audited is not None and not audited["complete"]
        r = next(r for r in rows if r["document_id"] == d.document_id)
        if r["status"] == "invalid":
            structural.append({"document_id": d.document_id, "primary_root_cause": 4,
                               "status": "CONFIRMED_STRUCTURAL_FAILURE", "error": r["error"], "raw_sha256": r["raw_hash"]})
        if not v or missing or unmatched or differences or audit_bad:
            previous = old_details[d.document_id]
            regression = len(missing) + len(unmatched) - len(previous["missing_indices"]) - len(previous["unmatched_indices"])
            priority = (int(not v), int(audit_bad), int(bool(differences)), max(regression, 0), len(missing) + len(unmatched))
            flagged.append({"document_id": d.document_id, "variant": d.variant,
                "status": "UNRESOLVED_SOURCE_REVIEW_REQUIRED", "operational_status": r["status"],
                "priority": list(priority), "silver_comparison": detail, "baseline_silver_comparison": previous,
                "semantic_difference_flags": differences, "fixed_source_audit": audited,
                "source_text": d.text, "candidate": v, "baseline": b,
                "note_sha256": d.note_sha256, "four_category_attribution": None,
                "direct_identify_trace_observable": False})
    flagged.sort(key=lambda f: (tuple(-x for x in f["priority"]), f["document_id"]))
    jsonl(root / phase / "flagged-cases.jsonl", flagged)
    jsonl(root / phase / "review-queue.jsonl", flagged[:PROMOTION_RULE["review_cap_per_phase"]])
    jsonl(root / phase / "structural-error-attribution.jsonl", structural)
    known = load_jsonl(repo / "artifacts/luna-round2-v1/manual-source-review-v2.jsonl")
    jsonl(root / phase / "historical-reference-overlay.jsonl", [x for x in known
          if x["document_id"] in {d.document_id for d in docs}
          and x["status"].startswith("REFERENCE_")])
    write_json(root / phase / "review-selection.json", {"flagged_documents": len(flagged),
        "selected_document_ids": [f["document_id"] for f in flagged[:PROMOTION_RULE["review_cap_per_phase"]]],
        "successful_unflagged_documents_manually_reviewed": 0,
        "method": "frozen priority: operational unavailable, fixed-audit discrepancy, baseline semantic difference, silver regression, discrepancy count"}, immutable=True)
    integrity(repo, root)
    return output


def promote(root):
    m = read(root / "comparison/metrics.json")
    checks = gate_checks(m["systems"]["grounded"], m["systems"]["historical_single_pass_effective"])
    reviewed = load_jsonl(root / "comparison/source-review-decisions.jsonl")
    selected = read(root / "comparison/review-selection.json")["selected_document_ids"]
    if set(selected) != {r["document_id"] for r in reviewed}:
        raise ValueError("Finish the bounded flagged-case source review before promotion")
    checks["no_additional_confirmed_semantic_regression"] = not any(r["additional_semantic_regression"] for r in reviewed)
    decision = {"promote": all(checks.values()), "checks": checks,
        "manifest_sha256": sha((root / "manifest.json").read_bytes()),
        "metrics_sha256": sha((root / "comparison/metrics.json").read_bytes()),
        "source_review_sha256": sha((root / "comparison/source-review-decisions.jsonl").read_bytes()),
        "rule": PROMOTION_RULE, "remaining_disagreements_unresolved": True,
        "scope": "selection on reused development data; no full universal clinical gold"}
    write_json(root / "promotion.json", decision, immutable=True)
    print(json.dumps(decision, indent=2))
    return decision
