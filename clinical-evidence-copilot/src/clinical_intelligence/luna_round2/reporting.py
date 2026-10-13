"""Bounded evidence review inventory and concise reporting, with no model judge."""
import json
from collections import Counter
from .runtime import integrity, result, result_path
from .evaluation import ledger_rows
from .contract import catalogue, APPROACHES
from ..simsum_comparison.execution import read
from ..simsum_comparison.evaluation import load_jsonl, jsonl, references
from ..simsum_comparison.__main__ import documents
from ..clinical_notes.dataset import sha, write_json

def audit_queue(repo,root,phase):
    manifest=integrity(repo,root)
    docs={d.document_id:d for d in documents(repo)}
    metrics=read(root/phase/'metrics.json')
    rows=ledger_rows(root,phase)
    names=list(APPROACHES) if phase=='comparison' else [read(root/'winner-freeze.json')['winner']]
    trail=[]
    for row in rows:
        if row['status'] in {'failed','invalid','reserved'}:
            trail.append({'document_id':row['document_id'],'phase':phase,'system':row['stage'],
                'status':'CONFIRMED_STRUCTURAL_FAILURE' if row['status']=='invalid' else 'INFRASTRUCTURE_OR_EXECUTION_FAILURE',
                'primary_root_cause':4 if row['status']=='invalid' else None,'error':row['error'],
                'raw_hash':row['raw_hash'],'stage_observed':row['stage'].split('.')[-1]})
    for name in names:
        for record in load_jsonl(root/phase/(name+'-audited-comparisons.jsonl')):
            d=docs[record['document_id']]
            identified=result(root,phase,name,'identify',d.document_id)
            ids=identified['evidence_ids'] if identified else []
            for index in record['missing']:
                target=record['source_references'][index]
                localized=[c['source_id'] for c in catalogue(d) if c['start']<=target['start'] and target['end']<=c['end']]
                hint_present=bool(set(localized)&set(ids))
                trail.append({'document_id':d.document_id,'phase':phase,'system':name,
                    'status':'SOURCE_REVIEWED_REFERENCE_UNMATCHED_REQUIRES_OUTPUT_INSPECTION',
                    'source_evidence':target,'identify_evidence_ids':ids,'target_source_ids':localized,
                    'candidate_root_cause':(2 if hint_present else 1) if identified is not None else None,
                    'primary_root_cause':None,'reason':'Do not infer hidden Identify behavior in a single-stage output; normalization and granularity need source review'})
            for index in record['unmatched']:
                trail.append({'document_id':d.document_id,'phase':phase,'system':name,
                    'status':'UNMATCHED_FACT_REQUIRES_SOURCE_REVIEW','fact':record['facts'][index],
                    'primary_root_cause':None,'candidate_root_cause':3,
                    'reason':'Extra boundaries, assertion scope and reference omissions are not automatic semantic errors'})
    jsonl(root/phase/'model-error-attribution.jsonl',trail)
    references_by_id,_=references(repo,list(docs.values()))
    selected={r['document_id'] for r in trail if r.get('source_evidence') or r.get('fact')}
    details={name:{x['document_id']:x for x in load_jsonl(root/phase/(name+'-silver-comparisons.jsonl'))} for name in names}
    all_ids=set().union(*(set(v) for v in details.values()))
    for variant in ('text','advanced_text'):
        ordered=sorted([i for i in all_ids if docs[i].variant==variant and any(
            details[n][i]['missing_indices'] or details[n][i]['unmatched_indices'] for n in names)],
            key=lambda i:(-sum(len(details[n][i]['missing_indices'])+len(details[n][i]['unmatched_indices']) for n in names),sha('round2-review:'+i)))
        selected.update(ordered[:5])
    selected=sorted(selected,key=lambda i:sha('round2-review:'+i))[:20]
    jsonl(root/phase/'bounded-manual-review-queue.jsonl',[{'document_id':i,'note_sha256':docs[i].note_sha256,
        'full_note':docs[i].text,'original_annotations':references_by_id[i],
        'predictions':{n:result(root,phase,n,'extract',i) for n in names},
        'identify':{n:result(root,phase,n,'identify',i) for n in names},
        'status':'UNRESOLVED_UNTIL_SOURCE_INSPECTION','selection':'Audited mismatches then five high-disagreement cases per variant; SHA-bound at 20'} for i in selected])
    return Counter(x['status'] for x in trail)

