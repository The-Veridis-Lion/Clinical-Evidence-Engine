"""Reuse frozen one-to-one scoring; separate silver, source audit and operational coverage."""
import json
import sqlite3
from collections import Counter
from statistics import mean, median
from .contract import APPROACHES, stable_hash
from .runtime import result, result_path, integrity
from ..simsum_comparison.execution import read
from ..simsum_comparison.evaluation import references, score, facts_candidates, load_jsonl, jsonl
from ..simsum_comparison.auditing import excluded
from ..clinical_notes.evaluation import match_mentions, metrics
from ..clinical_notes.normalization import concept_group
from ..clinical_notes.schema import validate_extraction
from ..clinical_notes.dataset import sha, write_json
from ..simsum_comparison.__main__ import documents

def ledger_rows(root,phase):
    p=root/phase/"requests.sqlite3"
    if not p.exists(): return []
    with sqlite3.connect(f"file:{p.as_posix()}?mode=ro",uri=True) as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY reserved_at")]

def assertion_score(docs,results,reviews):
    tp=pp=rr=complete=available=wrong_status=0
    details=[]
    for doc in docs:
        if doc.document_id not in reviews: continue
        review=reviews[doc.document_id]
        candidate=results.get(doc.document_id)
        facts=[f for f in candidate["facts"] if concept_group(f["concept"]) and not excluded(f["evidence"],review)] if candidate else []
        # Preserve independent nasal manifestations and polarity. Exact duplicate facts alone deduplicate.
        facts=list({stable_hash({k:f[k] for k in ("concept","original_term","polarity","experiencer","evidence")}):f for f in facts}.values())
        plain=[{"concept":concept_group(f["concept"]),**f["evidence"]} for f in facts]
        p=[{**q,"concept":q["concept"]+":"+f["polarity"]+":"+f["experiencer"]} for q,f in zip(plain,facts)]
        r=[{**x,"symptom":x["symptom"]+":"+x["polarity"]+":"+x["experiencer"]} for x in review["references"]]
        pairs=match_mentions(p,r)
        plain_pairs=match_mentions(plain,review["references"])
        tp+=len(pairs);pp+=len(p);rr+=len(r);available+=candidate is not None
        good=candidate is not None and len(pairs)==len(p)==len(r)
        complete+=good
        wrong_status+=len(plain_pairs)-len(pairs)
        details.append({"document_id":doc.document_id,"source_references":review["references"],"facts":facts,
            "matches":pairs,"missing":[j for j in range(len(r)) if j not in {j for i,j in pairs}],
            "unmatched":[i for i in range(len(p)) if i not in {i for i,j in pairs}],"complete":good,
            "structurally_available":candidate is not None,"note_sha256":doc.note_sha256})
    return {**metrics(tp,pp,rr),"documents":len(details),"available":available,"complete_cases":complete,
        "complete_case_rate":complete/len(details) if details else None,"localized_status_or_experiencer_mismatches":wrong_status,
        "scope":"Explicit reviewed symptom concept/span/polarity/experiencer; nonexpert review; no complete universal-fact gold"},details

def baseline(repo,docs,*,first=False):
    results={}
    for doc in docs:
        for attempt in ([1] if first else [2,1]):
            p=repo/"artifacts/clinical-notes-v2/requests"/doc.document_id.replace(":","_")/f"attempt-{attempt}"/"raw-response.json"
            if p.exists():
                try: results[doc.document_id]=validate_extraction(p.read_text(encoding="utf-8"),doc).model_dump()
                except ValueError: pass
                break
    return results

def summarize(docs,results,refs,reviews):
    predicted={i:facts_candidates(v) for i,v in results.items()}
    silver,details=score(docs,predicted,refs,{d.document_id for d in docs})
    for stratum,variant in (("all",None),("standard","text"),("advanced","advanced_text")):
        items=[x for x in details if variant is None or x["variant"]==variant]
        valid=[x for x in items if x["document_id"] in results]
        complete=sum(x["document_id"] in results and not x["missing_indices"] and not x["unmatched_indices"] for x in items)
        silver[stratum]["documents"]=len(items)
        silver[stratum]["valid_documents"]=len(valid)
        silver[stratum]["structural_success_rate"]=len(valid)/len(items) if items else None
        silver[stratum]["complete_mention_cases"]=complete
        silver[stratum]["complete_mention_case_rate"]=complete/len(items) if items else None
        silver[stratum]["complete_concept_cases"]=sum(x["concept_complete"] for x in valid)
    audited,audit_details=assertion_score(docs,results,reviews)
    return {"silver":silver,"audited":audited},details,audit_details

