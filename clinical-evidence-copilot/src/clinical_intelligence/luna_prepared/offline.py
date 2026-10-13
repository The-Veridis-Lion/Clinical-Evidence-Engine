"""Read-only historical diagnostics and explicit new-representation replay, zero dispatches."""
import json
from collections import Counter
from ..clinical_notes.dataset import sha, write_json
from ..luna_source.runtime import rows, folder, read, jsonl
from ..luna_source.contract import resolve as old_resolve
from ..luna_grounding.contract import catalogue as old_catalogue
from ..luna_rescore.evaluation import verify_index
from ..simsum_comparison.__main__ import documents
from .contract import inspect


def reconcile(directory):
    """CLI failure does not prove server failure. Only explicit local pre-turn failure is safe."""
    events = []
    path = directory / "events.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try: events.append(json.loads(line))
            except ValueError: pass
    stderr = (directory / "stderr.txt").read_text(encoding="utf-8") if (directory / "stderr.txt").exists() else ""
    raw = directory / "raw-response.json"
    started = sum(e.get("type") == "turn.started" for e in events)
    completed = sum(e.get("type") == "turn.completed" for e in events)
    tools = any(e.get("item", {}).get("type") in {"command_execution", "mcp_tool_call", "web_search", "file_change"} for e in events)
    if raw.exists() and completed == 1 and started == 1 and not tools:
        state = "COMPLETED_RAW_AVAILABLE"
    elif not events and not raw.exists() and "failed to initialize in-process app-server client" in stderr:
        state = "PROVEN_LOCAL_PRE_TURN_FAILURE"
    else:
        state = "UNCERTAIN_NO_REDISPATCH"
    return {"state": state, "turns_started": started, "turns_completed": completed,
        "raw_available": raw.exists(), "tool_violation": tools,
        "event_sha256": sha(path.read_bytes()) if path.exists() else None,
        "stderr_sha256": sha(stderr), "usage_known": completed == 1,
        "policy": "network errors/turn.failed/timeouts alone cannot establish server non-completion"}


def replay(repo, root):
    prior = repo / "artifacts/luna-source-constrained-v1"
    verify_index(prior)
    patch = repo / "artifacts/luna-source-delivery-v1/implementation.patch"
    manifest = read(repo / "artifacts/luna-source-delivery-v1/manifest.json")
    # The delivery manifest is independently retained; frozen historical code checked by file hash.
    frozen = read(prior / "implementation-freeze.json")
    for name, digest in frozen["code_hashes"].items():
        if sha((repo/name).read_bytes()) != digest: raise ValueError("Historical implementation changed: " + name)
    docs = {d.document_id: d for d in documents(repo)}
    diagnostics, conversions, counts = [], [], Counter()
    for row in rows(prior):
        name = row["stage"][-1]
        doc = docs[row["document_id"]]
        path = folder(prior, "comparison", name, doc.document_id)
        record = {"configuration": name, "document_id": doc.document_id, "historical_status": row["status"],
            "historical_error": row["error"], "note_sha256": doc.note_sha256, "transport": reconcile(path)}
        counts[name+"_"+row["status"]] += 1
        if (path/"raw-response.json").exists():
            raw = (path/"raw-response.json").read_text(encoding="utf-8")
            value = json.loads(raw)
            sources = {s["source_id"]: s for s in old_catalogue(doc)}
            try: old_resolve(raw, doc)
            except ValueError as exc: record["reproduced_validator_error"] = str(exc)
            changes = []
            for i, fact in enumerate(value["facts"]):
                term = fact.pop("original_term")
                selected = [sources[s] for s in fact["evidence"]["source_ids"]]
                changes.append({"fact_index": i, "historical_generated_term": term,
                    "new_python_anchor": selected[0]["quote"], "literal_old_term": any(term in s["quote"] for s in selected),
                    "source_ids": fact["evidence"]["source_ids"], "semantic_fields_unchanged": True})
            outcome = inspect(json.dumps(value), doc, sources=sources)
            record.update(replay_status=outcome["status"], conversion=changes, replay_errors=outcome["errors"])
            if row["status"] == "invalid" and outcome["status"] == "VALID": counts[name+"_offline_recovered"] += 1
            if outcome["status"] == "VALID": counts[name+"_replay_valid"] += 1
            conversions.append({"configuration": name, "document_id": doc.document_id,
                "status": outcome["status"], "result": outcome["result"], "source_raw_sha256": sha(raw),
                "method": "explicit representation conversion; old IDs unchanged; no semantic repair or new inference"})
        diagnostics.append(record)
    jsonl(root/"offline/diagnostics.jsonl", diagnostics)
    jsonl(root/"offline/converted-predictions.jsonl", conversions)
    result = {"counts": dict(counts), "new_dispatches": 0, "patch_sha256": sha(patch.read_bytes()),
        "historical_index_sha256": sha((prior/"artifact-index.json").read_bytes()),
        "provider_failures": [r for r in diagnostics if r["historical_status"] == "failed"],
        "retries_previously_disabled": "Explicit A/B preregistration required <=100 calls/configuration and no repair/repeated sampling. Not a provider limitation.",
        "limits": "Source anchoring is verified. Replayed clinical judgments are unchanged and may still be wrong; not a new measured model run."}
    write_json(root/"offline/summary.json", result, immutable=True)
    return result
