"""Bounded append-only pilot; all failed reservations count, no transport replay."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.runner import SingleDispatchProvider
from ..provider import ProviderConfig
from . import VERSION
from .contract import inspect, inspect_repair, schema
from .dataset import load_inputs
from .prompt import prompt, repair_prompt

CONFIG = {"model": "gpt-6-luna", "reasoning_effort": "high", "timeout_seconds": 300,
    "total_request_cap": 20, "initial_requests_per_encounter": 1,
    "structural_repairs_per_encounter": 1, "transport_retries": 0,
    "provider_request_retries": 0, "provider_stream_retries": 0}


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Budget:
    def __init__(self, root, identity, document_ids):
        self.path = root / "requests.sqlite3"
        self.ids = set(document_ids)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS identity(content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(
                    document_id TEXT, attempt INTEGER CHECK(attempt IN (1,2)), status TEXT,
                    reserved_at TEXT, ended_at TEXT, latency_seconds REAL, usage TEXT, error TEXT,
                    PRIMARY KEY(document_id,attempt));
                CREATE TRIGGER IF NOT EXISTS immutable_request BEFORE UPDATE ON requests
                    WHEN OLD.status!='reserved' BEGIN SELECT RAISE(ABORT,'terminal immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON requests
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS fixed_request_identity BEFORE UPDATE ON requests
                    WHEN NEW.document_id!=OLD.document_id OR NEW.attempt!=OLD.attempt OR NEW.reserved_at!=OLD.reserved_at
                    BEGIN SELECT RAISE(ABORT,'identity immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_identity BEFORE UPDATE ON identity
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_identity_delete BEFORE DELETE ON identity
                    BEGIN SELECT RAISE(ABORT,'immutable'); END;
            """)
            content = json.dumps(identity, sort_keys=True)
            old = db.execute("SELECT content FROM identity").fetchall()
            if not old:
                db.execute("INSERT INTO identity VALUES (?)", (content,))
            elif len(old) != 1 or old[0][0] != content:
                raise ValueError("Frozen request identity changed")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def rows(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY reserved_at")]

    def reserve(self, document_id, attempt):
        if document_id not in self.ids or attempt not in (1, 2):
            raise ValueError("Unplanned request")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM requests WHERE document_id=? AND attempt=?", (document_id, attempt)).fetchone():
                return False
            if attempt == 2:
                parent = db.execute("SELECT status FROM requests WHERE document_id=? AND attempt=1", (document_id,)).fetchone()
                if not parent or parent[0] not in {"INVALID", "PARTIAL"}:
                    raise ValueError("Only mechanical validation failure permits repair")
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= CONFIG["total_request_cap"]:
                raise RuntimeError("20-request cap exhausted (including failures)")
            db.execute("INSERT INTO requests(document_id,attempt,status,reserved_at) VALUES (?,?,'reserved',?)",
                       (document_id, attempt, now()))
        return True

    def finish(self, identity, attempt, status, latency, usage, error):
        if status not in {"VALID", "PARTIAL", "INVALID", "FAILED"}:
            raise ValueError("Unknown request status")
        with self.connect() as db:
            count = db.execute("UPDATE requests SET status=?,ended_at=?,latency_seconds=?,usage=?,error=? "
                "WHERE document_id=? AND attempt=? AND status='reserved'",
                (status, now(), latency, json.dumps(usage), error, identity, attempt)).rowcount
            if count != 1:
                raise ValueError("Request is not reserved")


def implementation_hashes():
    package = Path(__file__).parent
    sources = list(package.glob("*.py")) + [package.parent / "clinical_notes" / n for n in ("runner.py", "schema.py", "dataset.py")] + [package.parent / "provider.py"]
    return {str(p.relative_to(package.parent)): sha(p.read_bytes()) for p in sources}


def initialize(root, provider):
    docs = load_inputs(root)
    provider.preflight()  # Local bundled capability parse, no model request.
    identity = {"version": VERSION, "config": CONFIG, "selection_sha256": sha((root / "selection.json").read_bytes()),
        "inputs_sha256": sha((root / "inputs.json").read_bytes()), "implementation": implementation_hashes(),
        "cli_version": provider.cli_version,
        "provider_argv": provider.command(Path("FROZEN_REQUEST")),
        "contracts": {d.document_id: {"prompt_sha256": sha(prompt(d)),
            "schema_sha256": sha(json.dumps(schema(d), sort_keys=True))} for d in docs}}
    write_json(root / "execution-freeze.json", identity, immutable=True)
    return identity, docs


def summarize(doc, outcome, requests):
    lines = [f"# {doc.encounter_id} ({doc.subset})", "",
        f"Mechanical status: {outcome['status']}. This is not a clinical accuracy assessment.", ""]
    for i, f in enumerate((outcome.get("result") or {}).get("facts", [])):
        turns = ", ".join(dict.fromkeys(p["turn_id"] for p in f["provenance"]))
        lines.append(f"- [{i}] {f['concept'] or f['original_term']} | {f['category']} | {f['polarity']} | "
            f"{f['temporality']} | {f['experiencer']} | {f['assertion_basis']} | {f['clinical_status']} | "
            f"attribution={f['attribution_confidence']} | {turns}")
        if f["attributes"]:
            lines.append("  Attributes: " + json.dumps(f["attributes"], ensure_ascii=False))
        for p in f["provenance"]:
            lines.append(f"  > {p['turn_id']} {p['speaker_label'] or '[unlabelled]'} [{p['start']}:{p['end']}]: {p['quote']}")
    for r in (outcome.get("result") or {}).get("relationships", []):
        lines.append(f"- Relationship [{r['from_fact_index']}] → [{r['to_fact_index']}]: {r['relation']}")
    lines.extend(["", "Request records:", "```json", json.dumps(requests, ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines) + "\n"


def attempt(root, doc, number, provider, ledger, *, initial=None, initial_raw=None):
    if not ledger.reserve(doc.document_id, number):
        raise RuntimeError("Reserved requests are never replayed")
    folder = root / "encounters" / doc.encounter_id / f"attempt-{number}"
    started = perf_counter()
    usage, error = None, None
    outcome = {"status": "FAILED", "result": None, "accepted_indices": [], "errors": []}
    try:
        folder.mkdir(parents=True, exist_ok=False)
        write_json(folder / "schema.json", schema(doc), immutable=True)
        text = prompt(doc) if number == 1 else repair_prompt(doc, initial_raw, initial["errors"])
        with (folder / "prompt.txt").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        raw, usage = provider.dispatch(doc, folder)
        if not (folder / "raw-response.json").exists():
            raise ValueError("Provider failed to persist original response")
        outcome = inspect(raw, doc) if number == 1 else inspect_repair(raw, initial_raw, initial, doc)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        outcome["errors"].append(error)
        # Raw output on failed/timeout requests is retained but not silently promoted.
        if (folder / "raw-response.json").exists():
            outcome["unaccepted_raw_available"] = True
    finally:
        if (folder / "usage.json").exists():
            usage = read(folder / "usage.json")
        elif (folder / "events.jsonl").exists():
            for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "turn.completed":
                    usage = event.get("usage")
        write_json(folder / "validation.json", outcome, immutable=True)
        ledger.finish(doc.document_id, number, outcome["status"], perf_counter() - started, usage,
                      error or (json.dumps(outcome["errors"]) if outcome["errors"] else None))
    return outcome


def run(root: Path, *, provider=None, limit=None):
    root = root.resolve()
    provider = provider or SingleDispatchProvider(ProviderConfig(model=CONFIG["model"], reasoning_effort="high", timeout_seconds=300))
    if provider.config.model != CONFIG["model"] or provider.config.reasoning_effort != "high":
        raise ValueError("Pilot requires current Luna/High")
    identity, docs = initialize(root, provider)
    ledger = Budget(root, identity, [d.document_id for d in docs])
    lock = root / "runner.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps({"pid": os.getpid(), "started_at": now()}))
    try:
        for doc in docs[:limit] if limit else docs:
            directory = root / "encounters" / doc.encounter_id
            if (directory / "outcome.json").exists():
                continue
            previous = [r for r in ledger.rows() if r["document_id"] == doc.document_id]
            if any(r["status"] == "reserved" for r in previous):
                raise RuntimeError("Interrupted reservation: inspect saved streams locally; never redispatch")
            initial = read(directory / "attempt-1/validation.json") if previous else attempt(root, doc, 1, provider, ledger)
            outcome = initial
            if initial["status"] in {"INVALID", "PARTIAL"}:
                raw = (directory / "attempt-1/raw-response.json").read_text(encoding="utf-8")
                repaired = read(directory / "attempt-2/validation.json") if len(previous) == 2 else attempt(
                    root, doc, 2, provider, ledger, initial=initial, initial_raw=raw)
                if repaired["status"] == "VALID" or len(repaired.get("accepted_indices", [])) > len(initial["accepted_indices"]):
                    outcome = repaired
                else:
                    outcome = {**initial, "unresolved_repair": repaired}
            write_json(directory / "outcome.json", outcome, immutable=True)
            # Always save a clearly labelled facts artifact, including failed/partial encounters.
            write_json(directory / "facts.json", {"encounter_id": doc.encounter_id, "subset": doc.subset,
                "status": outcome["status"], "extraction": outcome.get("result")}, immutable=True)
            requests = [r for r in ledger.rows() if r["document_id"] == doc.document_id]
            write_json(directory / "requests.json", requests, immutable=True)
            (directory / "summary.md").write_text(summarize(doc, outcome, requests), encoding="utf-8", newline="\n")
            print(json.dumps({"encounter_id": doc.encounter_id, "status": outcome["status"],
                "facts": len((outcome.get("result") or {}).get("facts", [])), "requests": len(requests)}), flush=True)
    finally:
        lock.unlink()
    return report(root)


def report(root):
    docs = load_inputs(root)
    records = []
    for d in docs:
        p = root / "encounters" / d.encounter_id / "facts.json"
        value = read(p) if p.exists() else {"status": "NOT_PROCESSED", "extraction": None}
        records.append({"encounter_id": d.encounter_id, "subset": d.subset, "status": value["status"],
            "facts": len((value["extraction"] or {}).get("facts", [])),
            "relationships": len((value["extraction"] or {}).get("relationships", []))})
    requests = []
    if (root / "requests.sqlite3").exists():
        with sqlite3.connect(root / "requests.sqlite3") as db:
            db.row_factory = sqlite3.Row
            requests = [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY reserved_at")]
    usage = [json.loads(r["usage"]) for r in requests if r["usage"] and json.loads(r["usage"]) is not None]
    result = {"validation_scope": "JSON/schema, exact source IDs/quotes/offsets/turn mapping only; not clinical accuracy",
        "encounters": records, "successfully_processed": sum(r["status"] == "VALID" for r in records),
        "provider_requests_including_failures": len(requests),
        "structural_repair_requests": sum(r["attempt"] == 2 for r in requests),
        "latency_seconds_total": sum(r["latency_seconds"] or 0 for r in requests),
        "usage_records": len(usage), "token_totals_observed": {key: sum(u[key] for u in usage if isinstance(u.get(key), int))
            for key in sorted({k for u in usage for k in u if isinstance(u[k], int)})},
        "requests": requests}
    write_json(root / "report.json", result)
    return result
