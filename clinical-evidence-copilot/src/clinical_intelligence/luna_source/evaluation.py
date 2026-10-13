"""Corrected common scorer, unchanged mention geometry, separate source review."""
import json
import sqlite3
from collections import Counter
from statistics import mean, median
from .contract import CONFIG, EFFORTS, PROMOTION_RULE, primary_projection, validate_resolved
from .runtime import integrity, rows, folder, read, jsonl
from ..clinical_notes.dataset import sha, write_json
from ..luna_round2.evaluation import baseline, summarize
from ..luna_grounding.evaluation import semantic_differences
from ..luna_rescore.evaluation import project, apply_overlay
from ..simsum_comparison.__main__ import documents
from ..simsum_comparison.evaluation import references, load_jsonl


def execution(requests):
    usage = [json.loads(r["usage"]) for r in requests if r["usage"] and json.loads(r["usage"]) is not None]
    tokens = Counter()
    for u in usage:
        tokens.update({k: v for k, v in u.items() if type(v) is int})
    latencies = [r.get("latency", r.get("latency_seconds")) for r in requests]
    latencies = [x for x in latencies if x is not None]
    return {"calls": len(requests), "statuses": dict(Counter(r["status"] for r in requests)),
        "latency_median_seconds": median(latencies) if latencies else None,
        "latency_mean_seconds": mean(latencies) if latencies else None,
        "summed_request_seconds": sum(latencies), "usage_known_requests": len(usage), "tokens": dict(tokens),
        "cost_usd": None, "cost_scope": "subscription billing unavailable; reasoning tokens included in output tokens"}


