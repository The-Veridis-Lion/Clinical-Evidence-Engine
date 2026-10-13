"""Immutable first attempts, source-only targeted repairs and explicit dispatch accounting."""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from . import VERSION
from .contract import CONFIG, PROMOTION, prompt, schema, inspect, recover, repair_prompt, repair_schema, merge_repair
from .offline import reconcile
from .preparation import prepare
from ..clinical_notes.dataset import sha, write_json
from ..luna_source.runtime import SourceProvider, read, rows
from ..provider import ProviderConfig
from ..simsum_comparison.ledger import Ledger, now
from ..simsum_comparison.__main__ import documents
from ..luna_round2.contract import stable_hash
from ..luna_rescore.evaluation import verify_index, ledger_count


def provider():
    return SourceProvider(ProviderConfig(model=CONFIG["model"], reasoning_effort="high", timeout_seconds=CONFIG["timeout_seconds"]))


def code_hashes(repo):
    return {str(p.relative_to(repo)): sha(p.read_bytes()) for p in sorted((repo/"src/clinical_intelligence").rglob("*.py"))
        if "sol_comparison" not in p.relative_to(repo).parts}


def initialize(repo, root):
    previous = repo/"artifacts/luna-source-constrained-v1"
    verify_index(previous)
    previous_manifest = read(previous/"manifest.json")
    p = provider(); p.preflight()
    protected = dict(previous_manifest["protected_files"])
    for n,h in read(previous/"artifact-index.json")["files"].items():
        protected[str((previous/n).relative_to(repo))] = h
    for name in ("artifact-index.json",): protected[str((previous/name).relative_to(repo))] = sha((previous/name).read_bytes())
    for name in ("manifest.json", "implementation.patch"):
        file = repo/"artifacts/luna-source-delivery-v1"/name
        protected[str(file.relative_to(repo))] = sha(file.read_bytes())
    docs = documents(repo)
    m = {"version": VERSION, "config": CONFIG, "promotion_rule": PROMOTION,
        "comparison_ids": previous_manifest["comparison_ids"], "code_hashes": code_hashes(repo),
        "protected_files": protected, "historical_ledger_counts": {
            **previous_manifest["historical_ledger_counts"], str((previous/"requests.sqlite3").relative_to(repo)): ledger_count(previous/"requests.sqlite3")},
        "provider": {"cli_version": p.cli_version, "capabilities": p.capabilities, "argv": p.command(Path("FROZEN_REQUEST"))},
        "contracts": {d.document_id: {"prompt_sha256": sha(prompt(d)), "schema_sha256": stable_hash(schema(d)),
            "note_sha256": d.note_sha256, "preparation_sha256": stable_hash(prepare(d))} for d in docs},
        "branch": subprocess.run(["git","branch","--show-current"], cwd=repo, capture_output=True,text=True,check=True).stdout.strip(),
        "head": subprocess.run(["git","rev-parse","HEAD"], cwd=repo,capture_output=True,text=True,check=True).stdout.strip(),
        "budget_basis": "New user-authorized round 100+25 and conditional300+75; closed historical ledgers unchanged; no stricter project-wide active limit discovered",
        "evaluation_contract": "luna-offline-rescore-v1 frozen chest-pain projection + original silver and confirmed overlay separate; exact v2 reproduction required",
        "retry_policy": "At most one additional dispatch/document, structural errors only or proven local pre-turn transport failure; uncertain completion never replayed; no label/score access in runner",
        "baseline_policy": "Do not alter recommended baseline before passing pilot and fresh300 gates"}
    write_json(root/"manifest.json", m, immutable=True)
    write_json(root/"inputs-freeze.json", [d.__dict__ for d in docs], immutable=True)
    integrity(repo, root)
    return m


def integrity(repo, root):
    m = read(root/"manifest.json")
    if code_hashes(repo) != m["code_hashes"]: raise ValueError("Frozen implementation changed")
    for name,h in m["protected_files"].items():
        if sha((repo/name).read_bytes()) != h: raise ValueError("Historical artifact changed: " + name)
    for name,n in m["historical_ledger_counts"].items():
        if ledger_count(repo/name) != n: raise ValueError("Historical budget changed: " + name)
    for doc in documents(repo):
        c = m["contracts"][doc.document_id]
        if c != {"prompt_sha256": sha(prompt(doc)), "schema_sha256": stable_hash(schema(doc)),
                "note_sha256": doc.note_sha256, "preparation_sha256": stable_hash(prepare(doc))}:
            raise ValueError("Source or contract changed")
    return m


