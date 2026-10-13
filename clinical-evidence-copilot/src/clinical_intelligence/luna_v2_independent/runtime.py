"""One shared 200-dispatch ceiling, isolated source-only B payloads, no retries."""
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata as metadata
import json
import os
from pathlib import Path
from time import perf_counter

from . import VERSION
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.schema import validate_extraction
from ..clinical_notes.runner import SingleDispatchProvider
from ..provider import ProviderConfig
from ..simsum_comparison.ledger import Ledger, now
from ..simsum_comparison.evaluation import load_jsonl
from ..simsum_comparison.__main__ import documents

CONFIG = {"model": "gpt-6-luna", "reasoning_effort": "high", "timeout_seconds": 300,
          "concurrency": 10, "total_dispatch_cap": 200, "per_approach_cap": 100,
          "transport_retries": 0, "structural_retries": 0, "full_300_allowed": False}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in values)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError("Immutable artifact differs: " + str(path))
    else:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


def selected(repo):
    records = read(repo / "artifacts/luna-offline-rescore-v1/experiment_manifest.json")["cohort"]
    all_docs = {d.document_id: d for d in documents(repo)}
    docs = [all_docs[r["document_id"]] for r in records]
    if len(docs) != 100 or len({d.row_id for d in docs}) != 100 or sum(d.variant == "text" for d in docs) != 50:
        raise ValueError("Exact frozen balanced 100-patient cohort required")
    if any(d.note_sha256 != r["note_sha256"] for d, r in zip(docs, records)):
        raise ValueError("Cohort source changed")
    return docs


def hashes(repo):
    packages = ["luna_v2_independent", "clinical_notes", "simsum_comparison", "luna_round2", "luna_rescore", "rule_first"]
    paths = [p for name in packages for p in (repo / "src/clinical_intelligence" / name).rglob("*")
             if p.is_file() and p.suffix in {".py", ".json", ".html"}]
    paths += [repo / "src/clinical_intelligence/provider.py"]
    return {str(p.relative_to(repo)): sha(p.read_bytes()) for p in paths}


def provider():
    return SingleDispatchProvider(ProviderConfig(model=CONFIG["model"], reasoning_effort="high", timeout_seconds=300))


def initialize(repo, root):
    # B is frozen now, before any new A scanner execution or outcome.
    from . import approach_b
    docs = selected(repo)
    p = provider()
    p.preflight()
    command = p.command(Path("FROZEN_REQUEST"))
    providers = {"cli_version": p.cli_version, "argv": command}
    protections = read(repo / "artifacts/rule-first-v3/manifest.json")["protected"].copy()
    for path in [repo / "docs/luna-v2-reaudit-v1.md", repo / "tools/luna_v2_reaudit.py",
                 repo / "THIRD_PARTY_NOTICES.md", repo / "pyproject.toml"]:
        protections[str(path.relative_to(repo))] = sha(path.read_bytes())
    for old in ["rule-first-v1", "rule-first-v2", "rule-first-v3", "luna-v2-reaudit-v1"]:
        for path in (repo / "artifacts" / old).glob("*"):
            if path.is_file() and path.suffix in {".json", ".jsonl"}:
                protections[str(path.relative_to(repo))] = sha(path.read_bytes())
    ledger_counts = {}
    import sqlite3
    for relative in ["artifacts/clinical-notes-v2/requests.sqlite3", "artifacts/gliner-luna-v1/luna-requests.sqlite3",
                     "artifacts/luna-source-constrained-v1/requests.sqlite3", "artifacts/luna-prepared-high-v1/requests.sqlite3",
                     "artifacts/sol-controlled-comparison-v1/requests.sqlite3"]:
        path = repo / relative
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
            ledger_counts[relative] = db.execute("SELECT count(*) FROM requests").fetchone()[0]
    manifest = {"version": VERSION, "config": CONFIG, "implementation": hashes(repo), "protected": protections,
                "provider": providers, "packages": {n: metadata.version(n) for n in ["medspacy", "spacy", "pydantic", "langextract"]},
                "cohort": [{"document_id": d.document_id, "note_sha256": d.note_sha256, "variant": d.variant} for d in docs],
                "historical_ledger_counts": ledger_counts,
                "budget_basis": "New user-authorized round <=200; all historical ledgers and caps unchanged; also <= remaining 2000-1435 allowance of the original comparison ledger; no stricter active project-wide limit found",
                "B": {"source_only": True, "refinement": "one atomic source-assertion guideline block",
                      "prompt_sha256": sha(approach_b.INSTRUCTION_V2 + approach_b.REFINEMENT),
                      "schema_sha256": sha(json.dumps(approach_b.schema(), sort_keys=True)),
                      "per_note_prompt_sha256": {d.document_id: sha(approach_b.prompt(d)) for d in docs}},
                "A_offline_gate": {"minimum_source_confirmed_new_mentions": 3, "minimum_distinct_documents": 2,
                                  "maximum_source_grounding_failures": 0,
                                  "selection": "All runtime flagged documents; no source-audit or gold-based case filtering"},
                "source_audit": {"seed": "luna-v2-independent-v1-success-20261011", "per_variant": 5,
                                 "discrepancy_review_cap": 20,
                                 "prior_source_controls": ["simsum:4613:text", "simsum:2278:text", "simsum:7407:text", "simsum:2899:text",
                                    "simsum:192:advanced_text", "simsum:8698:text", "simsum:1522:advanced_text"]},
                "evaluation": "same corrected one-to-one scorer, 26 frozen overlay edits, all100; no new gold corrections"}
    write_json(root / "manifest.json", manifest, immutable=True)
    lines(root / "source-inputs.jsonl", [{"document_id": d.document_id, "note_sha256": d.note_sha256,
                                        "variant": d.variant, "text": d.text} for d in docs])
    return manifest


