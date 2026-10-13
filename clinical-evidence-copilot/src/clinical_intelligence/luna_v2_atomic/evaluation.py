"""Evaluator-only labels, original quotes and source-confirmed controls; no model calls."""
import json
from collections import Counter
from pathlib import Path
from ..clinical_notes.dataset import sha, write_json
from ..clinical_notes.schema import validate_extraction
from ..clinical_notes.evaluation import match_mentions
from ..luna_rescore.evaluation import project, apply_overlay, concept_group
from ..luna_round2.evaluation import baseline, summarize
from ..luna_v2_independent.runtime import selected, read, lines
from ..luna_v2_independent.evaluation import source_diagnostics, atomic_controls
from ..simsum_comparison.evaluation import references, load_jsonl


def outputs(repo,root,docs):
    prior=repo/"artifacts/luna-v2-repeat-v2/repeat_effective/predictions.jsonl"
    repeat={r["document_id"]:r["result"] for r in load_jsonl(prior) if r["result"] is not None}
    values={"V2_historical":baseline(repo,docs),"V2_repeat":repeat,"B2_first":{},"B2_effective":{}}
    for d in docs:
        for attempt in range(1,4):
            p=root/"requests"/d.document_id.replace(":","_")/f"attempt-{attempt}"/"result.json"
            if p.exists():
                v=validate_extraction(json.dumps(read(p)),d).model_dump()
                if attempt==1: values["B2_first"][d.document_id]=v
                values["B2_effective"][d.document_id]=v
                break
    return values


def confirmed_omissions(repo,values):
    records=load_jsonl(repo/"artifacts/luna-v2-omission-attribution-v1/confirmed-atomic-omissions.jsonl")
    out=[]
    for r in records:
        m=r["mention"]
        group="fever" if m["quote"]=="fever" else "cough"
        matches={}
        for system,own in values.items():
            matches[system]=[{"fact_index":i,"fact":f} for i,f in enumerate(own.get(r["document_id"],{"facts":[]})["facts"])
                if concept_group(f["concept"])==group and max(m["start"],f["evidence"]["start"])<min(m["end"],f["evidence"]["end"])]
        out.append({"document_id":r["document_id"],"note_sha256":r["note_sha256"],"mention":m,
            "context":r["context"],"source_confirmed_historical_omission":True,"systems":matches,
            "scope":"Existence at source location; polarity/temporality/experiencer require separate source review"})
    return out


def sample_probes(root,values):
    out=[]
    for record in load_jsonl(root/"source-only-audit-references.jsonl"):
        for system,own in values.items():
            facts=own.get(record["document_id"],{"facts":[]})["facts"]
            candidates=[{"concept":g+":"+f["polarity"]+":"+f["experiencer"],**f["evidence"]}
                for f in facts if (g:=concept_group(f["concept"])) is not None]
            refs=[{**r,"symptom":r["symptom"]+":"+r["polarity"]+":"+r["experiencer"]} for r in record["references"]]
            pairs=match_mentions(candidates,refs)
            out.append({"document_id":record["document_id"],"system":system,"expected":len(refs),
                "matched":len(pairs),"missing_references":[r for j,r in enumerate(record["references"]) if j not in {j for i,j in pairs}],
                "available":record["document_id"] in own,"scope":"Partial explicit source probes; extra facts reviewed separately"})
    return out