class Budget(Ledger):
    """Atomic per-phase initial/retry caps plus a shared500 cap. Terminal rows immutable."""
    def __init__(self, root, identity):
        super().__init__(root/"requests.sqlite3", identity, total_cap=CONFIG["total_cap"], batch_cap=CONFIG["final_initial_cap"])

    def reserve_request(self, phase, doc_id, kind, input_hash):
        if phase not in {"pilot", "final"} or kind not in {"initial", "retry"}: raise ValueError("unplanned dispatch")
        stage = phase+"."+kind
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM requests WHERE stage=? AND document_id=?", (stage,doc_id)).fetchone()
            if old:
                if old["input_hash"] != input_hash: raise ValueError("reserved input changed")
                return False
            if kind == "retry":
                parent = db.execute("SELECT status FROM requests WHERE stage=? AND document_id=?", (phase+".initial",doc_id)).fetchone()
                if not parent or parent["status"] not in {"invalid","failed"}: raise ValueError("valid output cannot trigger retry")
            cap = CONFIG[phase+"_"+("initial_cap" if kind=="initial" else "retry_cap")]
            if db.execute("SELECT COUNT(*) FROM requests WHERE stage=?",(stage,)).fetchone()[0] >= cap:
                raise RuntimeError("Phase dispatch budget exhausted")
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= CONFIG["total_cap"]:
                raise RuntimeError("Global dispatch budget exhausted")
            db.execute("INSERT INTO requests(stage,document_id,attempt,batch,input_hash,status,reserved_at) VALUES (?,?,1,?,?,'reserved',?)",
                (stage,doc_id,stage,input_hash,now()))
            return True


def folder(root, phase, doc_id):
    return root/phase/"requests"/doc_id.replace(":", "_")


def attempt(ledger, p, doc, directory, phase, kind, text, shape, *, initial=None):
    request_hash = stable_hash({"prompt": sha(text), "schema": shape, "config": CONFIG})
    if not ledger.reserve_request(phase,doc.document_id,kind,request_hash):
        raise ValueError("Previously reserved request must be reconciled, never redispatched")
    directory.mkdir(parents=True,exist_ok=False)
    write_json(directory/"schema.json",shape,immutable=True)
    write_json(directory/"input-identity.json",{"document_id":doc.document_id,"note_sha256":doc.note_sha256,
        "input_hash":request_hash,"phase":phase,"kind":kind},immutable=True)
    with (directory/"prompt.txt").open("x",encoding="utf-8",newline="\n") as f: f.write(text)
    started = perf_counter(); error = usage = raw_hash = None; state = "failed"
    outcome = {"status":"INVALID","result":None,"accepted_indices":[],"raw_facts":None,"errors":[]}
    try:
        raw,usage = p.dispatch(doc,directory)
        if not (directory/"raw-response.json").exists(): raise ValueError("Provider did not persist original output")
        outcome = merge_repair(raw,initial,doc) if initial else inspect(raw,doc)
        state = "valid" if outcome["status"]=="VALID" else "invalid"
        error = json.dumps(outcome["errors"]) if state=="invalid" else None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        transport = reconcile(directory)
        if transport["state"] == "COMPLETED_RAW_AVAILABLE":
            raw = (directory/"raw-response.json").read_text(encoding="utf-8")
            outcome = merge_repair(raw,initial,doc) if initial else inspect(raw,doc)
            state = "valid" if outcome["status"]=="VALID" else "invalid"
            outcome["provider_completion_reconciled"] = True
            if not (directory/"usage.json").exists():
                events=[]
                for line in (directory/"events.jsonl").read_text(encoding="utf-8").splitlines():
                    try: events.append(json.loads(line))
                    except ValueError: pass
                usage = next(e.get("usage") for e in reversed(events) if e.get("type")=="turn.completed")
                write_json(directory/"usage.json",usage,immutable=True)
        else: outcome["transport"] = transport
    finally:
        if (directory/"raw-response.json").exists(): raw_hash = sha((directory/"raw-response.json").read_bytes())
        if (directory/"usage.json").exists(): usage = read(directory/"usage.json")
        write_json(directory/"validation.json",outcome,immutable=True)
        ledger.finish(phase+"."+kind,doc.document_id,1,state,perf_counter()-started,usage,error,raw_hash)
    return outcome


