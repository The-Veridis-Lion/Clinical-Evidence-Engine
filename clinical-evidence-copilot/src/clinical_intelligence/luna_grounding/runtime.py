"""Frozen, resumable single-dispatch phases using the established provider and ledger."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

from . import VERSION
from .contract import CONFIG, INSTRUCTION, PROMOTION_RULE, prompt, schema, resolve
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.runner import SingleDispatchProvider
from ..provider import ProviderConfig
from ..simsum_comparison.ledger import Ledger, now
from ..simsum_comparison.__main__ import documents
from ..luna_round2.runtime import integrity as previous_integrity
from ..luna_round2.contract import stable_hash
from ..luna_round2.evaluation import ledger_rows


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path, rows):
    content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"Immutable artifact changed: {path}")
        return
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(content)


def code_hashes():
    return {str(p): sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}


def provider():
    return SingleDispatchProvider(ProviderConfig(model=CONFIG["model"],
        reasoning_effort=CONFIG["reasoning_effort"], timeout_seconds=CONFIG["timeout_seconds"]))


def initialize(repo, root):
    old = repo / "artifacts/luna-round2-v1"
    parent = previous_integrity(repo, old)
    docs = documents(repo)
    selected = parent["comparison_ids"]
    assert len(selected) == len(set(selected)) == 100
    chosen = [d for d in docs if d.document_id in selected]
    assert len({d.row_id for d in chosen}) == 100
    assert sum(d.variant == "text" for d in chosen) == 50
    index = read(old / "artifact-index.json")
    protected = {str((old / n).relative_to(repo)): h for n, h in index["files"].items()}
    for p in (old / "manifest.json", old / "artifact-index.json",
              repo / "artifacts/luna-round2-structural-audit-v1/summary.json",
              repo / "artifacts/luna-round2-structural-audit-v1/paired-audit.jsonl"):
        protected[str(p.relative_to(repo))] = sha(p.read_bytes())
    p = provider()
    p.preflight()
    manifest = {"version": VERSION, "config": CONFIG, "promotion_rule": PROMOTION_RULE,
        "comparison_ids": selected, "cohort": parent["cohort"],
        "cohort_sha256": parent["cohort_sha256"], "partition_sha256": parent["partition_sha256"],
        "code_hashes": code_hashes(), "protected_files": protected,
        "prompt_sha256": sha(INSTRUCTION), "schema_template": schema(docs[0]),
        "per_document_contracts": {d.document_id: {"prompt_sha256": sha(prompt(d)),
                                    "schema_sha256": stable_hash(schema(d))} for d in docs},
        "provider": {"cli_version": p.cli_version, "argv": p.command(Path("FROZEN_REQUEST"))},
        "scorer": "unchanged clinical_intelligence.luna_round2.evaluation.summarize",
        "data_role": "reused development benchmark, not unseen holdout",
        "research": ["https://github.com/google/langextract",
                     "https://developers.openai.com/api/docs/guides/structured-outputs"],
        "design": "v2 clinical instruction unchanged; model selects source_id; exact full passage copied deterministically"}
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "manifest.json", manifest, immutable=True)
    write_json(root / "inputs-freeze.json", [{"document_id": d.document_id, **d.__dict__} for d in docs], immutable=True)
    integrity(repo, root)
    return manifest


def integrity(repo, root):
    m = read(root / "manifest.json")
    if code_hashes() != m["code_hashes"]:
        raise ValueError("Frozen grounding implementation changed")
    for n, h in m["protected_files"].items():
        if sha((repo / n).read_bytes()) != h:
            raise ValueError("Historical artifact changed: " + n)
    previous_integrity(repo, repo / "artifacts/luna-round2-v1")
    return m


def folder(root, phase, doc_id):
    return root / phase / "requests" / doc_id.replace(":", "_")


def execute(repo, root, phase, *, limit=None, supplied_provider=None):
    m = integrity(repo, root)
    if phase not in ("comparison", "final"):
        raise ValueError("Unknown phase")
    docs = documents(repo)
    if phase == "comparison":
        docs = [d for d in docs if d.document_id in m["comparison_ids"]]
    else:
        gate = read(root / "promotion.json")
        if not gate["promote"] or gate["manifest_sha256"] != sha((root / "manifest.json").read_bytes()):
            raise ValueError("Final run requires a qualifying frozen candidate")
    cap = CONFIG[phase + "_cap"]
    ledger = Ledger(root / phase / "requests.sqlite3", {"manifest_sha256": sha((root / "manifest.json").read_bytes()),
                    "phase": phase}, total_cap=cap, batch_cap=cap)
    p = supplied_provider or provider()
    p.preflight()
    if p.cli_version != m["provider"]["cli_version"]:
        raise ValueError("Provider CLI version changed")
    lock = root / "runner.lock"
    with lock.open("x", encoding="utf-8") as f:
        f.write(json.dumps({"pid": os.getpid(), "phase": phase, "started_at": now()}))
    began = perf_counter()
    before = len(ledger.rows())

    def work(doc):
        text, shape = prompt(doc), schema(doc)
        contract = m["per_document_contracts"][doc.document_id]
        assert sha(text) == contract["prompt_sha256"] and stable_hash(shape) == contract["schema_sha256"]
        input_hash = stable_hash({"prompt": text, "schema": shape, "provider": m["provider"], "config": CONFIG})
        if not ledger.reserve("grounded.extract", doc.document_id, 1, phase, input_hash):
            return "previously_reserved_no_replay"
        directory = folder(root, phase, doc.document_id).resolve()
        started = perf_counter()
        status, error, usage, raw_hash = "failed", None, None, None
        try:
            directory.mkdir(parents=True, exist_ok=False)
            write_json(directory / "schema.json", shape, immutable=True)
            write_json(directory / "input-identity.json", {"document_id": doc.document_id,
                "note_sha256": doc.note_sha256, "input_hash": input_hash, "phase": phase}, immutable=True)
            with (directory / "prompt.txt").open("x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            raw, usage = p.dispatch(doc, directory)
            if not (directory / "raw-response.json").exists():
                raise RuntimeError("Raw response must precede postprocessing")
            try:
                value, provenance = resolve(raw, doc)
            except ValueError as exc:
                status, error = "invalid", str(exc)
            else:
                write_json(directory / "result.json", value, immutable=True)
                write_json(directory / "offset-provenance.json", provenance, immutable=True)
                status = "valid"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if (directory / "raw-response.json").exists():
                raw_hash = sha((directory / "raw-response.json").read_bytes())
            if (directory / "usage.json").exists():
                usage = read(directory / "usage.json")
            ledger.finish("grounded.extract", doc.document_id, 1, status, perf_counter() - started, usage, error, raw_hash)
        print(json.dumps({"phase": phase, "document_id": doc.document_id, "status": status, "error": error}), flush=True)
        return status

    try:
        with ThreadPoolExecutor(max_workers=CONFIG["max_concurrency"]) as pool:
            statuses = list(pool.map(work, docs[:limit] if limit else docs))
    finally:
        lock.unlink()
    write_json(root / phase / "runs" / (now().replace(":", "-") + ".json"), {
        "wall_seconds": perf_counter() - began, "new_dispatches": len(ledger.rows()) - before,
        "processed": len(statuses), "statuses": statuses}, immutable=True)
    assert sum(len(ledger_rows(root, x)) for x in ("comparison", "final")) <= CONFIG["new_round_cap"]
    integrity(repo, root)
    return statuses
