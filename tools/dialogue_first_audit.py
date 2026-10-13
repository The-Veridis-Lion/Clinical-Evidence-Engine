"""Replay mechanical validation from immutable pilot artifacts; no provider calls."""
import argparse
import json
import sqlite3
from pathlib import Path

from clinical_intelligence.clinical_notes.dataset import sha, write_json
from clinical_intelligence.clinical_notes.schema import validate_extraction
from clinical_intelligence.dialogue_first.contract import Extraction, inspect, inspect_repair, primary_projection
from clinical_intelligence.dialogue_first.dataset import load_inputs, source_index
from clinical_intelligence.dialogue_first.runtime import implementation_hashes


def audit(root):
    frozen = json.loads((root / "execution-freeze.json").read_text(encoding="utf-8"))
    if frozen["implementation"] != implementation_hashes():
        raise ValueError("Frozen implementation changed")
    if frozen["selection_sha256"] != sha((root / "selection.json").read_bytes()) or frozen["inputs_sha256"] != sha((root / "inputs.json").read_bytes()):
        raise ValueError("Frozen selection or inputs changed")
    with sqlite3.connect(f"file:{(root / 'requests.sqlite3').as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        requests = [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY reserved_at")]
    if len(requests) > 20 or any(r["attempt"] not in (1, 2) for r in requests):
        raise ValueError("Request budget exceeded")
    records = []
    for doc in load_inputs(root):
        directory = root / "encounters" / doc.encounter_id
        path = directory / "outcome.json"
        if not path.exists():
            records.append({"encounter_id": doc.encounter_id, "status": "NOT_PROCESSED"})
            continue
        outcome = json.loads(path.read_text(encoding="utf-8"))
        catalogue = {s["source_id"]: s for s in source_index(doc)["source_catalogue"]}
        spans = 0
        if outcome.get("result") is not None:
            parsed = Extraction.model_validate(outcome["result"])
            validate_extraction(json.dumps(primary_projection(parsed.model_dump())), doc)
            for f in parsed.facts:
                evidence = [f.evidence, *f.supporting_evidence]
                if len(f.provenance) != len(evidence):
                    raise ValueError("Evidence/provenance count mismatch")
                for p, e in zip(f.provenance, evidence):
                    value = p.model_dump(exclude={"document_id"})
                    if catalogue.get(p.source_id) != value or p.document_id != doc.document_id:
                        raise ValueError("Saved provenance differs from original turn index")
                    if e.model_dump() != {k: value[k] for k in ("quote", "start", "end")}:
                        raise ValueError("Evidence differs from provenance")
                    spans += 1
            for r in parsed.relationships:
                if not 0 <= r.from_fact_index < len(parsed.facts) or not 0 <= r.to_fact_index < len(parsed.facts):
                    raise ValueError("Saved relationship index invalid")
                for p in r.provenance:
                    if catalogue.get(p.source_id) != p.model_dump(exclude={"document_id"}) or p.document_id != doc.document_id:
                        raise ValueError("Saved relationship provenance invalid")
        # Revalidate each completed raw response, including invalid/partial attempts.
        replayed = []
        initial_raw = initial = None
        for row in (r for r in requests if r["document_id"] == doc.document_id):
            folder = directory / f"attempt-{row['attempt']}"
            if row["status"] in {"reserved", "FAILED"}:
                continue
            raw = (folder / "raw-response.json").read_text(encoding="utf-8")
            validation = inspect(raw, doc) if row["attempt"] == 1 else inspect_repair(raw, initial_raw, initial, doc)
            saved = json.loads((folder / "validation.json").read_text(encoding="utf-8"))
            if validation != saved:
                raise ValueError("Mechanical replay differs from original validation")
            if row["attempt"] == 1:
                initial_raw, initial = raw, validation
            replayed.append(validation)
        if outcome["status"] == "VALID" and not any(v["status"] == "VALID" and v["result"] == outcome["result"] for v in replayed):
            raise ValueError("Final valid result has no validated original response")
        records.append({"encounter_id": doc.encounter_id, "status": outcome["status"],
            "fact_evidence_spans_checked": spans, "completed_raw_attempts_replayed": len(replayed)})
    result = {"scope": "Mechanical integrity only; not clinical accuracy", "requests_including_failures": len(requests), "encounters": records}
    write_json(root / "mechanical-audit.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("artifacts/dialogue-first-v1"))
    args = parser.parse_args()
    print(json.dumps(audit(args.root.resolve()), ensure_ascii=False, indent=2))
