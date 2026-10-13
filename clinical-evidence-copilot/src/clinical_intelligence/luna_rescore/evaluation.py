"""Apply explicit evaluation projections and source-audited reference overlays.

The historical one-to-one scorer, operational denominator and assertion scoring
are reused unchanged. No prediction, prompt, schema, or original label is edited.
"""
from copy import deepcopy
from collections import Counter
from pathlib import Path
import json
import sqlite3

from . import VERSION, NORMALIZATION_VERSION
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.normalization import CONCEPT_GROUPS
from ..clinical_notes.schema import validate_extraction
from ..luna_round2.evaluation import baseline, summarize
from ..luna_grounding.runtime import integrity
from ..simsum_comparison.__main__ import documents
from ..simsum_comparison.contract import stable_hash, DEFINITIONS
from ..simsum_comparison.evaluation import references, load_jsonl, jsonl

GROUPS = {**CONCEPT_GROUPS, "chest pain": "respiratory pain"}
CONDITIONS = {
    "original": (False, False),
    "normalization_only": (True, False),
    "reference_overlay_only": (False, True),
    "normalization_and_overlay": (True, True),
}


def concept_group(concept):
    return GROUPS.get(concept.strip().casefold()) if concept is not None else None


def project(results):
    """Temporary input adapter for the unchanged historical scorer.

    Only the new alias needs projection: all existing aliases and their fact-level
    deduplication retain historical behavior. Stored source facts never change.
    Positive/negative assertions, original terms, and all source spans remain distinct.
    """
    projected = deepcopy(results)
    changes = []
    for doc_id, output in projected.items():
        for i, fact in enumerate(output["facts"]):
            if fact["concept"] is not None and fact["concept"].strip().casefold() == "chest pain":
                changes.append({"document_id": doc_id, "fact_index": i,
                                "source_fact": deepcopy(fact),
                                "concept_group": "respiratory pain"})
                fact["concept"] = "respiratory pain"
    return projected, changes


def check_evidence(doc, evidence):
    start, end = evidence["start"], evidence["end"]
    if (type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(doc.text)
            or doc.text[start:end] != evidence["quote"]):
        raise ValueError("Audit evidence differs from the exact source")


def annotation_key(annotation):
    return tuple(annotation[k] for k in ("symptom", "start", "end", "text"))


def build_overlay(docs, refs, sources):
    """Translate already source-inspected decisions, never model agreement, into edits.

    Ambiguous/unresolved decisions remain an unapplied inventory. Every applied
    removal identifies an existing original annotation; every addition is an exact
    quoted source mention with a previously recorded concept and review reason.
    """
    by_id = {d.document_id: d for d in docs}
    overlay, inventory = [], []
    for path in sources:
        for line, decision in enumerate(load_jsonl(path), 1):
            doc_id = decision["document_id"]
            if doc_id not in by_id:
                continue
            doc = by_id[doc_id]
            if decision["note_sha256"] != doc.note_sha256:
                raise ValueError("Audit source identity differs")
            check_evidence(doc, decision["source_evidence"])
            provenance = {"origin_path": str(path), "origin_sha256": sha(path.read_bytes()),
                          "origin_line": line, "original_decision": decision}
            if decision["status"] not in {"REFERENCE_INCORRECT", "REFERENCE_INCOMPLETE"}:
                inventory.append({**provenance, "applied": False})
                continue
            if not decision.get("proposed_correction"):
                raise ValueError("Confirmed decision has no recorded proposal")
            if decision["status"] == "REFERENCE_INCORRECT":
                annotations = ([decision["original_annotation"]] if "original_annotation" in decision
                               else decision["original_annotations"])
                if not annotations:
                    raise ValueError("Removal has no original annotation")
                edits = [("remove", annotation) for annotation in annotations]
            else:
                proposal = decision["proposed_correction"]
                if "symptom" in proposal:
                    annotation = {k: proposal[k] for k in ("symptom", "start", "end", "text")}
                else:
                    evidence = proposal["evidence"]
                    annotation = {"symptom": proposal["add_source_supported_mention"],
                                  "text": evidence["quote"], "start": evidence["start"], "end": evidence["end"]}
                edits = [("add", annotation)]
            for action, annotation in edits:
                check_evidence(doc, {"quote": annotation["text"], "start": annotation["start"], "end": annotation["end"]})
                if annotation["symptom"] not in DEFINITIONS:
                    raise ValueError("Audit concept outside frozen symptom contract")
                if action == "remove" and annotation not in refs[doc_id]:
                    raise ValueError("Removal does not identify an exact original annotation")
                if action == "add" and any(annotation_key(annotation) == annotation_key(a) for a in refs[doc_id]):
                    raise ValueError("Added annotation already exists")
                edit = {"document_id": doc_id, "note_sha256": doc.note_sha256,
                        "action": action, "annotation": annotation,
                        "status": decision["status"], "source_evidence": decision["source_evidence"],
                        "reason": decision["reason"], "verification_method": decision["verification_method"],
                        "review_status": "previously_source_inspected_nonexpert",
                        "clinical_expert_verified": False, **provenance}
                edit["correction_id"] = stable_hash({k: edit[k] for k in
                    ("document_id", "note_sha256", "action", "annotation")})
                overlay.append(edit)
    return overlay, inventory


