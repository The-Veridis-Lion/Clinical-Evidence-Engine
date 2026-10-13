"""Shared atomic 500-call ledger and immutable inputs; no historical budget reset."""
import json
import os
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from . import VERSION
from .contract import CONFIG, EFFORTS, INSTRUCTION, PROMOTION_RULE, prompt, schema, resolve
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.runner import SingleDispatchProvider
from ..provider import ProviderConfig
from ..simsum_comparison.ledger import Ledger, now
from ..simsum_comparison.__main__ import documents
from ..luna_grounding.runtime import read, jsonl, integrity as old_integrity
from ..luna_round2.contract import stable_hash
from ..luna_rescore.evaluation import verify_index, ledger_count


class SourceProvider(SingleDispatchProvider):
    def preflight(self):
        command = self.command(Path("FROZEN_REQUEST"))
        configs = [part for i, v in enumerate(command) if v == "-c" for part in (v, command[i+1])]
        result = subprocess.run([self.executable, "debug", "models", "--bundled", *configs],
            capture_output=True, text=True, encoding="utf-8", timeout=20, check=True)
        model = next((m for m in json.loads(result.stdout)["models"] if m["slug"] == self.config.model), None)
        if model is None or self.config.reasoning_effort not in {x["effort"] for x in model["supported_reasoning_levels"]}:
            raise RuntimeError(f"Installed CLI/provider does not support {self.config.model}/{self.config.reasoning_effort}")
        self.capabilities = {k: model[k] for k in ("slug", "supported_reasoning_levels", "supported_in_api")}


def provider(name):
    return SourceProvider(ProviderConfig(model=CONFIG["model"], reasoning_effort=EFFORTS[name],
                                        timeout_seconds=CONFIG["timeout_seconds"]))


def code_hashes(repo):
    return {str(p.relative_to(repo)): sha(p.read_bytes())
            for p in sorted((repo / "src/clinical_intelligence").rglob("*.py"))
            if "sol_comparison" not in p.relative_to(repo).parts}


def rows(root):
    path = root / "requests.sqlite3"
    if not path.exists():
        return []
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY reserved_at")]


