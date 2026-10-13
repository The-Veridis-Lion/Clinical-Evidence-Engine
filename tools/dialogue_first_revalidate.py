"""Offline index-repair revalidation of saved responses; historical artifacts stay immutable."""
import argparse
import json
import sqlite3
from pathlib import Path

from clinical_intelligence.clinical_notes.dataset import sha, write_json
from clinical_intelligence.dialogue_first.contract import inspect, inspect_repair
from clinical_intelligence.dialogue_first.dataset import load_inputs
from clinical_intelligence.dialogue_first.runtime import implementation_hashes, summarize

VERSION = "relationship-index-revalidation-v2"
ALLOWED_CHANGES = {"dialogue_first/contract.py", "dialogue_first/prompt.py"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def revalidate(root, encounter_id="D2N002"):
    root = root.resolve()
    # Read-only connection: neither request counts nor historical statuses can change.
    with sqlite3.connect(f"file:{(root / 'requests.sqlite3').as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        requests = [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY reserved_at")]
    if len(requests) > 20:
        raise ValueError("Historical request cap exceeded")
    frozen = read(root / "execution-freeze.json")
    current = implementation_hashes()
    changed = {k for k in current if current[k] != frozen["implementation"].get(k)}
    if set(current) != set(frozen["implementation"]) or not {k.replace("\\", "/") for k in changed} <= ALLOWED_CHANGES:
        raise ValueError("Unexpected implementation change during offline revalidation")
    for name in ("selection", "inputs"):
        if frozen[name + "_sha256"] != sha((root / (name + ".json")).read_bytes()):
            raise ValueError("Frozen input changed")
    doc = next((d for d in load_inputs(root) if d.encounter_id == encounter_id), None)
    if doc is None:
        raise ValueError("Encounter outside frozen selection")
    directory = root / "encounters" / encounter_id
    rows = [r for r in requests if r["document_id"] == doc.document_id]
    if [r["attempt"] for r in rows] != [1, 2] or rows[0]["status"] not in {"PARTIAL", "INVALID"} or rows[1]["status"] in {"reserved", "FAILED"}:
        raise ValueError("Require original and completed sole structural repair")
    first = directory / "attempt-1/raw-response.json"
    second = directory / "attempt-2/raw-response.json"
    initial_raw, repair_raw = first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8")
    initial = inspect(initial_raw, doc)
    if initial != read(directory / "attempt-1/validation.json"):
        raise ValueError("Initial mechanical validation changed unexpectedly")
    old_outcome = read(directory / "outcome.json")
    outcome = inspect_repair(repair_raw, initial_raw, initial, doc)
    if outcome["status"] != "VALID":
        raise ValueError("Saved repair still fails mechanical guard: " + str(outcome["errors"]))
    if outcome["result"]["facts"] != initial["result"]["facts"]:
        raise ValueError("Offline relationship-only replay changed facts")
    original, replacement = json.loads(initial_raw), json.loads(repair_raw)
    changes = [{"relationship_index": i, "field": k, "before": old[k], "after": new[k]}
        for i, (old, new) in enumerate(zip(original["relationships"], replacement["relationships"]))
        for k in ("from_fact_index", "to_fact_index") if old[k] != new[k]]
    protected = [root / n for n in ("requests.sqlite3", "execution-freeze.json", "selection.json", "inputs.json", "report.json", "mechanical-audit.json") if (root / n).exists()]
    protected += [p for p in directory.rglob("*") if p.is_file()]
    hashes = {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in protected}
    destination = root / "revalidation" / VERSION / encounter_id
    record = {"version": VERSION, "encounter_id": encounter_id, "historical_status": old_outcome["status"],
        "revalidated_status": outcome["status"], "provider_requests_added": 0,
        "provider_requests_total": len(requests), "facts_unchanged": True,
        "facts": len(outcome["result"]["facts"]), "relationships": len(outcome["result"]["relationships"]),
        "index_changes": changes, "historical_sha256": hashes, "frozen_implementation": frozen["implementation"],
        "current_implementation": current, "changed_implementation_files": sorted(changed),
        "scope": "Offline JSON/schema/source/index validation only; not clinical accuracy"}
    write_json(destination / "revalidation.json", record, immutable=True)
    write_json(destination / "outcome.json", outcome, immutable=True)
    write_json(destination / "facts.json", {"encounter_id": encounter_id, "subset": doc.subset,
        "status": "VALID", "extraction": outcome["result"]}, immutable=True)
    summary = "Offline revalidation of saved responses; 0 new requests. Historical ledger/statuses unchanged.\n\n" + summarize(doc, outcome, rows)
    path = destination / "summary.md"
    if path.exists() and path.read_text(encoding="utf-8") != summary:
        raise ValueError("Immutable revalidation summary differs")
    if not path.exists():
        path.write_text(summary, encoding="utf-8", newline="\n")
    if any(sha((root / name).read_bytes()) != digest for name, digest in hashes.items()):
        raise ValueError("Historical artifact changed during revalidation")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("artifacts/dialogue-first-v1"))
    parser.add_argument("--encounter", default="D2N002")
    args = parser.parse_args()
    result = revalidate(args.root, args.encounter)
    print(json.dumps({k: result[k] for k in ("encounter_id", "historical_status", "revalidated_status",
        "provider_requests_added", "provider_requests_total", "facts", "relationships", "index_changes")}, indent=2))
