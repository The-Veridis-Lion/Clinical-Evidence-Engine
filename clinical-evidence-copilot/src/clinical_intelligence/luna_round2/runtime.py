"""Separate persistent phase ledgers, one dispatch per planned stage/document, no replay."""
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.runner import SingleDispatchProvider
from ..provider import ProviderConfig
from ..simsum_comparison.ledger import Ledger, now
from ..simsum_comparison.execution import read
from ..simsum_comparison.evaluation import jsonl, load_jsonl
from ..simsum_comparison.__main__ import documents
from .contract import (CONFIG, APPROACHES, SELECTION_RULE, IndexedIdentify, IndexedExtraction,
    EXTRACT_INSTRUCTION, IDENTIFY_INSTRUCTION, stable_hash, prompt, validate_identify, resolve_extraction)

def code_hashes():
    return {str(p):sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}

def initialize(repo, root):
    docs = documents(repo)
    reviews_path = repo / "artifacts/gliner-luna-v1/source-only-adjudicated-mentions.jsonl"
    reviews = load_jsonl(reviews_path)
    reviewed_ids = {x["document_id"] for x in reviews}
    chosen = []
    for variant in ("text","advanced_text"):
        stratum = [d for d in docs if d.variant == variant]
        fixed = [d for d in stratum if d.document_id in reviewed_ids]
        rest = sorted([d for d in stratum if d.document_id not in reviewed_ids],
                      key=lambda d:sha(f"{CONFIG['seed']}:round2-selection:"+d.document_id))
        chosen += fixed + rest[:50-len(fixed)]
    assert len(chosen)==100 and len({d.row_id for d in chosen})==100 and len(reviewed_ids)==10
    provider = SingleDispatchProvider(ProviderConfig(model=CONFIG["model"],reasoning_effort=CONFIG["reasoning_effort"],timeout_seconds=300))
    provider.preflight()
    historical = read(repo / "artifacts/gliner-luna-v1/experiment_manifest.json")
    protected = historical["protected_files"] | historical["historical_raw_hashes"]
    for folder in (repo/"docs",repo/"examples/clinical_notes",repo/"artifacts/gliner-luna-v1"):
        for p in folder.rglob("*"):
            if p.is_file() and (p.name in {"raw-response.json","metrics.json","luna-requests.sqlite3"} or
                p.suffix in {".md",".jsonl"} and "events.jsonl" != p.name):
                protected[str(p.relative_to(repo))] = sha(p.read_bytes())
    for p,h in protected.items():
        if sha((repo/p).read_bytes()) != h:
            raise ValueError("Historical integrity mismatch: "+p)
    manifest = {"version":"luna-round2-v1","config":CONFIG,"approaches":APPROACHES,
        "selection_rule":SELECTION_RULE,"comparison_ids":[d.document_id for d in chosen],
        "cohort":[{"document_id":d.document_id,"row_id":d.row_id,"variant":d.variant,"note_sha256":d.note_sha256,
                   "source_sha256":d.source_sha256} for d in docs],
        "cohort_path":"examples/clinical_notes/v2/batch2.json",
        "cohort_sha256":sha((repo/"examples/clinical_notes/v2/batch2.json").read_bytes()),
        "partition_sha256":sha((repo/"examples/clinical_notes/v1/partition.json").read_bytes()),
        "audit_source_sha256":sha(reviews_path.read_bytes()),
        "final_audit_sha256":sha((root/"source-review-final.jsonl").read_bytes()),
        "schemas":{"identify":IndexedIdentify.model_json_schema(),"extract":IndexedExtraction.model_json_schema()},
        "prompt_hashes":{"identify":sha(IDENTIFY_INSTRUCTION),"extract":sha(EXTRACT_INSTRUCTION)},
        "code_hashes":code_hashes(),"protected_files":protected,
        "provider":{"cli_version":provider.cli_version,"argv":provider.command(Path('FROZEN_REQUEST'))},
        "maximum_planned_new_dispatches":300+600,
        "data_role":"Previously used development cohort; no unseen holdout",
        "audit_limitations":"Known nonexpert source review; not independent clinical ground truth"}
    write_json(root/"manifest.json",manifest,immutable=True)
    jsonl(root/"source-review-selection.jsonl",reviews)
    write_json(root/"inputs-freeze.json",[{"document_id":d.document_id,**d.__dict__} for d in docs],immutable=True)
    print(json.dumps({"phase":"init","documents":300,"comparison":100,"max_new_calls":900}))
    return manifest

def integrity(repo, root):
    manifest=read(root/"manifest.json")
    if code_hashes()!=manifest["code_hashes"]:
        raise ValueError("Frozen Round 2 code changed")
    if sha((root/"source-review-final.jsonl").read_bytes())!=manifest["final_audit_sha256"]:
        raise ValueError("Frozen final source audit changed")
    for p,h in manifest["protected_files"].items():
        if sha((repo/p).read_bytes())!=h:
            raise ValueError("Historical file changed: "+p)
    return manifest

