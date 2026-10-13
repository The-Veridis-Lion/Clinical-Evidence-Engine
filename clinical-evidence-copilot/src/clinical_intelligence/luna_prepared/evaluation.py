"""Same corrected scoring contract; incomplete retained facts never become complete cases."""
from collections import Counter
from .runtime import read, rows, folder, integrity
from .contract import PROMOTION, validate_result, primary_projection
from ..clinical_notes.dataset import sha, write_json
from ..luna_source.evaluation import execution
from ..luna_grounding.evaluation import semantic_differences
from ..luna_round2.evaluation import baseline, summarize
from ..luna_rescore.evaluation import project, apply_overlay
from ..simsum_comparison.__main__ import documents
from ..simsum_comparison.evaluation import references, load_jsonl, jsonl


def evaluate(repo,root,phase):
    m=integrity(repo,root)
    docs=documents(repo)
    if phase=="pilot": docs=[d for d in docs if d.document_id in m["comparison_ids"]]
    elif phase!="final": raise ValueError("unknown phase")
    requests=[r for r in rows(root) if r["stage"].startswith(phase+".")]
    if {r["document_id"] for r in requests if r["stage"]==phase+".initial"}!={d.document_id for d in docs} or any(r["status"]=="reserved" for r in requests):
        raise ValueError("All selected records require terminal first attempts")
    outputs={"historical_single_pass_effective":baseline(repo,docs),"historical_single_pass_first":baseline(repo,docs,first=True),
        "first_pass":{},"post_repair":{}}
    statuses={name:{} for name in ("first_pass","post_repair")}
    for doc in docs:
        directory=folder(root,phase,doc.document_id)
        for name,file in (("first_pass",directory/"initial/validation.json"),("post_repair",directory/"final-outcome.json")):
            outcome=read(file);statuses[name][doc.document_id]=outcome["status"]
            if outcome["result"] is not None: outputs[name][doc.document_id]=primary_projection(validate_result(outcome["result"],doc))
        for row in [r for r in requests if r["document_id"]==doc.document_id]:
            raw=directory/row["stage"].split(".")[1]/"raw-response.json"
            if raw.exists() and sha(raw.read_bytes())!=row["raw_hash"]: raise ValueError("Raw response mutated")
    if phase=="pilot":
        outputs["offline_previous_high"]={r["document_id"]:primary_projection(r["result"]) for r in
            load_jsonl(root/"offline/converted-predictions.jsonl") if r["configuration"]=="A" and r["status"]=="VALID"}
    refs,bad=references(repo,docs)
    overlay=load_jsonl(repo/"artifacts/luna-offline-rescore-v1/reference_adjudication_overlay.jsonl")
    corrected,applied=apply_overlay(docs,refs,[r for r in overlay if r["document_id"] in refs])
    reviews={r["document_id"]:r for r in load_jsonl(repo/"artifacts/luna-round2-v1/source-review-final.jsonl")}
    systems={};details={};audits={}
    for name,values in outputs.items():
        projected,changes=project(values)
        original,_,_=summarize(docs,projected,refs,reviews)
        scores,detail,audit=summarize(docs,projected,corrected,reviews)
        if name in statuses:
            for stratum,variant in (("all",None),("standard","text"),("advanced","advanced_text")):
                subset=[d for d in docs if variant is None or d.variant==variant]
                valid={d.document_id for d in subset if statuses[name][d.document_id]=="VALID"}
                for metric in (original,scores):
                    group=metric["silver"][stratum]
                    group["valid_documents"]=len(valid);group["structural_success_rate"]=len(valid)/len(subset)
                scores["silver"][stratum]["complete_mention_cases"]=sum(r["document_id"] in valid and not r["missing_indices"] and not r["unmatched_indices"] for r in detail if r["document_id"] in {d.document_id for d in subset})
                scores["silver"][stratum]["complete_mention_case_rate"]=scores["silver"][stratum]["complete_mention_cases"]/len(subset)
            scores["audited"]["complete_cases"]=sum(r["complete"] and statuses[name][r["document_id"]]=="VALID" for r in audit)
            scores["audited"]["complete_case_rate"]=scores["audited"]["complete_cases"]/scores["audited"]["documents"]
        systems[name]={"corrected":scores["silver"],"original_silver":original["silver"],"fixed_source_audit":scores["audited"]}
        if name in statuses: systems[name]["statuses"]=dict(Counter(statuses[name].values()))
        if phase=="final":
            systems[name]["subsets"]={label:summarize(sub,projected,corrected,reviews)[0] for label,sub in
                (("initial100",[d for d in docs if d.document_id in m["comparison_ids"]]),("remaining200",[d for d in docs if d.document_id not in m["comparison_ids"]]))}
        details[name]=detail;audits[name]=audit
        jsonl(root/phase/(name+"-mention-comparisons.jsonl"),detail)
        jsonl(root/phase/(name+"-assertion-audit.jsonl"),audit)
        jsonl(root/phase/(name+"-normalization-projection.jsonl"),changes)
        jsonl(root/phase/(name+"-predictions.jsonl"),[{"document_id":d.document_id,"note_sha256":d.note_sha256,
            "status":statuses.get(name,{}).get(d.document_id,"VALID" if d.document_id in values else "INVALID"),"result":values.get(d.document_id)} for d in docs])
    if phase=="pilot":
        old=read(repo/"artifacts/luna-source-constrained-v1/comparison/metrics.json")["systems"]
        for name in ("historical_single_pass_effective","historical_single_pass_first"):
            if systems[name]["corrected"]!=old[name]["corrected"] or systems[name]["fixed_source_audit"]!=old[name]["fixed_source_audit"]:
                raise ValueError("Historical corrected baseline differs")
        systems["previous_source_high"]=old["A"]
    by_doc={n:{r["document_id"]:r for r in ds} for n,ds in details.items()}
    controls={"simsum:5359:text","simsum:192:advanced_text","simsum:4240:text","simsum:1764:advanced_text","simsum:9268:text","simsum:1569:text"}
    flagged=[]
    for doc in docs:
        candidate=outputs["post_repair"].get(doc.document_id);previous=outputs["historical_single_pass_effective"].get(doc.document_id)
        comparison=by_doc["post_repair"][doc.document_id]
        difference=semantic_differences(candidate,previous) if candidate and previous else []
        reasons=[]
        if statuses["post_repair"][doc.document_id]!="VALID": reasons.append("incomplete output")
        if comparison["missing_indices"] or comparison["unmatched_indices"]: reasons.append("reference disagreement")
        if difference: reasons.append("baseline semantic disagreement")
        if doc.document_id in controls: reasons.append("previous confirmed failure mechanism")
        if reasons: flagged.append({"document_id":doc.document_id,"note_sha256":doc.note_sha256,"source_text":doc.text,
            "reasons":reasons,"semantic_differences":difference,"comparison":comparison,
            "candidate":candidate,"baseline":previous,"status":"UNRESOLVED_UNTIL_SOURCE_REVIEW",
            "model_error_category":None,"omission_categories":[1,2],"independent_identify_trace":False,
            "priority":[int(statuses["post_repair"][doc.document_id]!="VALID"),int(doc.document_id in controls),int(bool(difference)),
                len(comparison["missing_indices"])+len(comparison["unmatched_indices"])]})
    flagged.sort(key=lambda r:(tuple(-x for x in r["priority"]),r["document_id"]))
    jsonl(root/phase/"flagged-cases.jsonl",flagged)
    jsonl(root/phase/"review-queue.jsonl",flagged[:PROMOTION["review_cap"]])
    initial=[r for r in requests if r["stage"].endswith(".initial")];retry=[r for r in requests if r["stage"].endswith(".retry")]
    recovered=sum(statuses["first_pass"][d.document_id]!="VALID" and statuses["post_repair"][d.document_id]=="VALID" for d in docs)
    offline_recovered=sum(read(folder(root,phase,d.document_id)/"deterministic-recovery.json")["outcome"]["status"]=="VALID" and statuses["first_pass"][d.document_id]!="VALID" for d in docs)
    usage={"total":execution(requests),"initial":execution(initial),"retry":execution(retry),
        "recovered_records":recovered,"recovered_deterministically":offline_recovered,"recovered_after_model_retry":recovered-offline_recovered,
        "wall_seconds":sum(read(p)["wall_seconds"] for p in (root/phase/"runs").glob("*.json")),
        "final_record_latency_seconds":{d.document_id:sum(r["latency"] for r in requests if r["document_id"]==d.document_id) for d in docs},
        "unknown_completion_requests":sum(read(folder(root,phase,r["document_id"])/r["stage"].split(".")[1]/"validation.json").get("transport",{}).get("state")=="UNCERTAIN_NO_REDISPATCH" for r in requests)}
    result={"version":m["version"],"phase":phase,"systems":systems,"execution":usage,
        "source_integrity":{"accepted_facts":sum(len(v["facts"]) for v in outputs["post_repair"].values()),
            "exact_source_anchors":True,"free_generated_terms":False,"semantic_support":"separate source review required"},
        "reference_overlay_applied":len(applied),"invalid_original_reference_offsets":bad,"flagged_documents":len(flagged),
        "review_selected":min(PROMOTION["review_cap"],len(flagged)),"unflagged_successes_manually_reviewed":0,"scope":PROMOTION["scope"]}
    write_json(root/phase/"metrics.json",result,immutable=True)
    return result