def apply_overlay(docs, original, overlay):
    corrected = deepcopy(original)
    by_id = {d.document_id: d for d in docs}
    applied, seen = [], set()
    for edit in overlay:
        if edit["correction_id"] in seen:
            raise ValueError("Duplicate correction ID; reference inflation prevented")
        seen.add(edit["correction_id"])
        doc = by_id[edit["document_id"]]
        if edit["note_sha256"] != doc.note_sha256:
            raise ValueError("Overlay source identity differs")
        if edit["status"] not in {"REFERENCE_INCORRECT", "REFERENCE_INCOMPLETE"}:
            raise ValueError("Unresolved audit cannot modify references")
        annotation = edit["annotation"]
        check_evidence(doc, {"quote": annotation["text"], "start": annotation["start"], "end": annotation["end"]})
        values = corrected[doc.document_id]
        if edit["action"] == "remove" and edit["status"] == "REFERENCE_INCORRECT":
            if annotation not in values:
                raise ValueError("Removal reference not found")
            values.remove(annotation)
        elif edit["action"] == "add" and edit["status"] == "REFERENCE_INCOMPLETE":
            if any(annotation_key(annotation) == annotation_key(a) for a in values):
                raise ValueError("Duplicate added reference")
            values.append({**annotation, "audit_correction_id": edit["correction_id"]})
        else:
            raise ValueError("Invalid overlay action/status")
        applied.append(edit["correction_id"])
    return corrected, applied


def verify_index(root):
    index = json.loads((root / "artifact-index.json").read_text(encoding="utf-8"))
    for name, expected in index["files"].items():
        if sha((root / name).read_bytes()) != expected:
            raise ValueError("Frozen artifact changed: " + name)
    return {"sealed_files": len(index["files"]), "index_sha256": sha((root / "artifact-index.json").read_bytes())}


def ledger_count(path):
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
        return db.execute("SELECT count(*) FROM requests").fetchone()[0]


