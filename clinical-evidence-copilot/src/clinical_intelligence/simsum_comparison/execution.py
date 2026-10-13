"""Resumable, budgeted Luna phases. Cache only byte-identical prompts/schema/config."""
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from ..clinical_notes.runner import SingleDispatchProvider
from ..provider import ProviderConfig
from ..clinical_notes.schema import ClinicalNoteExtraction, validate_extraction
from ..clinical_notes.dataset import sha, write_json
from .contract import (CONFIG, Identify, Verification, stable_hash, identify_prompt, extract_prompt,
                       union_candidates, verify_prompt, validate_candidates, validate_verification)
from .ledger import Ledger, now

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def request_folder(root, stage, doc, attempt):
    return root / "requests" / stage / doc.replace(":", "_") / f"attempt-{attempt}"

def effective(root, stage, doc):
    for attempt in (2,1):
        path = request_folder(root,stage,doc,attempt) / "result.json"
        if path.exists():
            return read(path)
    alias = root / "cache-aliases" / stage / (doc.replace(":", "_")+".json")
    if alias.exists():
        record = read(alias)
        if record.get("status","valid") != "valid":
            return None
        result = effective(root,record["source_stage"],doc)
        if result is None:
            raise ValueError("Invalid cache alias")
        return result
    return None