def initialize(repo, root):
    previous = repo / "artifacts/luna-grounding-v3"
    parent = old_integrity(repo, previous)
    verify_index(previous)
    rescore = repo / "artifacts/luna-offline-rescore-v1"
    verify_index(rescore)
    docs = documents(repo)
    selected = parent["comparison_ids"]
    assert len(selected) == len(set(selected)) == 100
    assert len(docs) == len({d.row_id for d in docs}) == 300
    chosen = [d for d in docs if d.document_id in selected]
    assert len(chosen) == len({d.row_id for d in chosen}) == 100
    assert sum(d.variant == "text" for d in chosen) == 50
    providers = {}
    for name in EFFORTS:
        p = provider(name)
        p.preflight()
        providers[name] = {"cli_version": p.cli_version, "capabilities": p.capabilities,
                           "argv": p.command(Path("FROZEN_REQUEST"))}
    # Verify that the provider requests differ only in the explicitly requested effort.
    a, b = providers["A"]["argv"], providers["B"]["argv"]
    assert len(a) == len(b)
    assert [(x, y) for x, y in zip(a, b) if x != y] == [
        ('model_reasoning_effort="high"', 'model_reasoning_effort="xhigh"')]
    protected = dict(parent["protected_files"])
    for directory in (previous, rescore):
        for n, h in read(directory / "artifact-index.json")["files"].items():
            protected[str((directory / n).relative_to(repo))] = h
        protected[str((directory / "artifact-index.json").relative_to(repo))] = sha((directory / "artifact-index.json").read_bytes())
    for f in (repo / "examples/clinical_notes/v2/batch2.json", repo / "examples/clinical_notes/v1/partition.json"):
        protected[str(f.relative_to(repo))] = sha(f.read_bytes())
    historical_ledgers = [repo / "artifacts/clinical-notes-v2/requests.sqlite3",
        repo / "artifacts/gliner-luna-v1/luna-requests.sqlite3",
        repo / "artifacts/luna-round2-v1/comparison/requests.sqlite3",
        repo / "artifacts/luna-round2-v1/final/requests.sqlite3", previous / "comparison/requests.sqlite3"]
    m = {"version": VERSION, "config": CONFIG, "efforts": EFFORTS, "providers": providers,
         "comparison_ids": selected, "cohort": parent["cohort"], "promotion_rule": PROMOTION_RULE,
         "code_hashes": code_hashes(repo), "protected_files": protected,
         "historical_ledger_counts": {str(p.relative_to(repo)): ledger_count(p) for p in historical_ledgers},
         "prompt_sha256": sha(INSTRUCTION), "per_document_contracts": {
             d.document_id: {"prompt_sha256": sha(prompt(d)), "schema_sha256": stable_hash(schema(d)),
                             "note_sha256": d.note_sha256} for d in docs},
         "reference_overlay_sha256": sha((rescore / "reference_adjudication_overlay.jsonl").read_bytes()),
         "evaluation": "luna-offline-rescore-v1 chest-pain projection and frozen confirmed overlay; primary span matching unchanged",
         "budget_basis": "new user-authorized round: 100 high + 100 xhigh + conditional fresh 300; earlier closed limits/ledgers preserved",
         "branch": subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip(),
         "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()}
    write_json(root / "manifest.json", m, immutable=True)
    write_json(root / "implementation-freeze.json", {
        "manifest_sha256": sha((root / "manifest.json").read_bytes()),
        "code_hashes": code_hashes(repo), "reason": "isolated experiment dependencies; unrelated Sol comparison excluded"}, immutable=True)
    write_json(root / "inputs-freeze.json", [d.__dict__ for d in docs], immutable=True)
    integrity(repo, root)
    return m


def integrity(repo, root):
    m = read(root / "manifest.json")
    frozen = read(root / "implementation-freeze.json")
    if frozen["manifest_sha256"] != sha((root / "manifest.json").read_bytes()) or code_hashes(repo) != frozen["code_hashes"]:
        raise ValueError("Frozen implementation changed")
    for name, h in m["protected_files"].items():
        if sha((repo / name).read_bytes()) != h:
            raise ValueError("Historical artifact changed: " + name)
    for name, count in m["historical_ledger_counts"].items():
        if ledger_count(repo / name) != count:
            raise ValueError("Historical request budget changed: " + name)
    for d in documents(repo):
        if d.note_sha256 != m["per_document_contracts"][d.document_id]["note_sha256"]:
            raise ValueError("Source note changed")
    return m


def folder(root, phase, name, doc_id):
    return root / phase / name / "requests" / doc_id.replace(":", "_")


def execute(repo, root, phase, name, *, limit=None, supplied_provider=None):
    m = integrity(repo, root)
    if phase not in {"comparison", "final"} or name not in EFFORTS:
        raise ValueError("Unplanned configuration/phase")
    docs = documents(repo)
    if phase == "comparison":
        docs = [d for d in docs if d.document_id in m["comparison_ids"]]
    else:
        winner = read(root / "winner-freeze.json")
        if not winner["promote"] or winner["winner"] != name or winner["manifest_sha256"] != sha((root / "manifest.json").read_bytes()):
            raise ValueError("Final requires a qualifying frozen winner")
    ledger = Ledger(root / "requests.sqlite3", {"manifest_sha256": sha((root / "manifest.json").read_bytes())},
                    total_cap=CONFIG["total_cap"], batch_cap=CONFIG["final_cap"])
    p = supplied_provider or provider(name)
    p.preflight()
    if p.cli_version != m["providers"][name]["cli_version"]:
        raise ValueError("Provider CLI version changed")
    stage, batch = phase + "." + name, phase + "." + name
    lock = root / "runner.lock"
    with lock.open("x", encoding="utf-8") as f:
        f.write(json.dumps({"pid": os.getpid(), "phase": phase, "configuration": name, "started_at": now()}))
    began, before = perf_counter(), len(ledger.rows())

    def work(doc):
        text, shape = prompt(doc), schema(doc)
        c = m["per_document_contracts"][doc.document_id]
        if sha(text) != c["prompt_sha256"] or stable_hash(shape) != c["schema_sha256"]:
            raise ValueError("Frozen document contract changed")
        request_hash = stable_hash({"contract": c, "provider": m["providers"][name], "config": CONFIG})
        if not ledger.reserve(stage, doc.document_id, 1, batch, request_hash):
            return "previously_reserved_no_replay"
        directory = folder(root, phase, name, doc.document_id).resolve()
        started = perf_counter()
        status, error, usage, raw_hash = "failed", None, None, None
        try:
            directory.mkdir(parents=True, exist_ok=False)
            write_json(directory / "schema.json", shape, immutable=True)
            write_json(directory / "input-identity.json", {"document_id": doc.document_id,
                "note_sha256": doc.note_sha256, "input_hash": request_hash, "phase": phase, "configuration": name}, immutable=True)
            with (directory / "prompt.txt").open("x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            raw, usage = p.dispatch(doc, directory)
            if not (directory / "raw-response.json").exists():
                raise RuntimeError("Provider must persist original response")
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
            if (directory / "raw-response.json").exists(): raw_hash = sha((directory / "raw-response.json").read_bytes())
            if (directory / "usage.json").exists(): usage = read(directory / "usage.json")
            ledger.finish(stage, doc.document_id, 1, status, perf_counter() - started, usage, error, raw_hash)
        print(json.dumps({"phase": phase, "configuration": name, "document_id": doc.document_id,
                          "status": status, "error": error}), flush=True)
        return status

    try:
        with ThreadPoolExecutor(max_workers=CONFIG["max_concurrency"]) as pool:
            statuses = list(pool.map(work, docs[:limit] if limit else docs))
    finally:
        lock.unlink()
    write_json(root / phase / name / "runs" / (now().replace(":", "-") + ".json"),
        {"wall_seconds": perf_counter() - began, "new_dispatches": len(ledger.rows()) - before,
         "processed": len(statuses), "statuses": statuses}, immutable=True)
    assert sum(r["stage"] == stage for r in ledger.rows()) <= len(docs)
    integrity(repo, root)
    return statuses