def rescore(repo, root):
    old = repo / "artifacts/luna-grounding-v3"
    manifest = integrity(repo, old)
    seal_before = verify_index(old)
    ledgers = [old / "comparison/requests.sqlite3",
               repo / "artifacts/luna-round2-v1/comparison/requests.sqlite3",
               repo / "artifacts/luna-round2-v1/final/requests.sqlite3",
               repo / "artifacts/clinical-notes-v2/requests.sqlite3"]
    before = {str(p.relative_to(repo)): ledger_count(p) for p in ledgers}
    docs = [d for d in documents(repo) if d.document_id in manifest["comparison_ids"]]
    if len(docs) != 100 or len({d.row_id for d in docs}) != 100 or sum(d.variant == "text" for d in docs) != 50:
        raise ValueError("Frozen balanced cohort changed")
    refs, invalid = references(repo, docs)
    reviews = {r["document_id"]: r for r in load_jsonl(repo / "artifacts/luna-round2-v1/source-review-final.jsonl")}
    for doc in docs:
        if doc.document_id in reviews and reviews[doc.document_id]["note_sha256"] != doc.note_sha256:
            raise ValueError("Fixed source review identity changed")
    cache = load_jsonl(old / "comparison/predictions.jsonl")
    if len(cache) != 100 or {r["document_id"] for r in cache} != {d.document_id for d in docs}:
        raise ValueError("Frozen cache identity mismatch")
    new = {}
    for doc in docs:
        row = next(r for r in cache if r["document_id"] == doc.document_id)
        if row["note_sha256"] != doc.note_sha256:
            raise ValueError("Prediction source identity mismatch")
        if row["status"] == "valid":
            new[doc.document_id] = validate_extraction(json.dumps(row["result"]), doc).model_dump()
    outputs = {"grounded": new, "historical_single_pass_effective": baseline(repo, docs),
               "historical_single_pass_first": baseline(repo, docs, first=True)}
    hashes = {k: stable_hash(v) for k, v in outputs.items()}
    original_metrics = json.loads((old / "comparison/metrics.json").read_text(encoding="utf-8"))
    # First reproduce every historical score and per-document result before changing anything.
    for name, output in outputs.items():
        metric, detail, audit = summarize(docs, output, refs, reviews)
        previous = original_metrics["systems"][name]
        if metric["silver"] != previous["silver"] or metric["audited"] != previous["audited"]:
            raise ValueError("Original score reproduction failed: " + name)
        for suffix, actual in (("silver", detail), ("audited", audit)):
            # JSON tuples serialize as arrays; normalize only this container representation.
            if json.loads(json.dumps(actual)) != load_jsonl(old / "comparison" / f"{name}-{suffix}-comparisons.jsonl"):
                raise ValueError("Original paired detail reproduction failed: " + name)
    sources = [old / "comparison/historical-reference-overlay.jsonl",
               old / "comparison/reference-review-overlay.jsonl"]
    overlay, inventory = build_overlay(docs, refs, sources)
    corrected, applied = apply_overlay(docs, refs, overlay)
    root.mkdir(parents=True, exist_ok=True)
    provenance_paths = [old / "manifest.json", old / "comparison/metrics.json", old / "artifact-index.json",
                        old / "promotion.json", old / "comparison/predictions.jsonl", *sources,
                        repo / "artifacts/luna-round2-v1/source-review-final.jsonl"]
    for package in ("clinical_notes", "luna_round2", "luna_grounding", "luna_rescore"):
        provenance_paths += sorted((repo / "src/clinical_intelligence" / package).glob("*.py"))
    protocol = {"version": VERSION, "normalization_version": NORMALIZATION_VERSION,
        "concept_groups": GROUPS, "added_mapping_only": {"chest pain": "respiratory pain"},
        "conditions": {k: {"new_normalization": n, "confirmed_reference_overlay": a} for k, (n, a) in CONDITIONS.items()},
        "cohort": [{"document_id": d.document_id, "row_id": d.row_id, "variant": d.variant, "note_sha256": d.note_sha256} for d in docs],
        "source_hashes": {str(p.relative_to(repo)): sha(p.read_bytes()) for p in provenance_paths},
        "original_prediction_hashes": hashes, "ledger_counts_before": before,
        "scorer": "unchanged luna_round2.evaluation.summarize; same maximum one-to-one overlap and exact matching",
        "projection": "ephemeral chest-pain alias only; no source fact changes; no change to nasal manifestation/assertion separation",
        "denominator": "all 100 selected documents, including unavailable outputs",
        "reference_scope": "Original silver and partial source-audit correction overlay separately; neither full clinical gold",
        "fixed_assertion_audit": "unchanged source-only 10-document/44-mention subset; nonexpert; status/subject scored, temporality unlabelled",
        "no_inference": True, "new_dispatch_cap": 0,
        "posthoc": True, "promotion_unchanged": True,
        "clinical_semantics": "No keyword reasoning or diagnoses; only already confirmed source-review reference corrections"}
    write_json(root / "experiment_manifest.json", protocol, immutable=True)
    jsonl(root / "reference_adjudication_overlay.jsonl", overlay)
    jsonl(root / "unresolved_reference_inventory.jsonl", inventory)
    jsonl(root / "references_with_overlay.jsonl", [{"document_id": d.document_id,
        "note_sha256": d.note_sha256, "original_annotations": refs[d.document_id],
        "overlay_annotations": corrected[d.document_id]} for d in docs])
    projected, projections = {}, []
    for name, output in outputs.items():
        projected[name], change = project(output)
        projections += [{"system": name, **c} for c in change]
    jsonl(root / "normalization_projection.jsonl", projections)
    scores, details = {}, {}
    for condition, (normalize, audit_refs) in CONDITIONS.items():
        scores[condition], details[condition] = {}, {}
        for name in outputs:
            metric, detail, audit = summarize(docs, projected[name] if normalize else outputs[name],
                                             corrected if audit_refs else refs, reviews)
            scores[condition][name], details[condition][name] = metric, detail
            jsonl(root / condition / f"{name}-mention-comparisons.jsonl", detail)
            jsonl(root / condition / f"{name}-fixed-assertion-audit.jsonl", audit)
    paired = []
    for doc in docs:
        item = {"document_id": doc.document_id, "variant": doc.variant, "note_sha256": doc.note_sha256,
                "conditions": {}}
        for condition in CONDITIONS:
            systems = {}
            for name in outputs:
                detail = next(d for d in details[condition][name] if d["document_id"] == doc.document_id)
                systems[name] = {"true_positive": len(detail["overlap_pairs"]), "predicted": len(detail["predictions"]),
                    "reference": len(detail["references"]), "false_positive": len(detail["unmatched_indices"]),
                    "false_negative": len(detail["missing_indices"]),
                    "complete": doc.document_id in outputs[name] and not detail["missing_indices"] and not detail["unmatched_indices"]}
            delta = (systems["grounded"]["false_positive"] + systems["grounded"]["false_negative"]
                     - systems["historical_single_pass_effective"]["false_positive"] - systems["historical_single_pass_effective"]["false_negative"])
            item["conditions"][condition] = {"systems": systems,
                "new_minus_baseline_unmatched": delta, "relationship": "new_better" if delta < 0 else "baseline_better" if delta > 0 else "tie"}
        paired.append(item)
    jsonl(root / "paired_document_changes.jsonl", paired)
    known_errors = load_jsonl(old / "confirmed-semantic-fact-errors.jsonl")
    omissions = load_jsonl(old / "comparison/confirmed-error-attribution.jsonl")
    jsonl(root / "preserved_source_confirmed_semantic_errors.jsonl", known_errors)
    jsonl(root / "preserved_source_error_attribution.jsonl", omissions)
    after = {str(p.relative_to(repo)): ledger_count(p) for p in ledgers}
    integrity(repo, old)
    seal_after = verify_index(old)
    if after != before or seal_after != seal_before or hashes != {k: stable_hash(v) for k, v in outputs.items()}:
        raise ValueError("Frozen results or request ledger changed during offline evaluation")
    result = {"version": VERSION, "new_model_calls": 0, "original_scores_reproduced_exactly": True,
        "systems": scores, "normalization_projection_counts": dict(Counter(x["system"] for x in projections)),
        "reference_overlay": {"applied_corrections": len(applied), "action_counts": dict(Counter(x["action"] for x in overlay)),
            "corrected_documents": len({x["document_id"] for x in overlay}),
            "unresolved_decisions_retained": len(inventory), "unresolved_documents": len({x["original_decision"]["document_id"] for x in inventory}),
            "original_reference_mentions": sum(map(len, refs.values())), "overlay_reference_mentions": sum(map(len, corrected.values())),
            "invalid_reference_offsets": invalid},
        "paired_document_relationships": {condition: dict(Counter(x["conditions"][condition]["relationship"] for x in paired)) for condition in CONDITIONS},
        "source_confirmed_semantic_errors": {"facts": len(known_errors), "documents": len({x["document_id"] for x in known_errors}),
            "root_cause": 3, "unchanged_by_rescoring": True},
        "preservation": {"seal_before": seal_before, "seal_after": seal_after, "ledger_counts_before": before, "ledger_counts_after": after},
        "scope": "posthoc five-symptom scoring diagnosis on reused development benchmark; not proof of clinical superiority; no promotion or new 300-note run"}
    write_json(root / "metrics.json", result, immutable=True)
    return result