def integrity(repo, root):
    m = read(root / "manifest.json")
    expected = m["implementation"].copy()
    repair = root / "pre-scoring-evaluator-repair.json"
    if repair.exists():
        record = read(repair)
        for path, change in record["files"].items():
            if path not in {"src\\clinical_intelligence\\luna_v2_independent\\runtime.py",
                            "src\\clinical_intelligence\\luna_v2_independent\\evaluation.py"} or expected[path] != change["before"]:
                raise ValueError("Invalid evaluator-repair provenance")
            expected[path] = change["after"]
    if hashes(repo) != expected:
        raise ValueError("Frozen implementation changed")
    if any(sha((repo / path).read_bytes()) != expected for path, expected in m["protected"].items()):
        raise ValueError("Historical or unrelated artifact changed")
    if m["packages"] != {n: metadata.version(n) for n in m["packages"]}:
        raise ValueError("Frozen dependencies changed")
    return m


def offline_a(repo, root):
    integrity(repo, root)
    from .approach_a import CoverageScanner, prompt, schema
    from ..luna_round2.evaluation import baseline
    from loguru import logger
    logger.disable("PyRuSH")
    docs, scanner = selected(repo), CoverageScanner()
    originals = baseline(repo, docs)
    if len(originals) != 100:
        raise ValueError("Complete frozen V2 baseline required")
    scans = [scanner.scan(d, originals[d.document_id]) for d in docs]
    lines(root / "A/scanner.jsonl", scans)
    lines(root / "historical-v2-predictions.jsonl", [{"document_id": d.document_id, "result": originals[d.document_id]} for d in docs])
    contracts = {}
    for doc, scan in zip(docs, scans):
        if scan["requires_adjudication"]:
            contracts[doc.document_id] = {"prompt_sha256": sha(prompt(doc, scan, originals[doc.document_id])),
                                        "schema_sha256": sha(json.dumps(schema(scan), sort_keys=True))}
    write_json(root / "A/targeted-contracts.json", contracts, immutable=True)
    summary = {"documents": 100, "detected_mentions": sum(len(s["candidates"]) for s in scans),
               "covered_mentions": sum(s["covered_mentions"] for s in scans),
               "uncovered_mentions": sum(s["uncovered_mentions"] for s in scans),
               "flagged_documents": sum(s["requires_adjudication"] for s in scans),
               "gold_used_for_detection_or_selection": False, "confirmed_new_facts": None}
    write_json(root / "A/offline-summary.json", summary, immutable=True)
    return summary