def execute(repo,root,phase,*,supplied_provider=None,limit=None):
    m = integrity(repo,root)
    if phase not in {"pilot","final"}: raise ValueError("unknown phase")
    docs = documents(repo)
    if phase == "pilot": docs = [d for d in docs if d.document_id in m["comparison_ids"]]
    else:
        decision = read(root/"pilot-decision.json")
        if not decision["promote"] or decision["manifest_sha256"] != sha((root/"manifest.json").read_bytes()):
            raise ValueError("Pilot promotion gate not passed")
    ledger = Budget(root,{"manifest_sha256":sha((root/"manifest.json").read_bytes())})
    p = supplied_provider or provider(); p.preflight()
    if p.cli_version != m["provider"]["cli_version"]: raise ValueError("CLI version changed")
    lock=root/"runner.lock"
    with lock.open("x",encoding="utf-8") as f: f.write(json.dumps({"pid":os.getpid(),"phase":phase,"time":now()}))
    began=perf_counter(); before=len(ledger.rows())
    try:
        selected=docs[:limit] if limit else docs
        def first(doc):
            directory=folder(root,phase,doc.document_id)
            existing=next((r for r in ledger.rows() if r["stage"]==phase+".initial" and r["document_id"]==doc.document_id),None)
            if existing:
                if existing["status"]=="reserved":
                    raise RuntimeError("Interrupted reservation requires explicit local reconciliation; no redispatch")
                return
            outcome=attempt(ledger,p,doc,directory/"initial",phase,"initial",prompt(doc),schema(doc))
            print(json.dumps({"phase":phase,"document_id":doc.document_id,"first_pass":outcome["status"]}),flush=True)
        with ThreadPoolExecutor(max_workers=CONFIG["max_concurrency"]) as pool: list(pool.map(first,selected))
        # Stable source-ID ordering; no scorer, labels or reference matches enter retry selection.
        for doc in sorted(selected,key=lambda d:d.document_id):
            directory=folder(root,phase,doc.document_id)
            if (directory/"final-outcome.json").exists(): continue
            initial=read(directory/"initial/validation.json")
            outcome=initial; changes=[]; reason=None
            raw_path=directory/"initial/raw-response.json"
            if initial["status"]!="VALID" and raw_path.exists() and "transport" not in initial:
                raw=raw_path.read_text(encoding="utf-8")
                outcome,changes=recover(raw,doc)
                if outcome["status"]!="VALID": reason="targeted_structural_repair"
            elif initial.get("transport",{}).get("state")=="PROVEN_LOCAL_PRE_TURN_FAILURE":
                reason="proven_local_pre_turn_transport_retry"
            write_json(directory/"deterministic-recovery.json",{"changes":changes,"outcome":outcome,"retry_reason":reason},immutable=True)
            if reason:
                write_json(directory/"retry-warrant.json",{"reason":reason,"validator_errors":outcome["errors"],
                    "reconciliation":initial.get("transport"),"trigger":"structural/provider failure only; no gold or score consulted"},immutable=True)
                if any(r["stage"]==phase+".retry" and r["document_id"]==doc.document_id for r in ledger.rows()):
                    if not (directory/"retry/validation.json").exists(): raise RuntimeError("Unreconciled retry reservation")
                    repaired=read(directory/"retry/validation.json")
                else:
                    count=sum(r["stage"]==phase+".retry" for r in ledger.rows())
                    if count >= CONFIG[phase+"_retry_cap"]:
                        outcome={**outcome,"retry_not_dispatched":"phase retry budget exhausted"}
                        repaired=None
                    elif reason=="targeted_structural_repair":
                        repaired=attempt(ledger,p,doc,directory/"retry",phase,"retry",repair_prompt(doc,outcome,raw),repair_schema(doc,outcome),initial=outcome)
                    else:
                        repaired=attempt(ledger,p,doc,directory/"retry",phase,"retry",prompt(doc),schema(doc))
                if repaired:
                    # Failed repairs cannot discard independently valid initial facts.
                    if repaired.get("result") is not None: outcome=repaired
                    else: outcome={**outcome,"unresolved_retry":repaired}
            write_json(directory/"final-outcome.json",outcome,immutable=True)
            sources={s["source_id"]:s for s in prepare(doc)["source_catalogue"]}
            provenance=[]
            for index in outcome["accepted_indices"]:
                ids=outcome["raw_facts"][index]["evidence"]["source_ids"]
                provenance.append({"raw_fact_index":index,"source_ids":ids,"sources":[sources[s] for s in ids],
                    "note_sha256":doc.note_sha256,"method":"exact original-source lookup; no generated verbatim text"})
            write_json(directory/"offset-provenance.json",provenance,immutable=True)
            print(json.dumps({"phase":phase,"document_id":doc.document_id,"post_repair":outcome["status"],"retry_reason":reason}),flush=True)
    finally: lock.unlink()
    write_json(root/phase/"runs"/(now().replace(":","-")+".json"),{"wall_seconds":perf_counter()-began,
        "new_dispatches":len(ledger.rows())-before},immutable=True)
    integrity(repo,root)
    return {"new_dispatches":len(ledger.rows())-before,"total":len(ledger.rows())}