def evaluate(repo,root):
    docs=selected(repo)
    values=outputs(repo,root,docs)
    original,invalid=references(repo,docs)
    overlay=load_jsonl(repo/"artifacts/luna-offline-rescore-v1/reference_adjudication_overlay.jsonl")
    corrected,applied=apply_overlay(docs,original,[r for r in overlay if r["document_id"] in {d.document_id for d in docs}])
    reviews={r["document_id"]:r for r in load_jsonl(repo/"artifacts/luna-round2-v1/source-review-final.jsonl")}
    metrics,details={},{}
    for system,own in values.items():
        projected,_=project(own)
        silver,_,_=summarize(docs,projected,original,reviews)
        scored,detail,assertions=summarize(docs,projected,corrected,reviews)
        fields,nonliteral=source_diagnostics(own)
        metrics[system]={"original_silver":silver["silver"],"corrected":scored["silver"],"fixed_source_audit":scored["audited"],
            "source_fields":fields,"atomic_controls":atomic_controls(docs,own)}
        details[system]={r["document_id"]:r for r in detail}
        lines(root/system/"predictions.jsonl",[{"document_id":d.document_id,"note_sha256":d.note_sha256,"result":own.get(d.document_id)} for d in docs])
        lines(root/system/"mention-comparisons.jsonl",detail)
        lines(root/system/"assertion-audit.jsonl",assertions)
        lines(root/system/"nonliteral-original-terms.jsonl",nonliteral)
    previous=read(repo/"artifacts/luna-v2-independent-v1/V2/independent-metrics.json")
    repeat=read(repo/"artifacts/luna-v2-repeat-v2/metrics.json")["systems"]["repeat_effective"]
    for key in ["original_silver","corrected","fixed_source_audit"]:
        if metrics["V2_historical"][key]!=previous[key] or metrics["V2_repeat"][key]!=repeat[key]:
            raise ValueError("Baseline scoring failed exact reproduction")
    paired=[]
    for d in docs:
        counts={n:{"tp":len(v[d.document_id]["overlap_pairs"]),"fp":len(v[d.document_id]["unmatched_indices"]),
            "fn":len(v[d.document_id]["missing_indices"])} for n,v in details.items()}
        comparisons={}
        for control in ["V2_historical","V2_repeat"]:
            before,after=counts[control],counts["B2_effective"]
            delta=after["fp"]+after["fn"]-before["fp"]-before["fn"]
            comparisons[control]="improved" if delta<0 else "regressed" if delta>0 else "tied"
        paired.append({"document_id":d.document_id,"note_sha256":d.note_sha256,"systems":counts,"benchmark_changes":comparisons})
    omissions=confirmed_omissions(repo,values)
    probes=sample_probes(root,values)
    requests=load_jsonl(root/"dispatch-outcomes.jsonl")
    tokens=Counter()
    known=0
    for row in requests:
        if row["usage"]:
            known+=1
            tokens.update({k:v for k,v in row["usage"].items() if type(v) is int})
    metrics_out={"systems":metrics,"execution":read(root/"execution-summary.json"),"tokens":dict(tokens),
        "usage_known_calls":known,"cost_usd":None,"summed_request_seconds":sum(r["latency_seconds"] for r in requests),
        "confirmed_omission_probe_matches":{n:sum(bool(r["systems"][n]) for r in omissions) for n in values},
        "source_sample_probes":{n:{"matched":sum(r["matched"] for r in probes if r["system"]==n),
            "expected":sum(r["expected"] for r in probes if r["system"]==n)} for n in values},
        "benchmark_document_changes":{n:dict(Counter(r["benchmark_changes"][n] for r in paired)) for n in ["V2_historical","V2_repeat"]},
        "overlay_edits_applied":len(applied),"invalid_reference_offsets":invalid,
        "no_new_gold_edits":True,"full_document_clinical_correctness_not_established":True}
    lines(root/"paired-document-comparison.jsonl",paired)
    lines(root/"confirmed-omission-comparison.jsonl",omissions)
    lines(root/"source-only-audit-probe-results.jsonl",probes)
    queue=sorted([r for r in paired if r["benchmark_changes"]["V2_repeat"]!="tied"],key=lambda r:
        (r["benchmark_changes"]["V2_repeat"]!="regressed",sha("luna-v2-atomic-v1-discrepancy:"+r["document_id"])))[:20]
    lines(root/"flagged-source-review-selection.jsonl",queue)
    write_json(root/"metrics.json",metrics_out,immutable=True)
    return metrics_out
