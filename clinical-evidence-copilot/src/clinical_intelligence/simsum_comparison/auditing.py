"""Separate, bounded source-review overlay and trace-based attribution.

No model-verification result adjudicates references. Unreviewed clinical disagreements stay
unresolved. The explicit source-only review is a nonexpert textual subset, not full gold.
"""
from collections import Counter, defaultdict
from .contract import DEFINITIONS, canonical_candidates, stable_hash
from .execution import read, effective
from .evaluation import (jsonl, load_jsonl, references, predictions, score, flat, ledger_rows,
                         facts_candidates)
from ..clinical_notes.dataset import write_json, sha
from ..clinical_notes.normalization import concept_group
from ..clinical_notes.evaluation import match_mentions, metrics

def overlaps(a,b):
    return max(a["start"],b["start"]) < min(a["end"],b["end"])

def excluded(evidence, review):
    # Do not suppress a supported target sharing the quote with a borderline finding.
    return any(overlaps(evidence,e) for e in review["excluded_ambiguous_spans"]) and not any(
        overlaps(evidence,r) for r in review["references"])

def reference_status(matching,ambiguous,decision=None):
    """A disagreement alone cannot substantiate a reference defect."""
    return decision["status"] if decision else "REFERENCE_CORRECT" if matching else "REFERENCE_AMBIGUOUS" if ambiguous else "UNRESOLVED"