def decide(root,phase):
    metrics=read(root/phase/"metrics.json");candidate=metrics["systems"]["post_repair"];baseline_system=metrics["systems"]["historical_single_pass_effective"]
    c=candidate["corrected"]["all"];b=baseline_system["corrected"]["all"]
    ca=candidate["fixed_source_audit"];ba=baseline_system["fixed_source_audit"]
    review=load_jsonl(root/phase/"source-review-decisions.jsonl");queue=load_jsonl(root/phase/"review-queue.jsonl")
    if {r["document_id"] for r in review}!={r["document_id"] for r in queue}: raise ValueError("Complete the frozen flagged review")
    checks={"meaningful_f1_gain":c["overlap"]["f1"]-b["overlap"]["f1"]>=PROMOTION["minimum_f1_gain"],
        "more_complete_cases":c["complete_mention_cases"]>=b["complete_mention_cases"]+PROMOTION["minimum_complete_case_gain"],
        "structural_completeness":c["structural_success_rate"]==1.,
        "fixed_audit_noninferiority":ca["f1"]>=ba["f1"] and ca["complete_cases"]>=ba["complete_cases"],
        "no_important_clinical_regression":not any(f.get("important_regression",False) for r in review for f in r["findings"])}
    if phase=="final":
        for name in ("initial100","remaining200"):
            x=candidate["subsets"][name]["silver"]["all"];y=baseline_system["subsets"][name]["silver"]["all"]
            checks[name+"_no_accuracy_regression"]=x["overlap"]["f1"]>=y["overlap"]["f1"] and x["complete_mention_cases"]>=y["complete_mention_cases"]
    result={"promote":all(checks.values()),"checks":checks,"manifest_sha256":sha((root/"manifest.json").read_bytes()),
        "metrics_sha256":sha((root/phase/"metrics.json").read_bytes()),"review_sha256":sha((root/phase/"source-review-decisions.jsonl").read_bytes()),
        "recommended_baseline":"luna-prepared-high-v1" if phase=="final" and all(checks.values()) else "historical Single-pass v2",
        "unreviewed_flags_remain_unresolved":metrics["flagged_documents"]>len(review),"rule":PROMOTION}
    write_json(root/(phase+"-decision.json"),result,immutable=True)
    return result
