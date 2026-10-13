"""One source-only call at a time per document; fifty workers, bounded failure retries."""
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from time import perf_counter
from ..clinical_notes.dataset import sha, write_json
from .contract import prompt, schema, resolve

CONFIG = {"model": "gpt-6-luna", "reasoning_effort": "high", "concurrency": 50,
    "timeout_seconds": 300, "max_attempts_per_document": 3, "total_dispatch_cap": 294,
    "retry_only": ["failed", "invalid"], "provider_internal_retries": 0,
    "additional_extraction_stages": 0, "nlp_components": 0}


def execute(docs, root, provider, manifest, *, concurrency=50, max_attempts=3):
    if not 1 <= concurrency <= CONFIG["concurrency"] or not 1 <= max_attempts <= 3:
        raise ValueError("Unapproved dispatch configuration")
    guard, records, began = Lock(), [], perf_counter()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "runner.lock"
    with lock_path.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    shape = schema()

    def work(doc):
        text = prompt(doc)
        if sha(text) != manifest["per_note_prompt_sha256"][doc.document_id]:
            raise ValueError("Frozen source-only prompt changed")
        for attempt in range(1, max_attempts + 1):
            folder = root / "requests" / doc.document_id.replace(":", "_") / f"attempt-{attempt}"
            with guard:
                if len(records) >= CONFIG["total_dispatch_cap"]:
                    return "budget_exhausted"
                folder.mkdir(parents=True, exist_ok=False)
                row = {"document_id": doc.document_id, "attempt": attempt,
                    "prompt_sha256": sha(text), "status": "reserved"}
                write_json(folder / "reservation.json", row, immutable=True)
                records.append(row)
            started, status, usage, error = perf_counter(), "failed", None, None
            try:
                write_json(folder / "schema.json", shape, immutable=True)
                with (folder / "prompt.txt").open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                raw, usage = provider.dispatch(doc, folder.resolve())
                if not (folder / "raw-response.json").exists():
                    raise RuntimeError("Raw response not durable before validation")
                try:
                    value = resolve(raw, doc)
                except ValueError as exc:
                    status, error = "invalid", str(exc)
                else:
                    write_json(folder / "result.json", value, immutable=True)
                    status = "valid"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            usage_path = folder / "usage.json"
            if usage_path.exists():
                usage = json.loads(usage_path.read_text(encoding="utf-8"))
            raw_path = folder / "raw-response.json"
            row.update(status=status, error=error, usage=usage,
                latency_seconds=perf_counter()-started,
                raw_sha256=sha(raw_path.read_bytes()) if raw_path.exists() else None)
            write_json(folder / "outcome.json", row, immutable=True)
            print(json.dumps({k:row[k] for k in ["document_id", "attempt", "status", "error"]}), flush=True)
            if status == "valid":
                return status
        return status
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            outcomes = list(pool.map(work, docs))
    finally:
        lock_path.unlink()
    rows = sorted(records, key=lambda r:(r["document_id"],r["attempt"]))
    with (root / "dispatch-outcomes.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in rows))
    result = {"calls": len(rows), "initial_calls": sum(r["attempt"] == 1 for r in rows),
        "retry_calls": sum(r["attempt"] > 1 for r in rows),
        "attempt_statuses": dict(Counter(r["status"] for r in rows)),
        "final_document_statuses": dict(Counter(outcomes)), "wall_seconds": perf_counter()-began}
    write_json(root / "execution-summary.json", result, immutable=True)
    return result