def evaluate(repo, root, phase):
    m = integrity(repo, root)
    docs = documents(repo)
    if phase == "comparison":
        docs = [d for d in docs if d.document_id in m["comparison_ids"]]
        names = list(EFFORTS)
    elif phase == "final":
        names = [read(root / "winner-freeze.json")["winner"]]
    else:
        raise ValueError("Unknown phase")
    requests = rows(root)
    originals = {"historical_single_pass_effective": baseline(repo, docs),
                 "historical_single_pass_first": baseline(repo, docs, first=True)}
    for name in names:
        own = [r for r in requests if r["stage"] == phase + "." + name]
        if {r["document_id"] for r in own} != {d.document_id for d in docs} or any(r["status"] == "reserved" for r in own):
            raise ValueError("Every selected document requires a terminal outcome")
        values, predictions = {}, []
        for doc in docs:
            r = next(r for r in own if r["document_id"] == doc.document_id)
            directory = folder(root, phase, name, doc.document_id)
            if (directory / "raw-response.json").exists() and sha((directory / "raw-response.json").read_bytes()) != r["raw_hash"]:
                raise ValueError("Raw response changed")
            if r["status"] == "valid":
                values[doc.document_id] = validate_resolved(read(directory / "result.json"), doc)
            predictions.append({"document_id": doc.document_id, "note_sha256": doc.note_sha256,
                                "status": r["status"], "result": values.get(doc.document_id)})
        originals[name] = {i: primary_projection(v) for i, v in values.items()}
        jsonl(root / phase / name / "predictions.jsonl", predictions)
    refs, invalid_refs = references(repo, docs)
    overlay = load_jsonl(repo / "artifacts/luna-offline-rescore-v1/reference_adjudication_overlay.jsonl")
    corrected, applied = apply_overlay(docs, refs, [x for x in overlay if x["document_id"] in refs])
    reviews = {r["document_id"]: r for r in load_jsonl(repo / "artifacts/luna-round2-v1/source-review-final.jsonl")}
    systems, details, audited_details = {}, {}, {}
    for name, output in originals.items():
        projected, changes = project(output)
        original_score, _, _ = summarize(docs, projected, refs, reviews)
        metric, detail, audit = summarize(docs, projected, corrected, reviews)
        systems[name] = {"original_silver": original_score["silver"], "corrected": metric["silver"],
                         "fixed_source_audit": metric["audited"]}
        details[name], audited_details[name] = detail, audit
        jsonl(root / phase / (name + "-mention-comparisons.jsonl"), detail)
        jsonl(root / phase / (name + "-assertion-audit.jsonl"), audit)
        jsonl(root / phase / (name + "-normalization-projection.jsonl"), changes)
        if name in names:
            own = [r for r in requests if r["stage"] == phase + "." + name]
            systems[name]["execution"] = execution(own)
            systems[name]["execution"]["new_calls"] = len(own)
            systems[name]["execution"]["wall_seconds"] = sum(read(p)["wall_seconds"] for p in
                (root / phase / name / "runs").glob("*.json") if read(p)["new_dispatches"])
            systems[name]["grounding"] = {"facts": sum(len(v["facts"]) for v in output.values()),
                "source_spans": sum(len(read(folder(root, phase, name, i) / "offset-provenance.json")[j]["spans"])
                                    for i, v in output.items() for j in range(len(v["facts"]))),
                "valid_outputs_exact_source": len(output), "reconstructed_quotes": 0,
                "semantic_support": "requires source review; exact location is not proof"}
        else:
            with sqlite3.connect(f"file:{(repo / 'artifacts/clinical-notes-v2/requests.sqlite3').as_posix()}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                old = [dict(r) for r in db.execute("SELECT * FROM requests") if r["document_id"] in refs
                       and (not name.endswith("first") or r["attempt"] == 1)]
            systems[name]["execution"] = {**execution(old), "new_calls": 0, "wall_seconds": None}
        if phase == "final":
            systems[name]["subsets"] = {label: summarize(sub, projected, corrected, reviews)[0] for label, sub in (
                ("initial_100", [d for d in docs if d.document_id in m["comparison_ids"]]),
                ("remaining_200", [d for d in docs if d.document_id not in m["comparison_ids"]]))}
    if phase == "comparison":
        previous = read(repo / "artifacts/luna-offline-rescore-v1/metrics.json")["systems"]["normalization_and_overlay"]
        for name in ("historical_single_pass_effective", "historical_single_pass_first"):
            if systems[name]["corrected"] != previous[name]["silver"] or systems[name]["fixed_source_audit"] != previous[name]["audited"]:
                raise ValueError("Corrected historical baseline failed exact reproduction")
    flagged = []
    by_doc = {name: {r["document_id"]: r for r in ds} for name, ds in details.items()}
    known_controls = {"simsum:5359:text", "simsum:192:advanced_text", "simsum:4240:text",
                      "simsum:1764:advanced_text", "simsum:9268:text"}
    for doc in docs:
        reasons, diffs = [], {}
        for name in names:
            r = by_doc[name][doc.document_id]
            if doc.document_id not in originals[name]: reasons.append(name + ": unavailable output")
            if r["missing_indices"] or r["unmatched_indices"]: reasons.append(name + ": reference disagreement")
            a = originals[name].get(doc.document_id)
            b = originals["historical_single_pass_effective"].get(doc.document_id)
            if a and b:
                diffs[name] = semantic_differences(a, b)
                if diffs[name]: reasons.append(name + ": baseline semantic disagreement")
        if len(names) == 2 and all(doc.document_id in originals[n] for n in names):
            diffs["A_vs_B"] = semantic_differences(originals["A"][doc.document_id], originals["B"][doc.document_id])
            if diffs["A_vs_B"]: reasons.append("A/B semantic disagreement")
        if doc.document_id in known_controls: reasons.append("previous source-confirmed failure mechanism")
        if reasons:
            missing_output = any(doc.document_id not in originals[n] for n in names)
            discrepancy = sum(len(by_doc[n][doc.document_id]["missing_indices"]) +
                              len(by_doc[n][doc.document_id]["unmatched_indices"]) for n in names)
            flagged.append({"document_id": doc.document_id, "note_sha256": doc.note_sha256,
                "source_text": doc.text, "reasons": reasons, "semantic_differences": diffs,
                "systems": {n: originals[n].get(doc.document_id) for n in originals},
                "comparisons": {n: by_doc[n][doc.document_id] for n in originals},
                "operational_errors": {n: next(r["error"] for r in requests if r["stage"] == phase + "." + n
                                               and r["document_id"] == doc.document_id) for n in names},
                "priority": [int(missing_output), int(doc.document_id in known_controls), int(any(diffs.values())), discrepancy],
                "status": "UNRESOLVED_UNTIL_SOURCE_REVIEW", "model_error_category": None,
                "omission_categories": [1, 2], "independent_identify_trace": False})
    flagged.sort(key=lambda r: (tuple(-v for v in r["priority"]), r["document_id"]))
    jsonl(root / phase / "flagged-cases.jsonl", flagged)
    jsonl(root / phase / "review-queue.jsonl", flagged[:PROMOTION_RULE["review_cap"]])
    result = {"version": m["version"], "phase": phase, "systems": systems,
              "reference_overlay_applied": len(applied), "invalid_original_reference_offsets": invalid_refs,
              "flagged_documents": len(flagged), "review_selected": min(len(flagged), PROMOTION_RULE["review_cap"]),
              "new_dispatches": len(requests), "unflagged_successes_manually_reviewed": 0,
              "scope": "five symptom mention sets; partial nonexpert source audit; full universal accuracy unavailable"}
    write_json(root / phase / "metrics.json", result, immutable=True)
    integrity(repo, root)
    return result