def evaluate(repo,root,phase):
    manifest=integrity(repo,root)
    all_docs=documents(repo)
    selection=set(manifest["comparison_ids"])
    docs=[d for d in all_docs if d.document_id in selection] if phase=="comparison" else all_docs
    refs,invalid=references(repo,docs)
    reviews={x["document_id"]:x for x in load_jsonl(root/("source-review-selection.jsonl" if phase=="comparison" else "source-review-final.jsonl"))}
    if phase=="final" and not reviews: reviews={x["document_id"]:x for x in load_jsonl(root/"source-review-selection.jsonl")}
    for doc in docs:
        if doc.document_id in reviews and reviews[doc.document_id]["note_sha256"]!=doc.note_sha256: raise ValueError("Audit source changed")
    names=list(APPROACHES) if phase=="comparison" else [read(root/"winner-freeze.json")["winner"]]
    rows=ledger_rows(root,phase)
    metrics_out={"phase":phase,"version":"luna-round2-evaluation-v1","invalid_reference_offsets":len(invalid),
        "criteria":manifest["selection_rule"],"dispatches":len(rows),"systems":{},"known_usage_requests":0,
        "token_usage":dict(Counter()),"scope":"All-selected operational coverage; silver and audited reference kept separate"}
    usage=Counter()
    for row in rows:
        u=json.loads(row["usage"]) if row["usage"] else None
        if u:
            metrics_out["known_usage_requests"]+=1;usage.update({k:v for k,v in u.items() if type(v) is int})
    metrics_out["token_usage"]=dict(usage)
    for name in names:
        outputs={d.document_id:v for d in docs if (v:=result(root,phase,name,"extract",d.document_id)) is not None}
        summarized,details,audit_details=summarize(docs,outputs,refs,reviews)
        own=[r for r in rows if r["stage"].startswith(name+".")]
        by_stage={stage:dict(Counter(r["status"] for r in own if r["stage"]==name+"."+stage)) for stage in ("identify","extract")}
        latencies=[r["latency"] for r in own if r["latency"] is not None]
        runs=[x for p in (root/phase/"runs").glob("*.json") if (x:=read(p))["approach"]==name and x["new_dispatches"]]
        wall=sum(x["wall_seconds"] for x in runs)
        summarized["execution"]={"calls":len(own),"stage_statuses":by_stage,"latency_mean_seconds":mean(latencies) if latencies else None,
            "latency_median_seconds":median(latencies) if latencies else None,"wall_seconds":wall,
            "valid_documents_per_minute":60*len(outputs)/wall if wall else None,
            "failed_or_missing_outputs":len(docs)-len(outputs),"reserved":sum(r["status"]=="reserved" for r in own)}
        summarized["coverage"]={key:dict(Counter(f[key] for v in outputs.values() for f in v["facts"])) for key in ("category","polarity","temporality","experiencer")}
        summarized["citation"]={"valid":sum(len(v["facts"]) for v in outputs.values()),"normalized_offsets_mechanically_verified":True,
            "raw_structural_failures":sum(r["status"]=="invalid" for r in own)}
        if phase=="final":
            summarized["subsets"]={label:summarize(sub,outputs,refs,reviews)[0] for label,sub in
                (("selection_100",[d for d in docs if d.document_id in selection]),("remaining_200",[d for d in docs if d.document_id not in selection]))}
        metrics_out["systems"][name]=summarized
        jsonl(root/phase/(name+"-predictions.jsonl"),[{"document_id":d.document_id,"note_sha256":d.note_sha256,
            "status":"valid" if d.document_id in outputs else "failed_or_missing","result":outputs.get(d.document_id)} for d in docs])
        jsonl(root/phase/(name+"-silver-comparisons.jsonl"),details)
        jsonl(root/phase/(name+"-audited-comparisons.jsonl"),audit_details)
    for label,first in (("historical_single_pass_first",True),("historical_single_pass_effective",False)):
        values=baseline(repo,docs,first=first)
        metrics_out["systems"][label]=summarize(docs,values,refs,reviews)[0]
        if phase=="final": metrics_out["systems"][label]["subsets"]={label2:summarize(sub,values,refs,reviews)[0] for label2,sub in
            (("selection_100",[d for d in docs if d.document_id in selection]),("remaining_200",[d for d in docs if d.document_id not in selection]))}
    if any(r['status']=='reserved' for r in rows):
        raise ValueError("Unresolved reservations prevent evaluation freeze")
    if phase=="comparison":
        for stage in ('direct.extract','indexed_two_stage.identify'):
            if {r['document_id'] for r in rows if r['stage']==stage}!={d.document_id for d in docs}:
                raise ValueError("Incomplete comparison execution: "+stage)
    else:
        expected_stage=names[0]+('.identify' if APPROACHES[names[0]]==2 else '.extract')
        if {r['document_id'] for r in rows if r['stage']==expected_stage}!={d.document_id for d in docs}:
            raise ValueError("Incomplete final cohort execution")
    write_json(root/phase/"metrics.json",metrics_out,immutable=True)
    return metrics_out

def select(root):
    m=read(root/"comparison/metrics.json")
    ranking=[]
    for name in APPROACHES:
        s=m["systems"][name]
        if s["execution"]["reserved"]: raise ValueError("Unresolved reservations prevent selection")
        # Fixed lexicographic rule: source-grounded factual correctness before silver or cost.
        key=(s["audited"]["f1"] or 0,s["audited"]["complete_case_rate"] or 0,
             s["silver"]["all"]["overlap"]["f1"] or 0,s["silver"]["all"]["structural_success_rate"],
             -s["execution"]["calls"],name=="direct")
        ranking.append((key,name))
    winner=max(ranking)[1]
    freeze={"winner":winner,"ranking":[{"approach":name,"key":list(key)} for key,name in sorted(ranking,reverse=True)],
        "selection_rule":m["criteria"],"comparison_metrics_sha256":sha((root/"comparison/metrics.json").read_bytes()),
        "manifest_sha256":sha((root/"manifest.json").read_bytes()),"final_dispatch_cap":300*APPROACHES[winner],
        "note":"New independent final requests for all 300; no pilot output cache; no tuning after selection"}
    write_json(root/"winner-freeze.json",freeze,immutable=True)
    print(json.dumps(freeze,ensure_ascii=False))
    return winner