def run_phase(root, documents, stage, *, pilot=False):
    identity = read(root / "experiment_manifest.json")
    inference_files = ("contract.py","execution.py","ledger.py","gliner.py")
    hashes = {name:sha((Path(__file__).parent / name).read_bytes()) for name in inference_files}
    freeze_path = root / "inference-code-freeze.json"
    if freeze_path.exists():
        original_hashes = read(freeze_path)
        if any(original_hashes[name] != hashes[name] for name in ("contract.py","gliner.py")):
            raise ValueError("Frozen inference contract/model/ledger implementation changed")
    else:
        write_json(freeze_path,hashes,immutable=True)
    provenance_hash = stable_hash(hashes)
    write_json(root / "implementation-provenance" / (provenance_hash+".json"),
        {"hashes":hashes,"software_version":"execution-v1.2",
         "fix":"Preserve source-only verification with unavailable Luna; reuse identical Extract failures/reservations across stages instead of redispatching"},immutable=True)
    ledger = Ledger(root / "luna-requests.sqlite3", identity["execution_contract"])
    provider = SingleDispatchProvider(ProviderConfig(timeout_seconds=CONFIG["timeout_seconds"]))
    provider.preflight()
    chosen = documents[:5]+documents[150:155] if pilot else documents
    schema = Identify.model_json_schema() if stage == "identify" else Verification.model_json_schema() if stage == "verify" else ClinicalNoteExtraction.model_json_schema()
    lock = root / "luna-runner.lock"
    with lock.open("x",encoding="utf-8") as f:
        f.write(json.dumps({"pid": os.getpid(), "stage": stage, "started_at": now()}))
    began = perf_counter()
    results = []
    from threading import Event, Lock
    stop, guard = Event(), Lock()
    failure_streak = [0]

    def work(doc):
        if stop.is_set():
            return {"document_id":doc.document_id,"status":"stopped_after_repeated_infrastructure_failures"}
        union = None
        if stage == "identify":
            prompt = identify_prompt(doc)
        elif stage == "verify":
            a = effective(root,"identify",doc.document_id)
            b_path = root / "gliner" / doc.document_id.replace(":", "_") / "prediction.json"
            if not b_path.exists():
                return {"document_id": doc.document_id, "status": "blocked_upstream"}
            b = read(b_path)
            union = union_candidates(a["candidates"] if a else [], b["candidates"])
            # Every union is source-only. Prioritize disagreements in scheduling, never expose reference labels.
            prompt = verify_prompt(doc,union)
        else:
            system = "luna" if "luna" in stage else "gliner"
            if stage.endswith("verified"):
                path = root / "verified" / system / (doc.document_id.replace(":", "_")+".json")
                if not path.exists():
                    return {"document_id": doc.document_id, "status": "blocked_upstream"}
                candidates = read(path)["candidates"]
            elif system == "luna":
                record = effective(root,"identify",doc.document_id)
                if record is None:
                    return {"document_id": doc.document_id, "status": "blocked_upstream"}
                candidates = record["candidates"]
            else:
                path = root / "gliner" / doc.document_id.replace(":", "_") / "prediction.json"
                if not path.exists():
                    return {"document_id": doc.document_id, "status": "blocked_upstream"}
                candidates = read(path)["candidates"]
            prompt = extract_prompt(doc,candidates)
        input_hash = stable_hash({"prompt": prompt, "schema": schema, "model": CONFIG["model"],
                                  "reasoning_effort": CONFIG["reasoning_effort"], "provider": identity["provider_contract"]})
        if stage.startswith("extract_"):
            previous = [r for r in ledger.rows() if r["stage"].startswith("extract_") and r["stage"] != stage and r["document_id"] == doc.document_id
                        and r["status"] == "valid" and r["input_hash"] == input_hash]
            if previous:
                original_stage = previous[-1]["stage"]
                alias = root / "cache-aliases" / stage / (doc.document_id.replace(":", "_")+".json")
                write_json(alias,{"document_id": doc.document_id,"source_stage":original_stage,
                    "source_attempt":previous[-1]["attempt"],"input_hash":input_hash,"reason":"identical prompt/schema/model/provider"},immutable=True)
                return {"document_id":doc.document_id,"status":"cached_identical"}
            prior_outcomes = [r for r in ledger.rows() if r["stage"].startswith("extract_") and r["stage"] != stage
                              and r["document_id"] == doc.document_id and r["input_hash"] == input_hash]
            if prior_outcomes:
                source = prior_outcomes[-1]
                write_json(root / "cache-aliases" / stage / (doc.document_id.replace(":","_")+".json"),
                    {"document_id":doc.document_id,"source_stage":source["stage"],"source_attempt":source["attempt"],
                     "input_hash":input_hash,"status":source["status"],"reason":"identical input already dispatched; no replay after failure or reservation"},immutable=True)
                return {"document_id":doc.document_id,"status":"cached_identical_"+source["status"]}
        rows = [r for r in ledger.rows() if r["stage"] == stage and r["document_id"] == doc.document_id]
        if rows and rows[-1]["input_hash"] != input_hash:
            raise ValueError("Frozen stage input changed")
        attempt = 2 if rows and rows[-1]["status"] == "invalid" and rows[-1]["attempt"] == 1 else 1
        if rows and (rows[-1]["status"] != "invalid" or rows[-1]["attempt"] == 2):
            return {"document_id":doc.document_id,"status":rows[-1]["status"],"cached":True}
        while attempt <= 2:
            if not ledger.reserve(stage,doc.document_id,attempt,stage,input_hash):
                return {"document_id":doc.document_id,"status":"already_reserved"}
            folder = request_folder(root,stage,doc.document_id,attempt).resolve()
            started = perf_counter()
            status, usage, error, raw_hash = "failed", None, None, None
            try:
                folder.mkdir(parents=True,exist_ok=False)
                write_json(folder / "schema.json",schema,immutable=True)
                write_json(folder / "input-identity.json",{"input_hash":input_hash,"note_sha256":doc.note_sha256,
                            "stage":stage,"document_id":doc.document_id,"implementation_provenance_sha256":provenance_hash},immutable=True)
                with (folder / "prompt.txt").open("x",encoding="utf-8",newline="\n") as f:
                    f.write(prompt)
                raw,usage = provider.dispatch(doc,folder)
                raw_hash = sha((folder / "raw-response.json").read_bytes())
                try:
                    if stage == "identify":
                        result = validate_candidates(raw,doc)
                    elif stage == "verify":
                        result = validate_verification(raw,doc,union)
                    else:
                        result = validate_extraction(raw,doc)
                except ValueError as e:
                    status,error = "invalid",str(e)
                else:
                    write_json(folder / "result.json",result.model_dump(),immutable=True)
                    status = "valid"
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
            finally:
                if usage is None and (folder / "usage.json").exists():
                    usage = read(folder / "usage.json")
                if raw_hash is None and (folder / "raw-response.json").exists():
                    raw_hash = sha((folder / "raw-response.json").read_bytes())
                ledger.finish(stage,doc.document_id,attempt,status,perf_counter()-started,usage,error,raw_hash)
            print(json.dumps({"stage":stage,"document_id":doc.document_id,"attempt":attempt,"status":status,
                              "error":error}),flush=True)
            with guard:
                failure_streak[0] = failure_streak[0]+1 if status == "failed" else 0
                if failure_streak[0] >= 10:
                    stop.set()
            if status != "invalid" or attempt == 2:
                return {"document_id":doc.document_id,"status":status}
            attempt += 1

    try:
        if stage == "verify":
            # Deterministic disagreement-first priority. No references are read by the execution module.
            def priority(d):
                a = effective(root,"identify",d.document_id)
                p = root / "gliner" / d.document_id.replace(":", "_") / "prediction.json"
                from .contract import canonical_candidates
                mismatch = a is None or not p.exists() or canonical_candidates(a["candidates"]) != canonical_candidates(read(p)["candidates"])
                return (not mismatch, d.document_id)
            chosen = sorted(chosen,key=priority)
        with ThreadPoolExecutor(max_workers=CONFIG["max_concurrency"]) as pool:
            results = list(pool.map(work,chosen))
    finally:
        lock.unlink()
    run_id = now().replace(":", "_")
    write_json(root / "runs" / f"{stage}-{run_id}.json",{"stage":stage,"pilot":pilot,"wall_seconds":perf_counter()-began,
             "results":results},immutable=True)
    return results