def requests(root):
    path = root / "requests.sqlite3"
    if not path.exists():
        return []
    import sqlite3
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY reserved_at")]


def execute(repo, root, approach, limit=None, supplied_provider=None):
    m = integrity(repo, root)
    if approach not in {"A", "B"}:
        raise ValueError("Independent approaches A and B only")
    docs = selected(repo)
    if approach == "A":
        gate = read(root / "A/offline-decision.json")
        if not gate["proceed"]:
            return {"status": "offline_rejected", "calls": 0}
        scans = {s["document_id"]: s for s in load_jsonl(root / "A/scanner.jsonl")}
        originals = {s["document_id"]: s["result"] for s in load_jsonl(root / "historical-v2-predictions.jsonl")}
        contracts = read(root / "A/targeted-contracts.json")
        docs = [d for d in docs if d.document_id in contracts]
    p = supplied_provider or provider()
    p.preflight()
    if p.cli_version != m["provider"]["cli_version"]:
        raise ValueError("Provider version changed")
    ledger = Ledger(root / "requests.sqlite3", {"manifest_sha256": sha((root / "manifest.json").read_bytes())}, total_cap=200, batch_cap=100)
    lock = root / "runner.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "approach": approach, "started": now()}))
    before, began = len(ledger.rows()), perf_counter()

    def work(doc):
        if approach == "B":
            from . import approach_b
            text, shape = approach_b.prompt(doc), approach_b.schema()
            if sha(text) != m["B"]["per_note_prompt_sha256"][doc.document_id]:
                raise ValueError("Frozen B source-only input changed")
        else:
            from . import approach_a
            scan, original = scans[doc.document_id], originals[doc.document_id]
            text, shape = approach_a.prompt(doc, scan, original), approach_a.schema(scan)
            contract = contracts[doc.document_id]
            if sha(text) != contract["prompt_sha256"] or sha(json.dumps(shape, sort_keys=True)) != contract["schema_sha256"]:
                raise ValueError("Frozen targeted A input changed")
        input_hash = sha(text + json.dumps(shape, sort_keys=True))
        if not ledger.reserve(approach, doc.document_id, 1, approach, input_hash):
            return "previously_reserved_no_replay"
        folder = root / approach / "requests" / doc.document_id.replace(":", "_")
        folder.mkdir(parents=True, exist_ok=False)
        start, status, error, usage = perf_counter(), "failed", None, None
        try:
            write_json(folder / "schema.json", shape, immutable=True)
            with (folder / "prompt.txt").open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            raw, usage = p.dispatch(doc, folder.resolve())
            if not (folder / "raw-response.json").exists():
                raise RuntimeError("Raw response must be durable before validation")
            try:
                if approach == "B":
                    value = approach_b.resolve(raw, doc)
                    write_json(folder / "result.json", value, immutable=True)
                else:
                    value = approach_a.validate_proposals(raw, doc, scan, original)
                    write_json(folder / "proposal-validation.json", value, immutable=True)
                status = "valid"
            except ValueError as exc:
                status, error = "invalid", str(exc)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if (folder / "usage.json").exists():
                usage = read(folder / "usage.json")
            raw_hash = sha((folder / "raw-response.json").read_bytes()) if (folder / "raw-response.json").exists() else None
            ledger.finish(approach, doc.document_id, 1, status, perf_counter() - start, usage, error, raw_hash)
        print(json.dumps({"approach": approach, "document_id": doc.document_id, "status": status, "error": error}), flush=True)
        return status
    try:
        with ThreadPoolExecutor(max_workers=CONFIG["concurrency"]) as pool:
            outcomes = list(pool.map(work, docs[:limit] if limit else docs))
    finally:
        lock.unlink()
    result = {"approach": approach, "new_calls": len(ledger.rows()) - before,
              "wall_seconds": perf_counter() - began, "statuses": outcomes}
    write_json(root / approach / "runs" / (now().replace(":", "-") + ".json"), result, immutable=True)
    integrity(repo, root)
    return result