def result_path(root, phase, approach, stage, doc_id):
    return root/phase/"requests"/(approach+"."+stage)/doc_id.replace(":","_")

def result(root, phase, approach, stage, doc_id):
    p=result_path(root,phase,approach,stage,doc_id)/"result.json"
    return read(p) if p.exists() else None

def execute(repo, root, phase, approach, *, limit=None, provider=None):
    manifest=integrity(repo,root)
    if approach not in APPROACHES or phase not in {"comparison","final"}:
        raise ValueError("Unplanned approach/phase")
    docs=documents(repo)
    if phase=="comparison":
        docs=[d for d in docs if d.document_id in manifest["comparison_ids"]]
        phase_cap=300
    else:
        winner=read(root/"winner-freeze.json")
        if approach!=winner["winner"] or winner["manifest_sha256"]!=sha((root/"manifest.json").read_bytes()):
            raise ValueError("Final evaluation must use the frozen winner")
        phase_cap=300*APPROACHES[approach]
    identity={"manifest_sha256":sha((root/"manifest.json").read_bytes()),"phase":phase,
              "winner":approach if phase=="final" else None}
    ledger=Ledger(root/phase/"requests.sqlite3",identity,total_cap=phase_cap,batch_cap=200 if phase=="comparison" else 600)
    provider=provider or SingleDispatchProvider(ProviderConfig(model=CONFIG["model"],reasoning_effort=CONFIG["reasoning_effort"],timeout_seconds=300))
    provider.preflight()
    if provider.cli_version!=manifest["provider"]["cli_version"]:
        raise ValueError("Provider version changed")
    lock=root/"runner.lock"
    lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open("x",encoding="utf-8") as stream:
        stream.write(json.dumps({"pid":os.getpid(),"phase":phase,"approach":approach,"started_at":now()}))
    began=perf_counter()
    before=len(ledger.rows())
    def dispatch(doc, stage, hints=None):
        text=prompt(doc,stage,hints)
        schema=(IndexedIdentify if stage=="identify" else IndexedExtraction).model_json_schema()
        input_hash=stable_hash({"prompt":text,"schema":schema,"provider":manifest["provider"],"config":CONFIG})
        stage_key=approach+"."+stage
        if not ledger.reserve(stage_key,doc.document_id,1,approach,input_hash):
            return result(root,phase,approach,stage,doc.document_id)
        folder=result_path(root,phase,approach,stage,doc.document_id).resolve()
        started=perf_counter()
        status,usage,error,raw_hash="failed",None,None,None
        normalized=None
        try:
            folder.mkdir(parents=True,exist_ok=False)
            write_json(folder/"schema.json",schema,immutable=True)
            write_json(folder/"input-identity.json",{"input_hash":input_hash,"document_id":doc.document_id,
                "note_sha256":doc.note_sha256,"phase":phase,"approach":approach,"stage":stage},immutable=True)
            with (folder/"prompt.txt").open("x",encoding="utf-8",newline="\n") as stream:
                stream.write(text)
            raw,usage=provider.dispatch(doc,folder)
            try:
                if stage=="identify":
                    normalized=validate_identify(raw,doc)
                else:
                    normalized,provenance=resolve_extraction(raw,doc)
                    write_json(folder/"offset-provenance.json",provenance,immutable=True)
            except ValueError as exc:
                status,error="invalid",str(exc)
            else:
                write_json(folder/"result.json",normalized,immutable=True)
                status="valid"
        except Exception as exc:
            error=f"{type(exc).__name__}: {exc}"
        finally:
            if (folder/"usage.json").exists(): usage=read(folder/"usage.json")
            if (folder/"raw-response.json").exists(): raw_hash=sha((folder/"raw-response.json").read_bytes())
            ledger.finish(stage_key,doc.document_id,1,status,perf_counter()-started,usage,error,raw_hash)
        print(json.dumps({"phase":phase,"approach":approach,"stage":stage,"document_id":doc.document_id,
                          "status":status,"error":error}),flush=True)
        return normalized if status=="valid" else None
    def work(doc):
        hints=None
        if APPROACHES[approach]==2:
            identified=dispatch(doc,"identify")
            if identified is None: return "blocked_identify"
            hints=identified["evidence_ids"]
        return "valid" if dispatch(doc,"extract",hints) else "failed_or_invalid"
    try:
        with ThreadPoolExecutor(max_workers=CONFIG["max_concurrency"]) as pool:
            statuses=list(pool.map(work,docs[:limit] if limit else docs))
    finally:
        lock.unlink()
    after=len(ledger.rows())
    write_json(root/phase/"runs"/(now().replace(":","-")+".json"),
        {"phase":phase,"approach":approach,"wall_seconds":perf_counter()-began,
         "new_dispatches":after-before,"processed":len(statuses),"statuses":statuses},immutable=True)
    return statuses
