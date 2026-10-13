"""Silver symptom mentions only: concept equality + overlapping verified source spans."""
import json
from datetime import datetime
from collections import Counter
from pathlib import Path
from statistics import mean, median
from .dataset import sha, write_json
from .schema import ClinicalNoteExtraction
from .normalization import concept_group, NORMALIZATION_VERSION

SYMPTOMS = {"dyspnea", "cough", "respiratory pain", "fever", "nasal symptoms"}
EVALUATION_VERSION = "silver-canonical-concept-v1"
EVALUATION_V2 = "silver-grouped-unique-spans-v2"


def verified_annotations(document, annotations):
    valid, invalid = [], []
    for i, a in enumerate(annotations[document.row_id]):
        correct = (type(a.get("start")) is int and type(a.get("end")) is int
                   and 0 <= a["start"] < a["end"] <= len(document.text)
                   and document.text[a["start"]:a["end"]] == a["text"])
        (valid if correct else invalid).append({"annotation_index": i, **a})
    return valid, invalid


def match_mentions(predictions, references):
    # Maximum bipartite matching. One broad quotation cannot count twice for one concept.
    adjacent = [[j for j, r in enumerate(references)
                 if p["concept"] == r["symptom"]
                 and max(p["start"], r["start"]) < min(p["end"], r["end"])] for p in predictions]
    owners = {}
    def augment(i, seen):
        for j in adjacent[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owners or augment(owners[j], seen):
                owners[j] = i
                return True
        return False
    for i in range(len(predictions)):
        augment(i, set())
    return sorted((i, j) for j, i in owners.items())


def metrics(tp, predicted, expected):
    precision = tp / predicted if predicted else None
    recall = tp / expected if expected else None
    f1 = 2 * tp / (predicted + expected) if predicted + expected else None
    return {"true_positive": tp, "predicted": predicted, "reference": expected,
            "unmatched_prediction": predicted-tp, "missing_reference": expected-tp,
            "precision": precision, "recall": recall, "f1": f1}


def evaluate(documents, source_folder: Path, root: Path, ledger_rows, *, effective=False,
             version=EVALUATION_VERSION, output_root=None, batch=1):
    if version not in {EVALUATION_VERSION, EVALUATION_V2}:
        raise ValueError("Unknown evaluation version")
    grouped = version == EVALUATION_V2
    output_root = output_root or root
    annotations = {"text": json.loads((source_folder / "normal_span_annotations.json").read_text(encoding="utf-8")),
                   "advanced_text": json.loads((source_folder / "adv_span_annotations.json").read_text(encoding="utf-8"))}
    per_doc, mismatch, details, prediction_hashes = [], [], [], {}
    categories, polarity, temporality, experiencer = Counter(), Counter(), Counter(), Counter()
    citation_valid, citation_total, invalid_reference_total = 0, 0, 0
    coverage_examples = {}
    label = "effective" if effective else "first"
    evaluation_folder = output_root / "evaluation" / label
    ledger_by_id = {r["document_id"]: r for r in ledger_rows if effective or r["attempt"] == 1}
    for d in documents:
        refs, bad_refs = verified_annotations(d, annotations[d.variant])
        invalid_reference_total += len(bad_refs)
        attempt = ledger_by_id.get(d.document_id, {}).get("attempt", 1)
        folder = root / "requests" / d.document_id.replace(":", "_") / f"attempt-{attempt}"
        result = None
        raw_path = folder / "raw-response.json"
        if raw_path.exists():
            prediction_hashes[d.document_id] = sha(raw_path.read_bytes())
            try:
                candidate = ClinicalNoteExtraction.model_validate_json(raw_path.read_text(encoding="utf-8"))
                if candidate.document_id == d.document_id:
                    result = candidate
            except ValueError:
                pass
        predicted = []
        bad_citations = []
        if result:
            for i, f in enumerate(result.facts):
                categories[f.category] += 1
                polarity[f.polarity] += 1
                temporality[f.temporality] += 1
                experiencer[f.experiencer] += 1
                coverage_examples.setdefault(f.category, {"document_id": d.document_id, "fact_index": i,
                                                         "fact": f.model_dump()})
                e = f.evidence
                citation_total += 1
                correct = 0 <= e.start < e.end <= len(d.text) and d.text[e.start:e.end] == e.quote
                citation_valid += correct
                if not correct:
                    bad_citations.append({"fact_index": i, "fact": f.model_dump()})
                group = concept_group(f.concept) if grouped else f.concept
                if group in SYMPTOMS:
                    # Invalid evidence remains an unmatched prediction, never silently disappears.
                    predicted.append({"fact_index": i, "concept": group,
                                      **({"concept_group": group} if grouped else {}),
                                      "start": e.start if correct else -1, "end": e.end if correct else -1,
                                      "citation_valid": correct, "fact": f.model_dump()})
        fact_predicted = predicted
        fact_pairs = match_mentions(fact_predicted, refs)
        if grouped:
            # Mention = unique group + exact evidence interval, not one assertion/qualifier.
            # Polarity and all assertions remain in facts/fact_indices for review, never merged into a boolean.
            unique = {}
            for p in predicted:
                key = (p["concept"], p["start"], p["end"]) if p["citation_valid"] else ("invalid", p["fact_index"])
                if key not in unique:
                    unique[key] = {**p, "fact_indices": []}
                unique[key]["fact_indices"].append(p["fact_index"])
            predicted = list(unique.values())
        pairs = match_mentions(predicted, refs)
        matched_pred, matched_ref = {i for i, _ in pairs}, {j for _, j in pairs}
        pconcepts, rconcepts = {p["concept"] for p in predicted}, {r["symptom"] for r in refs}
        row = {"document_id": d.document_id, "row_id": d.row_id, "variant": d.variant,
               "status": ledger_by_id.get(d.document_id, {}).get("status", "unattempted"),
               "mention": metrics(len(pairs), len(predicted), len(refs)),
               "concept": metrics(len(pconcepts & rconcepts), len(pconcepts), len(rconcepts)),
               "per_concept": {c: metrics(sum(predicted[i]["concept"] == c for i, _ in pairs),
                   sum(p["concept"] == c for p in predicted), sum(r["symptom"] == c for r in refs)) for c in sorted(SYMPTOMS)},
               "invalid_references": len(bad_refs)}
        if grouped:
            row["fact_mention"] = metrics(len(fact_pairs), len(fact_predicted), len(refs))
        per_doc.append(row)
        missing = [r for j, r in enumerate(refs) if j not in matched_ref]
        additional = [p for i, p in enumerate(predicted) if i not in matched_pred]
        detail = {**row, "missing": missing, "additional": additional,
                  "invalid_reference_spans": bad_refs, "invalid_citations": bad_citations,
                  "error": ledger_by_id.get(d.document_id, {}).get("error")}
        details.append(detail)
        if missing or additional or bad_refs or bad_citations or row["status"] != "valid":
            mismatch.append(detail)
    prediction_freeze_hash = sha(json.dumps(prediction_hashes, sort_keys=True))
    write_json(output_root / f"predictions-freeze-{label}-{prediction_freeze_hash}.json", prediction_hashes, immutable=True)
    write_json(evaluation_folder / "documents.json", per_doc)
    write_json(evaluation_folder / "mismatches.json", mismatch)
    # Provider failures are audited separately; avoid filling clinical review with duplicate startup errors.
    # Freeze 20 completed mismatches, 10 per variant, with a fixed deterministic ranking.
    sample = []
    for variant in ("text", "advanced_text"):
        choices = [m for m in mismatch if m["variant"] == variant and m["status"] in {"valid", "invalid"}]
        choices.sort(key=lambda m: (-int(bool(m["invalid_citations"] or m["error"])),
                     -(len(m["missing"]) + len(m["additional"]) + len(m["invalid_reference_spans"])),
                     sha(("review-v2:" if grouped else "review-v1:")+m["document_id"])))
        sample.extend(choices[:10])
    ids_path = output_root / ("review-document-ids-v2.json" if grouped else "review-document-ids-v1.json")
    if not ids_path.exists():
        write_json(ids_path, [m["document_id"] for m in sample], immutable=True)
    sample_ids = json.loads(ids_path.read_text(encoding="utf-8"))
    detail_by_id = {m["document_id"]: m for m in details}
    sample = [detail_by_id[i] for i in sample_ids]
    sample_path = evaluation_folder / f"review-{'grouped-v2' if grouped else 'canonical-v1'}-{prediction_freeze_hash[:16]}.json"
    write_json(sample_path, sample, immutable=True)
    summary = {"evaluation_version": version,
               "prediction_freeze_sha256": prediction_freeze_hash, "review_sample_path": str(sample_path),
               "reference_invalid_spans": invalid_reference_total,
               "citation": {"valid": citation_valid, "total": citation_total,
                            "rate": citation_valid/citation_total if citation_total else None},
               "facts_by_category": dict(categories), "polarity": dict(polarity),
               "temporality": dict(temporality), "experiencer": dict(experiencer),
               "coverage_examples": coverage_examples,
               "interpretation": "Five canonical respiratory concepts across all universal fact categories; silver concept+span overlap, one-to-one; not clinical accuracy. No reference polarity, temporality or experiencer labels. Invalid reference spans excluded without correction. Missing/failed outputs count toward recall denominator.",
               "groups": {}}
    if grouped:
        summary["normalization_version"] = NORMALIZATION_VERSION
        summary["interpretation"] = ("Silver grouped-concept + overlapping verified source span, one-to-one. "
            "Mention predictions deduplicate identical group/start/end intervals only; all original facts and polarities retained. "
            "Document concepts are sets of groups regardless of status; reference has no polarity/temporality/experiencer labels. "
            "Primary groups include completed responses (valid or structurally invalid), excluding infrastructure failures and unattempted notes. "
            "All-selected end-to-end coverage is reported separately. Invalid citations remain unmatched; bad reference offsets excluded without correction. "
            "These are silver estimates, not clinical accuracy; grouped quote spans may still be coarser than true symptom mentions.")
        summary["all_selected_groups"] = {}
    for label, variant in (("overall", None), ("standard", "text"), ("advanced", "advanced_text")):
        rows = [r for r in per_doc if variant is None or r["variant"] == variant]
        if grouped:
            summary["all_selected_groups"][label] = {"documents": len(rows), **{metric: metrics(*[
                sum(r[metric][k] for r in rows) for k in ("true_positive", "predicted", "reference")])
                for metric in ("mention", "concept", "fact_mention")}}
            rows = [r for r in rows if r["status"] in {"valid", "invalid"}]
        summary["groups"][label] = {"documents": len(rows)}
        for metric in (("mention", "concept", "fact_mention") if grouped else ("mention", "concept")):
            summary["groups"][label][metric] = metrics(*[sum(r[metric][k] for r in rows)
                                                    for k in ("true_positive", "predicted", "reference")])
        summary["groups"][label]["per_concept"] = {c: metrics(*[sum(r["per_concept"][c][k] for r in rows)
            for k in ("true_positive", "predicted", "reference")]) for c in sorted(SYMPTOMS)}
    statuses = Counter(r["status"] for r in ledger_by_id.values())
    usages = [json.loads(r["usage"]) for r in ledger_rows if r["usage"] and json.loads(r["usage"]) is not None]
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in (root / "runs").glob("*.json")]
    active_run_seconds = sum(r["wall_seconds"] for r in runs)
    wall = (max(datetime.fromisoformat(r["ended_at"]) for r in runs)
            - min(datetime.fromisoformat(r["started_at"]) for r in runs)).total_seconds() if runs else 0
    latencies = [r["latency_seconds"] for r in ledger_rows if r["latency_seconds"] is not None]
    inference_turns = 0
    for r in ledger_rows:
        events_path = root / "requests" / r["document_id"].replace(":", "_") / f"attempt-{r['attempt']}" / "events.jsonl"
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                try:
                    inference_turns += json.loads(line).get("type") == "turn.started"
                except json.JSONDecodeError:
                    pass
    summary["execution"] = {"selected": len(documents), "attempted": len(ledger_by_id),
        "completed": statuses["valid"]+statuses["invalid"], "failed": statuses["failed"],
        "reserved_ambiguous": statuses["reserved"], "unattempted": len(documents)-len(ledger_by_id),
        "valid": statuses["valid"], "invalid": statuses["invalid"],
        "provider_dispatches": len(ledger_rows), "structural_retry_dispatches": sum(r["attempt"] == 2 for r in ledger_rows),
        "cli_inference_turns_started": inference_turns,
        "dispatch_records": sum((root / "requests" / r["document_id"].replace(":", "_") / f"attempt-{r['attempt']}" / "dispatch.json").exists() for r in ledger_rows),
        "usage_records": len(usages), "tokens_observed": {k: sum(u.get(k, 0) for u in usages) if usages else None
                          for k in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")},
        "usage_complete": len(usages) == len(ledger_rows) and bool(ledger_rows),
        "wall_seconds": wall, "throughput_documents_per_minute": len(ledger_by_id)*60/wall if wall else None,
        "active_run_seconds": active_run_seconds,
        "throughput_completed_per_minute": (statuses["valid"]+statuses["invalid"])*60/wall if wall else None,
        "latency_mean_seconds": mean(latencies) if latencies else None,
        "latency_median_seconds": median(latencies) if latencies else None,
        "latency_max_seconds": max(latencies) if latencies else None,
        "cost_usd": None, "cost_basis": "Codex subscription billing is not exposed; no verified Luna price basis used for an estimate",
        "blockers": [r["blocker"] for r in runs if r["blocker"]]}
    if grouped:
        summary["execution"]["attempt_statuses"] = dict(Counter(r["status"] for r in ledger_rows))
        summary["execution"]["latency_by_attempt_status"] = {}
        for status in ("valid", "invalid", "failed"):
            values = [r["latency_seconds"] for r in ledger_rows
                      if r["status"] == status and r["latency_seconds"] is not None]
            summary["execution"]["latency_by_attempt_status"][status] = {
                "count": len(values), "mean_seconds": mean(values) if values else None,
                "median_seconds": median(values) if values else None,
                "max_seconds": max(values) if values else None}
    write_json(evaluation_folder / "summary.json", summary)
    write_report(summary, evaluation_folder / "report.md", label, batch=batch)
    return summary


def write_report(summary, path, label, *, batch=1):
    e = summary["execution"]
    def percent(value):
        return "unavailable" if value is None else f"{value:.2%}"
    lines = [f"# Clinical note Batch {batch} — {label} attempts", "",
        f"Selected {e['selected']}; attempted {e['attempted']}; completed {e['completed']}; failed {e['failed']}; unattempted {e['unattempted']}.",
        f"Valid responses {e['valid']}; invalid responses {e['invalid']}; ambiguous reservations {e['reserved_ambiguous']}.",
        f"Application dispatches {e['provider_dispatches']}; structural retries {e['structural_retry_dispatches']}; CLI inference turns started {e['cli_inference_turns_started']}.", "",
        "| Notes | Symptom TP / predicted / reference | Precision | Recall | F1 |",
        "| --- | --- | --- | --- | --- |"]
    for group, values in summary["groups"].items():
        m = values["mention"]
        lines.append(f"| {group} | {m['true_positive']} / {m['predicted']} / {m['reference']} | {percent(m['precision'])} | {percent(m['recall'])} | {percent(m['f1'])} |")
    c = summary["citation"]
    lines.extend(["", f"Exact citations: {c['valid']}/{c['total']} ({percent(c['rate'])}). Invalid reference spans: {summary['reference_invalid_spans']}.",
        f"Wall time {e['wall_seconds']:.3f} seconds; active execution {e['active_run_seconds']:.3f} seconds.",
        f"Completed documents/minute: {e['throughput_completed_per_minute']}. Request mean/median/max seconds: {e['latency_mean_seconds']} / {e['latency_median_seconds']} / {e['latency_max_seconds']}.",
        f"Observed tokens: {json.dumps(e['tokens_observed'], sort_keys=True)}. Usage complete: {e['usage_complete']}.",
        f"Cost: unavailable. {e['cost_basis']}.", "", summary["interpretation"], "",
        f"Category coverage: {json.dumps(summary['facts_by_category'], sort_keys=True)}. No accuracy scores are assigned to unlabelled categories.",
        f"Frozen review sample: {summary['review_sample_path']}.",
        f"Prediction freeze: {summary['prediction_freeze_sha256']}.", ""])
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