def percent(x):return 'N/A' if x is None else f'{100*x:.2f}%'

def report(repo,root):
    comparison=read(root/'comparison/metrics.json');final=read(root/'final/metrics.json');winner=read(root/'winner-freeze.json')
    lines=['# Luna Clinical Extraction — Round 2','',
        'Two candidates were justified by historical evidence: direct indexed extraction and indexed Identify → the identical Extract instruction. No third model or candidate, verifier, repair, threshold search, or GLiNER installation was used.',
        '', 'Both preserve the universal clinical fact schema. The wire evidence is source_id + exact quote; the adapter resolves unique source substrings mechanically to Unicode offsets. It neither infers facts nor filters clinically meaningful assertions. Full-note context is available to both. The shared prompt clarifies negation scope and independent named findings within compound passages.',
        '', 'Historical reports and predictions were reviewed before implementation: SimSUM v1/v2 normalization, assertion granularity, negative scope, inaccurate source coordinates, annotation defects and provider configuration failures; older Claims/HbA1c experiments were reviewed for source-contract/scorer failures and were not transplanted into this respiratory benchmark.',
        '', 'The catalogue retains the existing mechanical segmentation. The indexing change addresses the 215 invalid Identify attempts in the prior comparison. JSON schema validity alone does not establish clinical correctness. [Official structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs).',
        '', '## Frozen comparison: same 100 patients','',
        '50 standard + 50 advanced notes; five previously reviewed patients per stratum are deliberately included. The other 90 are selected deterministically by SHA256. This is a reused development benchmark. The exact source hashes, prompts, schemas, scoring, source audits and lexicographic selection rule were frozen before inference. Primary selection uses source-audited end-to-end concept/span/polarity/experiencer F1, followed by complete-case rate, operational silver F1, structural success, then fewer calls. Identify F1 does not select the winner.',
        '', '| System | Calls | Valid / selected | Silver P | Silver R | Silver F1 | Silver complete cases | Audited F1 | Audited complete cases |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,s in comparison['systems'].items():
        t=s['silver']['all'];a=s['audited'];v=t['overlap']
        lines.append(f"| {name} | {s.get('execution',{}).get('calls','historical cache')} | {t['valid_documents']} / {t['documents']} | {percent(v['precision'])} | {percent(v['recall'])} | {percent(v['f1'])} | {t['complete_mention_cases']} / {t['documents']} | {percent(a['f1'])} | {a['complete_cases']} / {a['documents']} |")
    lines+=['',f"Winner: **{winner['winner']}**. The frozen ranking keys are recorded in winner-freeze.json; no post-final tuning was performed.",
        '', '## Separate final evaluation: all original 300 patients','',
        'Fresh requests include the selection 100 and remaining 200. No comparison predictions substitute for the new final run; losing candidates stop at 100. Missing or structurally invalid outputs remain in operational recall and complete-case denominators.',
        '', '| System / subset | Selected | Valid | Silver P | Silver R | Silver F1 | Complete cases | Audited P / R / F1 | Audited complete cases |',
        '|---|---:|---:|---:|---:|---:|---:|---|---:|']
    for name,s in final['systems'].items():
        for label,values in [('all_300',s),*s['subsets'].items()]:
            t=values['silver']['all'];v=t['overlap'];a=values['audited']
            lines.append(f"| {name} / {label} | {t['documents']} | {t['valid_documents']} | {percent(v['precision'])} | {percent(v['recall'])} | {percent(v['f1'])} | {t['complete_mention_cases']} / {t['documents']} | {' / '.join(percent(a[k]) for k in ('precision','recall','f1'))} | {a['complete_cases']} / {a['documents']} |")
    lines+=['','## Strata, reliability and usage','', '| Phase / system | Standard F1 | Advanced F1 | Structural success | Calls | Median request seconds | Wall seconds | Valid documents/min |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
    outcomes=[]
    for phase,m in [('comparison',comparison),('final',final)]:
        for name,s in m['systems'].items():
            if 'execution' not in s:continue
            e=s['execution'];g=s['silver']
            lines.append(f"| {phase} / {name} | {percent(g['standard']['overlap']['f1'])} | {percent(g['advanced']['overlap']['f1'])} | {percent(g['all']['structural_success_rate'])} | {e['calls']} | {e['latency_median_seconds']:.2f} | {e['wall_seconds']:.2f} | {e['valid_documents_per_minute']:.2f} |")
            outcomes += [f"\n{phase}/{name} stage outcomes: `{json.dumps(e['stage_statuses'],sort_keys=True)}`. Valid normalized fact citations: {s['citation']['valid']}; malformed raw outputs are separate structural failures."]
    lines+=outcomes
    total=comparison['dispatches']+final['dispatches']
    lines += ['',f'Actual ledger/application dispatches: **{total} / 1,200**. Comparison: {comparison["dispatches"]}; final: {final["dispatches"]}. Every failure counts. No automatic transport, schema, or verification retry. Phase ledgers are independent and capped by their frozen plans.',
        '',f"Comparison usage ({comparison['known_usage_requests']} known requests): `{json.dumps(comparison['token_usage'],sort_keys=True)}`.",
        '',f"Final usage ({final['known_usage_requests']} known requests): `{json.dumps(final['token_usage'],sort_keys=True)}`.",
        '', 'Cached-input and reasoning-token fields are subsets, not additive costs. Subscription billing and backend model snapshot are unavailable; no estimated dollar cost is fabricated.',
        '', '## Evidence auditing and limitations','',
        'Original silver references stay immutable. Five symptom concepts use the existing maximum one-to-one positive-overlap matcher, with exact-span and document-concept metrics separately saved. Identical concept/interval mention keys alone deduplicate. Audited facts preserve distinct nasal manifestations and assertion status. Silver has no adequate polarity, temporality or experiencer labels.',
        '', 'The selection audit contains 10 historical source-reviewed documents. A further 10 from the remaining 200 were source-only reviewed before new inference; final audited coverage is 20/300. Reviews are nonexpert engineering text inspections, not independent clinical gold. Complete-case scores cover only the five explicit symptom concepts, not all universal categories. The selection subset is purposefully enriched for known reviewed cases; the final 20 are not full-cohort ground truth.',
        '', 'Citation/schema failures receive root cause 4. Confirmed source-supported omissions can receive root cause 1 or 2 only when Identify evidence is independently observable. A direct model has no observable internal Identify trace; its missing facts do not establish which hidden stage failed. Semantic concept/polarity/temporal/subject errors receive category 3 only after source inspection. Annotation defects, infrastructure errors, evaluator defects, granularity disputes and unresolved interpretations remain separate.',
        '', 'The bounded source-review queue, original annotations, raw indexed outputs, normalized facts, source offsets and stage-level trails remain in ignored local artifacts. Additional unmatched silver mentions are disagreements, not automatically false clinical assertions.',
        '', '## Interpretation against the previous baseline','',
        'The tables re-evaluate cached historical first-attempt and effective single-pass v2 outputs under the same frozen Round 2 contract and source audits. Original historical metrics remain unchanged. The first-attempt baseline offers the closer no-repair reliability comparison; the effective baseline includes its historical permitted repairs. Numeric differences on this repeatedly used development cohort do not establish unseen-data generalization or causal improvement.',
        '', '## Reproduction','',
        'See docs/luna-round2-workflow-v1.md. manifest.json pins provider, source/cohort/audit/code/prompt/schema hashes; comparison/requests.sqlite3 and final/requests.sqlite3 enforce their plans. Raw responses precede postprocessing, are immutable, and are preserved with exact source identity. No model weights or new heavy dependencies are required. Stop after this final 300-document run.']
    manual=root/'manual-source-review.jsonl'
    if manual.exists():
        decisions=load_jsonl(manual)
        lines+=['','Source-inspected review decisions: `'+json.dumps(dict(Counter(x['status'] for x in decisions)),sort_keys=True)+'`. See the evidence overlay; source-supported decisions are distinct from unresolved discrepancies.']
    text='\n'.join(lines)+'\n'
    (root/'report.md').write_text(text,encoding='utf-8',newline='\n')
    (repo/'docs/luna-round2-results-v1.md').write_text(text,encoding='utf-8',newline='\n')
    write_json(repo/'docs/luna-round2-metrics-v1.json',{'comparison':comparison,'final':final,'winner':winner})

