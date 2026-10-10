"""Frozen, proposition/evidence-scoped constraints; not exhaustive semantic precision.

An unmatched extra is explicitly unscored, never counted as correct. Human/expert
review is false. Additional AI audit labels do not rewrite these frozen scores.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone
from clinical_intelligence.claims_review.note_extractor import validate_proposal, RuntimeValidationError
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.prepare import prepare_case
from clinical_intelligence.claims_review.review import load_policy
from luna_bounded_ab import read, save, sha

VERSION='bounded-ab-scoring/1'


def equal(a,b):return type(a) is type(b) and a==b
def citation_lines(fact):
    ids=fact.get('span_ids',[]) or [c['locator'] for c in fact.get('citations',[])]
    return {int(s.rsplit(':L',1)[1]) for s in ids if isinstance(s,str) and ':L' in s and s.rsplit(':L',1)[1].isdigit()}
def matches(fact,spec):
    return fact.get('kind')==spec['kind'] and bool(citation_lines(fact)&set(spec['identity_lines'])) and bool(re.search(spec.get('statement_regex','.'),fact.get('statement',''),re.I))


def score_facts(facts,expected,source):
    counters=Counter(required_total=len(expected['facts']),missing=0,required_recalled=0,supported_required=0,field_total=0,field_matches=0,
        unnecessary_null=0,wrong_definite=0,binding_temporal_errors=0,duplicate_assertions=0,unsupported_extras=0,unscored_extras=0)
    rows=[];assigned=set();bad=[]
    for spec in expected['facts']:
        indexes=[i for i,f in enumerate(facts) if i not in assigned and matches(f,spec)]
        # Prefer narrower evidence overlap, never choose the response by gold values.
        index=min(indexes,key=lambda i:(len(citation_lines(facts[i])-set(spec['identity_lines'])),i)) if indexes else None
        if index is not None:assigned.add(index);counters['required_recalled']+=1
        else:counters['missing']+=1
        comparisons=[]
        for field,allowed in spec['fields'].items():
            value=facts[index].get(field) if index is not None else None
            correct=index is not None and any(equal(value,v) for v in allowed)
            counters['field_total']+=1;counters['field_matches']+=int(correct)
            unnecessary=index is not None and value is None and not any(v is None for v in allowed)
            certainty=index is not None and value is not None and not correct
            counters['unnecessary_null']+=int(unnecessary);counters['wrong_definite']+=int(certainty)
            counters['binding_temporal_errors']+=int(certainty and field in {'target_date','fact_date','date_role','temporal_status','provider','authenticated'})
            comparisons.append({'field':field,'allowed':allowed,'actual':value,'correct':correct,'unnecessary_null':unnecessary,'wrong_definite':certainty})
        # Duplicate/competing objects never disappear behind the first matching value.
        for extra in [i for i in indexes if i!=index]:
            assigned.add(extra);counters['duplicate_assertions']+=1
            for field,allowed in spec['fields'].items():
                value=facts[extra].get(field)
                if value is not None and not any(equal(value,v) for v in allowed):
                    counters['wrong_definite']+=1
                    counters['binding_temporal_errors']+=int(field in {'target_date','fact_date','date_role','temporal_status','provider','authenticated'})
                    bad.append({'index':extra,'field':field,'actual':value,'allowed':allowed,'reason':'Competing extra assertion'})
        rows.append({'proposition':spec['proposition'],'matched_index':index,'duplicate_indexes':[i for i in indexes if i!=index],'fields':comparisons})
        counters['supported_required']+=int(index is not None and all(c['correct'] for c in comparisons))
    for i,f in enumerate(facts):
        if i in assigned:continue
        forbidden=[r for r in expected.get('forbidden',[]) if f.get('kind')==r['kind'] and
                   (not r.get('identity_lines') or citation_lines(f)&set(r['identity_lines'])) and
                   all(any(equal(f.get(k),v) for v in vals) for k,vals in r.get('fields',{}).items())]
        if expected.get('no_target') or forbidden:
            counters['unsupported_extras']+=1;bad.append({'index':i,'reason':'No-target invention' if expected.get('no_target') else 'Predeclared unsupported inference','fact':f})
        else:
            counters['unscored_extras']+=1;bad.append({'index':i,'reason':'Unscored extra; semantic review required','fact':f})
    positional=[]
    for i,f in enumerate(facts):
        lines=citation_lines(f);valid=bool(lines) and all(n<=len(source['content'].splitlines()) and n>=1 for n in lines)
        positional.append({'index':i,'valid_line_reference':valid})
    return {'metrics':dict(counters),'propositions':rows,'extra_review':bad,'position_checks':positional,
            'complete_selected_constraints':not(counters['missing'] or counters['wrong_definite'] or counters['unnecessary_null'] or counters['unsupported_extras'])}


def evaluate(directory):
    frozen=read(directory/'freeze.json');state=read(directory/'round_state.json');seal=read(directory/'prediction-seal.json')
    if any(sha(p)!=h for p,h in frozen['files'].items()) or any(sha(p)!=h for p,h in seal['outputs'].items()):
        state['phase']='BENCHMARK_INVALID';save(directory/'round_state.json',state);raise ValueError('Frozen files/output drift')
    # All feasible preplanned predictions must have been sealed first, including partial stops.
    save(directory/'labels-open-event.json',{'opened_at':datetime.now(timezone.utc).isoformat(),'seal_sha256':sha(directory/'prediction-seal.json')})
    expected=read(directory/'expected.json');rows=[];audit=[]
    for item in state['plan']:
        case=CaseInput.model_validate_json((directory/'inputs'/f"{item['case_id']}.json").read_bytes())
        source=next(s for s in prepare_case(case,load_policy(),input_label='frozen')['source_candidates'] if s['source_kind']=='synthetic_note')
        e=expected['cases'][item['case_id']];stages=[]
        for number in item['calls']:
            folder=directory/'calls'/f'call-{number:03d}';raw=read(folder/'answer.json') if (folder/'answer.json').exists() else None
            error=None
            if raw is not None:
                try:validate_proposal(raw,source,case.review_context.as_of)
                except RuntimeValidationError as ex:error=str(ex)
            elif (folder/'failure.json').exists():error=read(folder/'failure.json')
            stages.append({'call':number,'raw_response':raw,'runtime_validation_error':error,'prompt_path':str(folder/'prompt.txt'),
                'visible_response_path':str(folder/'visible_answer.txt'),'usage':read(folder/'usage.json') if (folder/'usage.json').exists() else None})
        output=Path(item['output']) if item.get('output') else None
        packet=read(output) if output and output.exists() else None
        raw=stages[0]['raw_response'] if stages else None
        rawfacts=raw.get('facts',[]) if isinstance(raw,dict) and isinstance(raw.get('facts'),list) else []
        finalfacts=packet['facts'] if packet else []
        first=score_facts(rawfacts,e,source);final=score_facts(finalfacts,e,source)
        actual={r['criterion_id']:r['status'] for r in packet['criteria']} if packet else {}
        criteria={k:{'expected':v,'actual':actual.get(k),'correct':actual.get(k)==v} for k,v in e['criteria'].items()}
        row={**{k:item[k] for k in ['execution_id','split','candidate','repeat','case_id','status','calls']},'family':e['family'],
            'length':len(source['content']),'length_stratum':'long' if len(source['content'])>=650 else 'short',
            'first':first,'final':final,'criteria':criteria,'execution_failed':not packet or packet['execution']['execution_failed'],
            'repair':len(stages)>1,'first_validation_rejected':bool(stages and stages[0]['runtime_validation_error']),
            'seconds':item.get('seconds'),'usage':packet['execution']['usage'] if packet else None}
        rows.append(row)
        # Full before/after is retained; this mechanical list is not inferred entity alignment.
        delta={'first':rawfacts,'repair':stages[1]['raw_response'] if len(stages)>1 else None,'final':finalfacts,
            'first_to_final_exact_fact_change':rawfacts!=[{k:f.get(k) for k in rawfacts[0]} for f in finalfacts] if rawfacts else bool(finalfacts)}
        audit.append({'execution':item,'source':source,'expected_constraints':e,'stages':stages,'repair_delta':delta,
                      'packet':packet,'score':row})
    groups={}
    for split in ['dev','confirm']:
        for candidate in ['A','B']:
            subset=[r for r in rows if r['split']==split and r['candidate']==candidate and r['status']!='pending']
            entry={'executions':len(subset),'failures':sum(r['execution_failed'] for r in subset),'repairs':sum(r['repair'] for r in subset),
                'calls':sum(len(r['calls']) for r in subset),'seconds':sum(r['seconds'] or 0 for r in subset),
                'criterion_matches':sum(c['correct'] for r in subset for c in r['criteria'].values()),'criterion_total':4*len(subset)}
            for layer in ['first','final']:
                total=Counter()
                for r in subset:total.update(r[layer]['metrics'])
                entry[layer]={'metrics':dict(total),'complete_selected_constraints':sum(r[layer]['complete_selected_constraints'] for r in subset)}
            entry['strata']={}
            for dimension in ['repeat','length_stratum','family']:
                strata={}
                for key in sorted({str(r[dimension]) for r in subset}):
                    selected=[r for r in subset if str(r[dimension])==key];v=Counter()
                    for r in selected:v.update(r['first']['metrics'])
                    strata[key]={'executions':len(selected),'first':dict(v)}
                entry['strata'][dimension]=strata
            groups[f'{split}-{candidate}']=entry
    resources=[]
    for c in state['calls']:
        p=directory/'calls'/f"call-{c['number']:03d}"/'usage.json'
        usage=read(p) if p.exists() else {};metrics=usage.get('call_metrics',[])
        resources.append({**c,'last_call_metrics':metrics[-1] if metrics else None})
    tokens=[r['last_call_metrics'].get('tokens') if r['last_call_metrics'] else None for r in resources]
    usage_totals={k:sum(t.get(k,0) for t in tokens if t) for k in ['input_tokens','output_tokens','cached_input_tokens']}
    summary={'version':VERSION,'stop':state['phase'],'actual_provider_requests':state['attempts'],'groups':groups,
        'resources':resources,'measured_token_totals':usage_totals,'calls_with_usage':sum(bool(t) for t in tokens),
        'calls_without_usage':sum(not t for t in tokens),'provider_seconds':sum(c.get('seconds',0) for c in state['calls']),
        'failures':[r for r in rows if r['execution_failed'] or not r['first']['complete_selected_constraints'] or not r['final']['complete_selected_constraints']],
        'rows':rows,'semantic_precision':'UNAVAILABLE: selected frozen constraints plus separate AI-assisted audit, no exhaustive independent semantic labels',
        'human_review_completed':False,'designer_blind':False,'recommend_B':False,
        'recommendation_basis':'Keep A unless all predeclared adoption conditions are demonstrated, including two mechanism families and repeated direction.'}
    save(directory/'summary.json',summary);save(directory/'call-audit.json',{'version':VERSION,'method':'AI-assisted constraints and mechanical replay; not human semantic verification','executions':audit})
    print(json.dumps({k:{'executions':v['executions'],'first':v['first']['metrics'],'final':v['final']['metrics'],'calls':v['calls']} for k,v in groups.items()},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--round',type=Path,required=True);evaluate(p.parse_args().round.resolve())
