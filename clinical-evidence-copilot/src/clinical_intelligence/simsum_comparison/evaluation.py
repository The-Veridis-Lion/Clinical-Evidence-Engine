"""One-to-one span evaluation and source audit inventory, never a semantic scoring model."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from .contract import DEFINITIONS, CONFIG, canonical_candidates, union_candidates, verified_candidates, stable_hash
from .execution import effective, read, request_folder
from .ledger import Ledger
from ..clinical_notes.dataset import write_json, sha
from ..clinical_notes.evaluation import match_mentions, metrics, verified_annotations
from ..clinical_notes.normalization import concept_group

def jsonl(path, values, *, immutable=True):
    content = "".join(json.dumps(v,ensure_ascii=False,sort_keys=True)+"\n" for v in values)
    path.parent.mkdir(parents=True,exist_ok=True)
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"Immutable artifact differs: {path}")
        return
    with path.open("x" if immutable else "w",encoding="utf-8",newline="\n") as f:
        f.write(content)

def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

def gliner_record(root, doc):
    p = root / "gliner" / doc.document_id.replace(":", "_") / "prediction.json"
    return read(p) if p.exists() else None

def ledger_rows(root):
    path = root / "luna-requests.sqlite3"
    return Ledger(path,read(root / "experiment_manifest.json")["execution_contract"]).rows() if path.exists() else []

def identify_record(root,doc):
    result = effective(root,"identify",doc.document_id)
    rows = [r for r in ledger_rows(root) if r["stage"] == "identify" and r["document_id"] == doc.document_id]
    responses = []
    for row in rows:
        raw_path = request_folder(root,"identify",doc.document_id,row["attempt"]) / "raw-response.json"
        responses.append({"attempt":row["attempt"],"status":row["status"],
            "raw_response":raw_path.read_text(encoding="utf-8") if raw_path.exists() else None,
            "raw_sha256":row["raw_hash"],"raw_path":str(raw_path.relative_to(root))})
    return {"document_id":doc.document_id,"note_sha256":doc.note_sha256,
        "status":"valid" if result else rows[-1]["status"] if rows else "not_attempted",
        "candidates":result["candidates"] if result else [],"attempts":rows,"raw_responses":responses}

def freeze(repo,root,docs):
    a,b = [],[]
    for doc in docs:
        a.append(identify_record(root,doc))
        record = gliner_record(root,doc)
        if record is None:
            raise ValueError("Full GLiNER cohort must finish before independent freeze")
        b.append({**record,"raw_chunks":read(root / "gliner" / doc.document_id.replace(":", "_") / "raw.json")["chunks"]})
    if any(x["status"] in {"not_attempted","reserved"} for x in a):
        raise ValueError("Luna Identify cohort is not complete")
    jsonl(root / "luna_identify_raw.jsonl",a)
    jsonl(root / "gliner_identify_raw.jsonl",b)
    write_json(root / "independent-predictions-freeze.json",{
        "luna_identify_raw_sha256":sha((root / "luna_identify_raw.jsonl").read_bytes()),
        "gliner_identify_raw_sha256":sha((root / "gliner_identify_raw.jsonl").read_bytes()),
        "documents":len(docs)},immutable=True)

def aligned(a,b):
    p = [{"concept":x["concept"],"start":x["evidence"]["start"],"end":x["evidence"]["end"]} for x in a]
    r = [{"symptom":x["concept"],"start":x["evidence"]["start"],"end":x["evidence"]["end"]} for x in b]
    pairs = match_mentions(p,r)
    ia,ib = {i for i,j in pairs},{j for i,j in pairs}
    return {"compatible":pairs,"luna_only":[i for i in range(len(a)) if i not in ia],
        "gliner_only":[j for j in range(len(b)) if j not in ib],
        "overlap_concept_disagreements":[(i,j) for i,x in enumerate(a) for j,y in enumerate(b)
            if x["concept"] != y["concept"] and max(x["evidence"]["start"],y["evidence"]["start"]) < min(x["evidence"]["end"],y["evidence"]["end"])]}

def derive(repo,root,docs):
    if not (root / "independent-predictions-freeze.json").exists():
        raise ValueError("Independent predictions are not frozen")
    cross, verified = [], {"luna":[],"gliner":[]}
    for doc in docs:
        a,b = identify_record(root,doc),gliner_record(root,doc)
        v = effective(root,"verify",doc.document_id)
        union = union_candidates(a["candidates"],b["candidates"])
        record = {"document_id":doc.document_id,"note_sha256":doc.note_sha256,
            "alignment":aligned(a["candidates"],b["candidates"]),"union":union,
            "verification":v,"verification_status":"provisional_model_verification" if v else "unavailable",
            "ground_truth":False,"gliner_independent_check":"full-note raw predictions; non-recognition is not rejection",
            "source_offsets_verified":True,"luna_raw_status":a["status"],"luna_raw_available":a["status"] == "valid"}
        for system,original in (("luna",a),("gliner",b)):
            candidates,changes = verified_candidates(original["candidates"],union,v) if v else (original["candidates"],[])
            item = {"document_id":doc.document_id,"note_sha256":doc.note_sha256,
                "status":"provisionally_verified" if v else "unverified_unchanged",
                "candidates":candidates,"changes":changes,
                "raw_candidates_hash":stable_hash(canonical_candidates(original["candidates"])),
                "verified_candidates_hash":stable_hash(candidates)}
            item["raw_status"] = original["status"]
            item["raw_available"] = original["status"] == "valid"
            item["recovered_from_cross_evidence"] = system == "luna" and original["status"] != "valid" and v is not None
            for change in changes:
                key = lambda c: (c["concept"],c["evidence"]["start"],c["evidence"]["end"])
                change["origin_systems"] = [name for name,raw in (("luna",a),("gliner",b))
                    if key(change["candidate"]) in {key(x) for x in raw["candidates"]}]
            write_json(root / "verified" / system / (doc.document_id.replace(":", "_")+".json"),item,immutable=True)
            verified[system].append(item)
            record[system+"_changes"] = changes
        cross.append(record)
    jsonl(root / "cross_verification.jsonl",cross)
    for system in verified:
        jsonl(root / f"{system}_identify_verified.jsonl",verified[system])

def references(repo,docs):
    folder = repo / "artifacts/clinical-notes-v1/source"
    annotations = {"text":read(folder / "normal_span_annotations.json"),"advanced_text":read(folder / "adv_span_annotations.json")}
    result,invalid = {},[]
    for d in docs:
        good,bad = verified_annotations(d,annotations[d.variant])
        result[d.document_id] = good
        invalid.extend({"document_id":d.document_id,**a} for a in bad)
    return result,invalid

def flat(candidates):
    return [{"concept":c["concept"],"start":c["evidence"]["start"],"end":c["evidence"]["end"],
             "candidate_index":i} for i,c in enumerate(canonical_candidates(candidates))]

def facts_candidates(result):
    if result is None:
        return []
    return canonical_candidates([{"concept":concept_group(f["concept"]),"evidence":f["evidence"]}
        for f in result["facts"] if concept_group(f["concept"]) in DEFINITIONS])

def exact_match(predictions, refs):
    # Same maximum matching engine, exact equality encoded in the edge list by filtering.
    # Separate implementation is deliberately only matching geometry, never clinical interpretation.
    adjacent = [[j for j,r in enumerate(refs) if p["concept"] == r["symptom"] and
                 p["start"] == r["start"] and p["end"] == r["end"]] for p in predictions]
    owner = {}
    def augment(i,seen):
        for j in adjacent[i]:
            if j in seen:
                continue
            seen.add(j)
            if j not in owner or augment(owner[j],seen):
                owner[j] = i
                return True
        return False
    for i in range(len(predictions)):
        augment(i,set())
    return sorted((i,j) for j,i in owner.items())

def score(docs,predicted,refs,eligible=None):
    eligible = set(predicted) if eligible is None else set(eligible)
    totals = defaultdict(lambda:[0,0,0])
    details = []
    for doc in docs:
        if doc.document_id not in eligible:
            continue
        p,r = flat(predicted.get(doc.document_id,[])),refs[doc.document_id]
        pairs,exact = match_mentions(p,r),exact_match(p,r)
        c_pairs = len({x["concept"] for x in p} & {x["symptom"] for x in r})
        item = {"document_id":doc.document_id,"variant":doc.variant,"predictions":p,"references":r,
            "overlap_pairs":pairs,"exact_pairs":exact,"missing_indices":[j for j in range(len(r)) if j not in {j for i,j in pairs}],
            "unmatched_indices":[i for i in range(len(p)) if i not in {i for i,j in pairs}],
            "concept_complete":{x["concept"] for x in p} == {x["symptom"] for x in r}}
        details.append(item)
        strata = ("all", "standard" if doc.variant == "text" else "advanced")
        for stratum in strata:
            for kind,tp,pp,rr in (("overlap",len(pairs),len(p),len(r)),("exact",len(exact),len(p),len(r)),
                    ("document_concept",c_pairs,len({x["concept"] for x in p}),len({x["symptom"] for x in r}))):
                totals[(stratum,kind)] = [a+b for a,b in zip(totals[(stratum,kind)],[tp,pp,rr])]
            for concept in DEFINITIONS:
                count = sum(p[i]["concept"] == concept for i,j in pairs)
                totals[(stratum,concept)] = [a+b for a,b in zip(totals[(stratum,concept)],
                    [count,sum(x["concept"] == concept for x in p),sum(x["symptom"] == concept for x in r)])]
    groups = {stratum:{kind:metrics(*totals[(stratum,kind)]) for kind in ("overlap","exact","document_concept",*DEFINITIONS)}
              for stratum in ("all","standard","advanced")}
    groups["all"]["evaluated_documents"] = len(details)
    groups["all"]["concept_complete_documents"] = sum(x["concept_complete"] for x in details)
    return groups,details

def predictions(root,docs):
    sets = {name:{} for name in ("luna_raw","gliner_raw","luna_verified","gliner_verified",
        "extract_luna_raw","extract_gliner_raw","extract_luna_verified","extract_gliner_verified","single_pass_v2")}
    available = {name:set() for name in sets}
    protocol_excluded = {(r["stage"],r["document_id"]) for r in
        read(root / "protocol-deviations.json")["excluded_extract_outputs"]} if (root / "protocol-deviations.json").exists() else set()
    for d in docs:
        for system,record in (("luna",identify_record(root,d)),("gliner",gliner_record(root,d))):
            if record and record["status"] == "valid":
                sets[system+"_raw"][d.document_id] = record["candidates"]
                available[system+"_raw"].add(d.document_id)
            path = root / "verified" / system / (d.document_id.replace(":", "_")+".json")
            if path.exists():
                v = read(path)
                if v["status"] == "provisionally_verified":
                    sets[system+"_verified"][d.document_id] = v["candidates"]
                    available[system+"_verified"].add(d.document_id)
        for stage in ("extract_luna_raw","extract_gliner_raw","extract_luna_verified","extract_gliner_verified"):
            if (stage,d.document_id) in protocol_excluded:
                continue
            if stage.endswith("verified") and d.document_id not in available[("luna" if "luna" in stage else "gliner")+"_verified"]:
                continue
            result = effective(root,stage,d.document_id)
            if result:
                sets[stage][d.document_id] = facts_candidates(result)
                available[stage].add(d.document_id)
        historical_root = root.parent / "clinical-notes-v2"
        for attempt in (2,1):
            p = historical_root / "requests" / d.document_id.replace(":", "_") / f"attempt-{attempt}" / "facts.json"
            if p.exists():
                sets["single_pass_v2"][d.document_id] = facts_candidates(read(p))
                available["single_pass_v2"].add(d.document_id)
                break
    return sets,available

def audit_queue(repo,root,docs):
    refs,invalid = references(repo,docs)
    sets,available = predictions(root,docs)
    queue,agreements = [],[]
    for doc in docs:
        a,b = sets["luna_raw"].get(doc.document_id,[]),sets["gliner_raw"].get(doc.document_id,[])
        alignment = aligned(a,b)
        comparisons = {}
        for system,candidates in (("luna",a),("gliner",b)):
            p = flat(candidates)
            pairs = match_mentions(p,refs[doc.document_id])
            comparisons[system] = {"missing_reference_indices":[j for j in range(len(refs[doc.document_id])) if j not in {j for i,j in pairs}],
                                   "unmatched_prediction_indices":[i for i in range(len(p)) if i not in {i for i,j in pairs}]}
        reasons = []
        if alignment["luna_only"] or alignment["gliner_only"] or alignment["overlap_concept_disagreements"]:
            reasons.append("intermodel_disagreement")
        if any(any(v.values()) for v in comparisons.values()):
            reasons.append("model_reference_disagreement")
        common = set(comparisons["luna"]["missing_reference_indices"]) & set(comparisons["gliner"]["missing_reference_indices"])
        if common:
            reasons.append("common_apparent_omission")
        item = {"document_id":doc.document_id,"variant":doc.variant,"note_sha256":doc.note_sha256,"note":doc.text,
            "original_annotations":refs[doc.document_id],"independent_predictions":{"luna":a,"gliner":b},
            "selection_reasons":reasons,"comparison":comparisons,"common_missing_indices":sorted(common),
            "mechanical_audit":"All reference and candidate quotations/offsets checked against exact source",
            "clinical_adjudication_status":"UNRESOLVED until separate source review; mismatches are not proven model errors"}
        (queue if reasons else agreements).append(item)
    for variant in ("text","advanced_text"):
        ranked = sorted([x for x in agreements if x["variant"] == variant],key=lambda x:sha(f"{CONFIG['seed']}:agreement-audit:{x['document_id']}"))
        for x in ranked[:5]:
            x["selection_reasons"] = ["stratified_random_agreement_sample"]
            queue.append(x)
    jsonl(root / "reference-audit-queue.jsonl",queue,immutable=False)
    write_json(root / "audit-queue-summary.json",{"documents":len(queue),"total_documents":len(docs),
        "invalid_reference_offsets":invalid,"selection_reason_counts":dict(Counter(r for x in queue for r in x["selection_reasons"])),
        "agreement_pool":len(agreements),"seed":CONFIG["seed"]})

def evaluate(repo,root,docs):
    refs,invalid = references(repo,docs)
    sets,available = predictions(root,docs)
    scores,details = {},{}
    all_ids = {d.document_id for d in docs}
    for system,p in sets.items():
        scores[system],details[system] = score(docs,p,refs,available[system])
        scores[system]["all_selected_coverage"],_ = score(docs,p,refs,all_ids)
    paired = available["luna_raw"] & available["gliner_raw"] & available["luna_verified"] & available["gliner_verified"]
    paired_scores = {s:score(docs,sets[s],refs,paired)[0] for s in ("luna_raw","gliner_raw","luna_verified","gliner_verified")}
    end_paired = set.intersection(*(available[s] for s in ("extract_luna_raw","extract_gliner_raw","extract_luna_verified","extract_gliner_verified")))
    paired_extract = {s:score(docs,sets[s],refs,end_paired)[0] for s in ("extract_luna_raw","extract_gliner_raw","extract_luna_verified","extract_gliner_verified")}
    common = Counter()
    disagreement_matrix = Counter()
    byid = {s:{x["document_id"]:x for x in rows} for s,rows in details.items()}
    for d in docs:
        a,b = byid["luna_raw"].get(d.document_id),byid["gliner_raw"].get(d.document_id)
        if a is None or b is None:
            common["infrastructure_or_structural_unavailable"] += 1
            continue
        common[("both_silver_concept_complete" if a["concept_complete"] and b["concept_complete"] else
            "luna_only_silver_concept_complete" if a["concept_complete"] else
            "gliner_only_silver_concept_complete" if b["concept_complete"] else "both_silver_concept_incomplete")] += 1
        for c in DEFINITIONS:
            aa,bb = any(x["concept"] == c for x in a["predictions"]),any(x["concept"] == c for x in b["predictions"])
            rr = any(x["symptom"] == c for x in refs[d.document_id])
            disagreement_matrix[f"Luna={int(aa)},GLiNER={int(bb)},silver={int(rr)}"] += 1
    requests = ledger_rows(root)
    usage = Counter()
    for r in requests:
        value = json.loads(r["usage"]) if r["usage"] else None
        if value:
            usage.update({k:v for k,v in value.items() if isinstance(v,(int,float))})
    stages = {}
    for stage in ("identify","extract_luna_raw","extract_gliner_raw","verify","extract_luna_verified","extract_gliner_verified"):
        rows = [r for r in requests if r["stage"] == stage]
        latencies = [r["latency"] for r in rows if r["latency"] is not None]
        final_rows = {r["document_id"]:r for r in rows}
        stages[stage] = {"dispatches":len(rows),"documents_attempted":len({r['document_id'] for r in rows}),
            "status_counts":dict(Counter(r["status"] for r in rows)),"latency_mean":mean(latencies) if latencies else None,
            "latency_median":median(latencies) if latencies else None,"latency_max":max(latencies) if latencies else None,
            "final_document_status_counts":dict(Counter(r["status"] for r in final_rows.values())),
            "cache_reuse":len(list((root / "cache-aliases" / stage).glob("*.json"))) if (root / "cache-aliases" / stage).exists() else 0}
    changes = {system:Counter() for system in ("luna","gliner")}
    for system in changes:
        for record in load_jsonl(root / f"{system}_identify_verified.jsonl"):
            if record["changes"]:
                changes[system]["documents_changed"] += 1
            changes[system].update(x["action"] for x in record["changes"])
    citations = {}
    for stage in ("extract_luna_raw","extract_gliner_raw","extract_luna_verified","extract_gliner_verified"):
        count = sum(len(effective(root,stage,d.document_id)["facts"]) for d in docs if effective(root,stage,d.document_id))
        citations[stage] = {"validated_facts":count,"successful_response_citation_validity":1.0 if count else None,
            "failed_initial_structural_attempts":sum(r["status"] == "invalid" for r in requests if r["stage"] == stage)}
    run_records = [read(p) for p in (root / "runs").glob("*.json")]
    wall_by_stage = {stage:sum(r["wall_seconds"] for r in run_records if r["stage"] == stage) for stage in stages}
    for stage in stages:
        stages[stage]["wall_seconds_including_pilot"] = wall_by_stage[stage]
        stages[stage]["completed_documents_per_minute"] = len(available.get(stage,set()))*60/wall_by_stage[stage] if wall_by_stage[stage] else None
    interruption = None
    if (root / "interruption-recovery.json").exists():
        from datetime import datetime
        interruption = read(root / "interruption-recovery.json")
        stage = interruption["runner_lock"]["stage"]
        start = datetime.fromisoformat(interruption["runner_lock"]["started_at"])
        finished_times = [datetime.fromisoformat(r["ended_at"]) for r in requests if r["stage"] == stage
                          and r["latency"] is not None and r["ended_at"] and datetime.fromisoformat(r["reserved_at"]) >= start]
        lower = (max(finished_times)-start).total_seconds() if finished_times else 0
        stages[stage]["wall_time_incomplete_due_to_execution_interruption"] = True
        stages[stage]["interrupted_run_wall_lower_bound_seconds"] = lower
        stages[stage]["interrupted_run_wall_upper_bound_seconds"] = (datetime.fromisoformat(interruption["observed_at"])-start).total_seconds()
        stages[stage]["completed_documents_per_minute"] = None
        stages[stage]["wall_seconds_including_pilot"] = None
        stages[stage]["known_completed_run_wall_seconds"] = wall_by_stage[stage]
    gliner_records = [gliner_record(root,d) for d in docs]
    gliner_latency = [r["latency_seconds"] for r in gliner_records if r]
    gliner_usage = {"documents":len(gliner_latency),"inference_seconds_sum":sum(gliner_latency),
        "latency_mean":mean(gliner_latency) if gliner_latency else None,
        "latency_median":median(gliner_latency) if gliner_latency else None,
        "peak_gpu_allocated_bytes":max((r["peak_gpu_allocated_bytes"] or 0 for r in gliner_records if r),default=None),
        "resources":read(root / "gliner-resources.json") if (root / "gliner-resources.json").exists() else None,
        "pilot_resources":read(root / "gliner-pilot-resources.json") if (root / "gliner-pilot-resources.json").exists() else None}
    dispatch_metadata,turns,tools = 0,0,0
    for r in requests:
        folder = request_folder(root,r["stage"],r["document_id"],r["attempt"])
        dispatch_metadata += (folder / "dispatch.json").exists()
        if (folder / "events.jsonl").exists():
            for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                turns += event.get("type") == "turn.started"
                tools += event.get("item",{}).get("type") in {"command_execution","mcp_tool_call","web_search","file_change"}
    result = {"version":"comparison-span-evaluation-v1","cohort":"reused development Batch 2",
        "reference":"original SimSUM silver annotations; no assertion ground truth",
        "matching":"maximum one-to-one concept-equal positive-length overlap; exact separately; exact duplicate measurement keys deduplicated",
        "silver_scores":scores,"paired_identify_scores":paired_scores,"paired_identify_denominator":len(paired),
        "paired_extract_scores":paired_extract,"paired_extract_denominator":len(end_paired),
        "common_mode_silver_proxy":dict(common),"concept_presence_disagreement_matrix":dict(disagreement_matrix),
        "reference_spans":sum(len(x) for x in refs.values()),"invalid_reference_offsets":invalid,
        "luna_dispatches":len(requests),"dispatch_metadata_records":dispatch_metadata,"cli_turns_started":turns,"tool_operations":tools,
        "usage_known_dispatches":sum(json.loads(r["usage"]) is not None for r in requests if r["usage"]),
        "token_usage":dict(usage),"stages":stages,"luna_phase_wall_seconds":sum(wall_by_stage.values()),
        "luna_phase_wall_time_incomplete":interruption is not None,
        "luna_phase_wall_lower_bound_seconds":sum(wall_by_stage.values())+(stages[interruption["runner_lock"]["stage"]]["interrupted_run_wall_lower_bound_seconds"] if interruption else 0),
        "gliner_resource_usage":gliner_usage,"cross_changes":{k:dict(v) for k,v in changes.items()},
        "citations":citations,"cost":None,"cost_reason":"Subscription CLI exposes tokens but no attributable documented per-request price",
        "unlabelled_dimensions":["polarity","temporality","experiencer","non-symptom clinical fact accuracy"],
        "semantic_accuracy":"Only separate manually source-adjudicated subset may support these measures"}
    if (root / "protocol-deviations.json").exists():
        result["protocol_deviations"] = read(root / "protocol-deviations.json")
        result["evaluation_status"] = "Protocol-compliant subset; excluded repeat output is preserved with as-executed metrics"
    if (root / "audited-metrics.json").exists():
        result["audited_subset"] = read(root / "audited-metrics.json")
    write_json(root / "metrics.json",result)
    jsonl(root / "silver-evidence-comparisons.jsonl",[{"system":s,**r} for s,rows in details.items() for r in rows],immutable=False)
    write_json(root / "ledger-snapshot.json",requests)
    return result