def gate_checks(candidate, previous):
    c, p = candidate["corrected"]["all"], previous["corrected"]["all"]
    ca, pa = candidate["fixed_source_audit"], previous["fixed_source_audit"]
    return {"meaningful_corrected_f1_gain": c["overlap"]["f1"] - p["overlap"]["f1"] >= PROMOTION_RULE["minimum_f1_gain"],
            "more_complete_cases": c["complete_mention_cases"] >= p["complete_mention_cases"] + PROMOTION_RULE["minimum_complete_case_gain"],
            "structural_noninferiority": c["structural_success_rate"] >= p["structural_success_rate"],
            "fixed_audit_noninferiority": ca["f1"] >= pa["f1"] and ca["complete_cases"] >= pa["complete_cases"]}


def select(root, phase="comparison"):
    metrics = read(root / phase / "metrics.json")
    review = load_jsonl(root / phase / "source-review-decisions.jsonl")
    queue = load_jsonl(root / phase / "review-queue.jsonl")
    if {r["document_id"] for r in review} != {r["document_id"] for r in queue}:
        raise ValueError("Complete the frozen flagged-case source review")
    names = list(EFFORTS) if phase == "comparison" else [read(root / "winner-freeze.json")["winner"]]
    checks = {}
    for name in names:
        checks[name] = gate_checks(metrics["systems"][name], metrics["systems"]["historical_single_pass_effective"])
        checks[name]["no_important_clinical_regression"] = not any(
            f.get("important_regression", False) and f["system"] == name for r in review for f in r["findings"])
    eligible = [n for n in names if all(checks[n].values())]
    winner = max(eligible, key=lambda n: (metrics["systems"][n]["fixed_source_audit"]["f1"],
        metrics["systems"][n]["corrected"]["all"]["overlap"]["f1"],
        metrics["systems"][n]["corrected"]["all"]["complete_mention_cases"], n == "A")) if eligible else None
    result = {"promote": bool(winner), "winner": winner, "checks": checks,
        "manifest_sha256": sha((root / "manifest.json").read_bytes()),
        "metrics_sha256": sha((root / phase / "metrics.json").read_bytes()),
        "review_sha256": sha((root / phase / "source-review-decisions.jsonl").read_bytes()),
        "rule": PROMOTION_RULE, "unreviewed_flags_remain_unresolved": True,
        "recommended_baseline": winner if winner and phase == "final" else "historical Single-pass v2 pending confirmation" if winner else "historical Single-pass v2"}
    write_json(root / ("winner-freeze.json" if phase == "comparison" else "final-decision.json"), result, immutable=True)
    return result