def audit(repo,root,docs):
    reviews = {r["document_id"]:r for r in load_jsonl(root / "source-only-adjudicated-mentions.jsonl")}
    original,invalid = references(repo,docs)
    manual = {(r["document_id"],r["annotation_index"]):r for r in load_jsonl(root / "manual-reference-decisions-v1.jsonl")}
    manual_identify = {(r["document_id"],r["system"],r["phase"],stable_hash(r["candidate"])):r
                      for r in load_jsonl(root / "manual-identify-decisions-v1.jsonl")}
    sets,available = predictions(root,docs)
    overlay,attribution = [],[]
    status_counts = Counter()
    reviewed_docs = [d for d in docs if d.document_id in reviews]
    for d in reviewed_docs:
        review = reviews[d.document_id]
        if review["note_sha256"] != d.note_sha256:
            raise ValueError("Source-only review identity changed")
        targets = review["references"]
        for index,r in enumerate(original[d.document_id]):
            matching = [x for x in targets if x["symptom"] == r["symptom"] and overlaps(x,r)]
            ambiguous = [x for x in review["excluded_ambiguous_spans"] if overlaps(x,r)]
            decision = manual.get((d.document_id,index))
            if decision and decision["original_annotation"] != r:
                raise ValueError("Manual reference decision identity mismatch")
            status = reference_status(matching,ambiguous,decision)
            status_counts[status] += 1
            overlay.append({"document_id":d.document_id,"note_sha256":d.note_sha256,"annotation_index":index,
                "original_annotation":r,"status":status,"proposed_correction":None if status != "REFERENCE_INCORRECT" else {"remove_from_explicit_symptom_mention_reference":True},
                "evidence":{"quote":r["text"],"start":r["start"],"end":r["end"]},
                "supporting_mentions":matching,"ambiguous_source_spans":ambiguous,
                "reason":decision["reason"] if decision else "Source-only review supports this concept" if matching else
                    "Taxonomy/clinical boundary lacks independent expert verification" if ambiguous else
                    "Reference mismatch requires an explicit source decision; span alignment alone is not an error verdict",
                "verification_method":review["method"],"review_status":review["review_status"],"clinical_expert_verified":False})
        for target in targets:
            if not any(target["symptom"] == r["symptom"] and overlaps(target,r) for r in original[d.document_id]):
                status_counts["REFERENCE_INCOMPLETE"] += 1
                overlay.append({"document_id":d.document_id,"note_sha256":d.note_sha256,"original_annotation":None,
                    "status":"REFERENCE_INCOMPLETE","proposed_correction":target,
                    "evidence":{"quote":target["text"],"start":target["start"],"end":target["end"]},
                    "reason":"Explicit source mention is absent from original reference",
                    "verification_method":review["method"],"review_status":review["review_status"],"clinical_expert_verified":False})
    queue = load_jsonl(root / "reference-audit-queue.jsonl")
    for item in queue:
        if item["document_id"] not in reviews:
            overlay.append({"document_id":item["document_id"],"note_sha256":item["note_sha256"],
                "status":"UNRESOLVED","original_annotation":item["original_annotations"],"proposed_correction":None,
                "verification_method":"Exact source/offset audit and disagreement inventory only; model verification is provisional",
                "reason":"Not independently clinically adjudicated within bounded source-review scope",
                "selection_reasons":item["selection_reasons"]})
    refs = {doc_id:r["references"] for doc_id,r in reviews.items()}
    audited,filtered = {},{}
    for system,p in sets.items():
        values = {doc_id:[c for c in candidates if not excluded(c["evidence"],reviews[doc_id])]
                  for doc_id,candidates in p.items() if doc_id in reviews}
        filtered[system] = values
        eligible = available[system] & set(reviews)
        audited[system] = score(reviewed_docs,values,refs,eligible)[0]
        audited[system]["boundary_predictions_unscored"] = sum(len(p[doc_id])-len(values[doc_id]) for doc_id in values)
    assertion_scores = {}
    paired_identify = set(reviews) & set.intersection(*(available[s] for s in ("luna_raw","gliner_raw","luna_verified","gliner_verified")))
    paired_identify_scores = {s:score(reviewed_docs,filtered[s],refs,paired_identify)[0]
        for s in ("luna_raw","gliner_raw","luna_verified","gliner_verified")}
    for stage in ("extract_luna_raw","extract_gliner_raw","extract_luna_verified","extract_gliner_verified"):
        tp,pp,rr,complete,denominator,wrong_status = 0,0,0,0,0,0
        for d in reviewed_docs:
            if d.document_id not in available[stage]:
                continue
            result = effective(root,stage,d.document_id)
            if result is None:
                continue
            review = reviews[d.document_id]
            facts = [f for f in result["facts"] if concept_group(f["concept"]) in DEFINITIONS and not excluded(f["evidence"],review)]
            # Assertion-aware exact duplicate measurement keys preserve different polarities.
            unique = {(f["concept"],f["original_term"],f["evidence"]["start"],f["evidence"]["end"],f["polarity"]):f for f in facts}
            facts = list(unique.values())
            predicted = [{"concept":concept_group(f["concept"])+":"+f["polarity"],**f["evidence"]} for f in facts]
            gold = [{**r,"symptom":r["symptom"]+":"+r["polarity"]} for r in review["references"]]
            matches = match_mentions(predicted,gold)
            plain = match_mentions([{**p,"concept":p["concept"].rsplit(":",1)[0]} for p in predicted],review["references"])
            tp += len(matches); pp += len(predicted); rr += len(gold); denominator += 1
            complete += len(matches) == len(predicted) == len(gold)
            wrong_status += len(plain)-len(matches)
        assertion_scores[stage] = {**metrics(tp,pp,rr),"evaluated_documents":denominator,
            "complete_explicit_symptom_cases":complete,"status_mismatches_on_localized_mentions":wrong_status,
            "scope":"Five explicitly text-verified symptom concept/span/polarity keys; not complete universal fact or qualifier accuracy"}

    # Stage attribution relies on independent Identify records and actual frozen Extract facts.
    for d in reviewed_docs:
        review = reviews[d.document_id]
        for system in ("luna","gliner"):
            for phase in ("raw","verified"):
                identify_key,stage = system+"_"+phase,"extract_"+system+"_"+phase
                if d.document_id not in available[identify_key]:
                    continue
                identify = sets[identify_key][d.document_id]
                result = effective(root,stage,d.document_id)
                if result is None:
                    continue
                targets = review["references"]
                facts = result["facts"]
                ip = flat(identify)
                identified = {j:i for i,j in match_mentions(ip,targets)}
                fp = [{"concept":concept_group(f["concept"]),**f["evidence"],"fact_index":i}
                      for i,f in enumerate(facts) if concept_group(f["concept"]) in DEFINITIONS]
                extracted = {j:i for i,j in match_mentions(fp,targets)}
                for j,target in enumerate(targets):
                    category,secondary = None,[]
                    candidates = [c for c in identify if c["concept"] == target["symptom"] and overlaps(c["evidence"],target)]
                    extracted_facts = [f for f in facts if concept_group(f["concept"]) == target["symptom"] and overlaps(f["evidence"],target)]
                    if j not in extracted:
                        category = 2 if j in identified else 1
                        if candidates and j not in identified:
                            secondary.append("mention_granularity_one_to_one_boundary")
                        if extracted_facts:
                            secondary.append("fact_granularity_one_to_one_boundary")
                    elif extracted_facts and not any(f["polarity"] == target["polarity"] for f in extracted_facts):
                        category = 3
                    # The four causes only classify observed pipeline errors, not latent internal reasoning.
                    if category:
                        attribution.append({"document_id":d.document_id,"system":system,"phase":phase,
                            "status":"SOURCE_TEXT_VERIFIED_PIPELINE_ERROR" if not secondary else "GRANULARITY_DISAGREEMENT_UNRESOLVED",
                            "primary_category":category if not secondary else None,"secondary_causes":secondary,
                            "reference_target":target,"identify_evidence":candidates,"extracted_facts":extracted_facts,
                            "related_source_facts":[f for f in facts if overlaps(f["evidence"],target)],
                            "extract_result_present":True,"source_evidence":{"quote":target["text"],"start":target["start"],"end":target["end"]},
                            "verification_method":review["method"],"clinical_expert_verified":False})
                    if j not in identified and not candidates:
                        attribution.append({"document_id":d.document_id,"system":system,"phase":phase,
                            "status":"SOURCE_TEXT_VERIFIED_IDENTIFY_OMISSION","primary_category":1,
                            "scope":"Identify stage only; separately counted from downstream pipeline errors",
                            "extract_recovered":j in extracted,"reference_target":target,
                            "source_evidence":{"quote":target["text"],"start":target["start"],"end":target["end"]},
                            "verification_method":review["method"],"clinical_expert_verified":False})
                for candidate in identify:
                    if not any(candidate["concept"] == t["symptom"] and overlaps(candidate["evidence"],t) for t in targets) and not excluded(candidate["evidence"],review):
                        decision = manual_identify.get((d.document_id,system,phase,stable_hash(candidate)))
                        attribution.append({"document_id":d.document_id,"system":system,"phase":phase,
                            "status":"SOURCE_TEXT_VERIFIED_IDENTIFY_UNSUPPORTED_OR_MISMAPPED" if decision and decision["decision"] == "unsupported" else "UNRESOLVED_IDENTIFY_CONCEPT_DISAGREEMENT",
                            "primary_category":None,"reason":decision["reason"] if decision else "Unmatched audit target is insufficient for a semantic error verdict",
                            "identify_evidence":candidate,"source_evidence":candidate["evidence"],"clinical_expert_verified":False})
                for f in facts:
                    group = concept_group(f["concept"])
                    if group in DEFINITIONS and not any(group == t["symptom"] and overlaps(f["evidence"],t) for t in targets) and not excluded(f["evidence"],review):
                        attribution.append({"document_id":d.document_id,"system":system,"phase":phase,
                            "status":"SOURCE_TEXT_VERIFIED_PIPELINE_ERROR","primary_category":3,
                            "secondary_causes":["unsupported_or_incorrect_concept"],"extracted_fact":f,
                            "identify_evidence":[c for c in identify if overlaps(c["evidence"],f["evidence"])],
                            "source_evidence":f["evidence"],"verification_method":review["method"],"clinical_expert_verified":False})
    for row in ledger_rows(root):
        if row["status"] == "invalid":
            attribution.append({"document_id":row["document_id"],"stage":row["stage"],"attempt":row["attempt"],
                "status":"CONFIRMED_STRUCTURAL_FAILURE","primary_category":4,"error":row["error"],"raw_sha256":row["raw_hash"]})
        elif row["status"] in {"failed","reserved"}:
            attribution.append({"document_id":row["document_id"],"stage":row["stage"],"attempt":row["attempt"],
                "status":"INFRASTRUCTURE_FAILURE" if row["status"] == "failed" else "INTERRUPTED_RESERVATION",
                "primary_category":None,"error":row["error"]})
    for item in queue:
        if item["document_id"] not in reviews:
            attribution.append({"document_id":item["document_id"],"status":"UNRESOLVED_SOURCE_DISAGREEMENT",
                "primary_category":None,"reason":"Silver mismatch/model judgment is insufficient for confirmed root cause",
                "common_missing_reference_indices":item["common_missing_indices"]})
    common_mode,changes = Counter(),{s:Counter() for s in ("luna","gliner")}
    for d in reviewed_docs:
        gold = refs[d.document_id]
        correctness = {}
        for system in ("luna","gliner"):
            for phase in ("raw","verified"):
                key = system+"_"+phase
                if d.document_id not in available[key]:
                    continue
                p = flat(filtered[key].get(d.document_id,[]))
                pairs = match_mentions(p,gold)
                correctness[key] = len(pairs) == len(p) == len(gold)
                if phase == "raw":
                    raw_matches = {j for i,j in pairs}
                    raw_extra = {i for i in range(len(p)) if i not in {i for i,j in pairs}}
                elif d.document_id in available[system+"_raw"]:
                    verified_matches = {j for i,j in pairs}
                    raw_p = flat(filtered[system+"_raw"].get(d.document_id,[]))
                    raw_pairs = match_mentions(raw_p,gold)
                    raw_matches = {j for i,j in raw_pairs}
                    raw_extras = len(raw_p)-len(raw_pairs)
                    verified_extras = len(p)-len(pairs)
                    changes[system]["source_mentions_recovered"] += len(verified_matches-raw_matches)
                    changes[system]["source_mentions_lost"] += len(raw_matches-verified_matches)
                    changes[system]["net_unmatched_predictions_removed"] += raw_extras-verified_extras
        if "luna_raw" not in correctness or "gliner_raw" not in correctness:
            common_mode["raw_unavailable"] += 1
        else:
            a,b = correctness["luna_raw"],correctness["gliner_raw"]
            common_mode["both_text_complete" if a and b else "luna_only_text_complete" if a else
                        "gliner_only_text_complete" if b else "both_text_incomplete"] += 1
    jsonl(root / "reference_adjudication.jsonl",overlay,immutable=False)
    jsonl(root / "model_error_attribution.jsonl",attribution,immutable=False)
    summary = {"review_version":"source-text-audit-v1.1","reviewed_documents":len(reviews),
        "source_verified_mentions":sum(len(x["references"]) for x in reviews.values()),"selection":"Five per stratum, predetermined source-only SHA256 sample",
        "expert_verified":False,"scope":"Nonexpert, directly verifiable textual review; ambiguous spans unscored",
        "full_cohort_clinical_accuracy_available":False,"unresolved_queue_documents":sum(x['status']=='UNRESOLVED' for x in overlay),
        "reference_status_counts":dict(status_counts),"audited_scores":audited,"assertion_scores":assertion_scores,
        "paired_identify_denominator":len(paired_identify),"paired_identify_scores":paired_identify_scores,
        "attribution_status_counts":dict(Counter(x["status"] for x in attribution)),
        "four_category_counts":dict(Counter(str(x["primary_category"]) for x in attribution if x["primary_category"] and x["status"] != "SOURCE_TEXT_VERIFIED_IDENTIFY_OMISSION")),
        "per_system_phase_category_counts":dict(Counter(f"{x.get('system',x.get('stage'))}:{x.get('phase','attempt')}:category-{x['primary_category']}" for x in attribution if x["primary_category"] and x["status"] != "SOURCE_TEXT_VERIFIED_IDENTIFY_OMISSION")),
        "pipeline_category_counts":dict(Counter(f"{x['system']}:{x['phase']}:category-{x['primary_category']}" for x in attribution
            if x["status"] == "SOURCE_TEXT_VERIFIED_PIPELINE_ERROR")),
        "identify_stage_omission_counts":dict(Counter(f"{x['system']}:{x['phase']}" for x in attribution if x["status"] == "SOURCE_TEXT_VERIFIED_IDENTIFY_OMISSION")),
        "audited_common_mode":dict(common_mode),"audited_cross_changes":{s:dict(c) for s,c in changes.items()},
        "limitations":"Source-selected subset is small, not independent clinical expert adjudication. One-to-one mention granularity and wide fact citations limit assertion matching. Rates cannot be generalized to full cohort."}
    write_json(root / "audited-metrics.json",summary)
    return summary
