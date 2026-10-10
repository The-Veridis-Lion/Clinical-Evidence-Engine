"""POST_HOC_REANALYSIS of immutable saved proposals; standard library only.

Never imports production extraction, validators, providers or policy evaluation.
Identity precedes correctness. Unknown matching/semantics never become a pass.
"""
import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

VERSION='luna-ab-offline-rescore/2'
MISSING='__FIELD_MISSING__'
MODEL_CALLS=0


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp');tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');tmp.replace(path)
def check_deadline(directory,*,reserve_pass=False):
    p=Path(directory)/'rescore_state.json';s=read(p)
    if datetime.now(timezone.utc)>=datetime.fromisoformat(s['work_deadline']):
        s.update(terminal_status='TIME_LIMIT',phase='DELIVERY');save(p,s);raise RuntimeError('Offline work deadline reached')
    if s['max_new_provider_calls']!=0 or s['new_provider_calls']!=0:raise RuntimeError('Zero-call contract violated')
    if reserve_pass:
        if s['full_rescore_passes']>=s['max_full_rescore_passes']:raise RuntimeError('Two-pass ceiling reached')
        s['full_rescore_passes']+=1;s['phase']='RESCORING';save(p,s)
    return s


def numeric_projection(value):
    """Parse only the existing value. No source/gold backfill or unit conversion."""
    if type(value) in {int,float}:
        if not math.isfinite(value):return {'status':'INVALID','reason':'Non-finite'}
        return {'status':'CANONICAL','number':str(Decimal(str(value)).normalize()),'unit':None,'concept':None,'basis':'native numeric encoding'}
    if type(value) is bool:return {'status':'INVALID','reason':'Boolean is not a result number'}
    if not isinstance(value,str):return {'status':'UNRESOLVED','reason':'No numeric field value'}
    text=value.strip()
    if re.search(r'\b(?:not|no|denied|deny|negative|other patient|another patient|thyroid|albumin|fructosamine)\b|[<>≤≥]',text,re.I):
        return {'status':'INVALID','reason':'Negation/comparison/wrong concept or subject'}
    if re.search(r'mg\s*/\s*d[lL]|mmol|g\s*/\s*[lL]',text,re.I):return {'status':'INVALID','reason':'Different unit; no conversion'}
    pattern=r'(?:(Hb\s*A1c|Hgb\s*A1c|hemoglobin\s+A1c|haemoglobin\s+A1c)\s*(?:result\s*)?:?\s*)?([+-]?\d+(?:\.\d+)?)\s*(%|percent)?'
    m=re.fullmatch(pattern,text,re.I)
    if not m:return {'status':'UNRESOLVED','reason':'Unsupported/multiple numeric encoding'}
    return {'status':'CANONICAL','number':str(Decimal(m[2]).normalize()),'unit':'percent' if m[3] else None,
            'concept':'hba1c' if m[1] else None,'basis':'Exact finite scalar/value wrapper; original value preserved'}


def field_status(value,allowed,*,numeric=False,bare_allowed=False):
    if value==MISSING:return 'MISSING',None
    if numeric:
        p=numeric_projection(value)
        if p['status']=='UNRESOLVED':return ('UNNECESSARY_NULL' if value is None else 'UNRESOLVED'),p
        if p['status']=='INVALID':return 'WRONG_DEFINITE',p
        if isinstance(value,str) and p['unit'] is None and not bare_allowed:return 'UNRESOLVED',p
        expected=[numeric_projection(v) for v in allowed]
        correct=any(v['status']=='CANONICAL' and v['number']==p['number'] for v in expected)
        return ('CORRECT' if correct else 'WRONG_DEFINITE'),p
    correct=any(type(value) is type(v) and value==v for v in allowed)
    return ('CORRECT' if correct else 'UNNECESSARY_NULL' if value is None else 'WRONG_DEFINITE'),None


def frame(fact):
    kind=fact.get('kind');text=fact.get('statement','').lower()
    if kind=='diabetes_context':return 'other_subject_condition' if re.search(r'sibling|family history|another patient|other patient',text) else 'diabetes_context'
    if kind=='regimen_change':
        if re.search(r'not (?:been )?(?:implemented|begun|started)|has not begun|unchanged|nonimplementation|not yet',text):return 'regimen_state'
        if re.search(r'discuss|discussion|options',text) and re.search(r'future|planned|will|scheduled',text):return 'future_discussion'
        return 'regimen_state'
    if kind=='test_mention':
        if re.search(r'receipt|courier|new blood draw|new (?:test|collection)|already been performed',text) and not re.search(r'result\s*(?:of|line|:)|\d+\.\d+\s*(?:percent|%)',text):return 'performance_documentation'
        if re.search(r'thyroid|potassium|lipid|fructosamine|albumin',text) and (not re.search(r'hba1c|hgb|hemoglobin|glycated hemoglobin',text) or re.search(r'not\s+HbA1c',text,re.I)):return 'other_test'
        if re.search(r'historic|result|\d+\.\d+\s*(?:percent|%)',text):return 'test_result'
        if re.search(r'request|intend|repeat|order|collection|test',text):return 'test_intention_mention'
        return 'UNKNOWN'
    if kind in {'purpose','order_intent','clinical_rationale'}:return kind
    return 'UNKNOWN'


def evidence(fact,source):
    anchors={a['span_id']:a for a in source['line_anchors']}
    ids=fact.get('span_ids')
    if ids is None:ids=[c.get('locator') for c in fact.get('citations',[])]
    if not isinstance(ids,list) or not ids:return {'status':'GROUNDING_ERROR','lines':[],'reason':'Missing references'}
    if any(s not in anchors for s in ids):return {'status':'GROUNDING_ERROR','lines':[],'reason':'Wrong source/unknown span'}
    if fact.get('patient_id',source['patient_id'])!=source['patient_id'] or fact.get('source_id',source['source_id'])!=source['source_id']:
        return {'status':'IDENTITY_ERROR','lines':[],'reason':'Wrong patient/source'}
    for c in fact.get('citations',[]):
        a=anchors.get(c.get('locator'))
        if not a or any(c.get(k)!=a[k] for k in ['quote','start','end']):return {'status':'GROUNDING_ERROR','lines':[],'reason':'Citation slice changed'}
        if c.get('patient_id')!=source['patient_id'] or c.get('source_id')!=source['source_id']:return {'status':'IDENTITY_ERROR','lines':[],'reason':'Citation identity mismatch'}
        fields=['patient_id','source_id','encounter_id','available_at','availability_basis','event_date','recorded_at','origin','record_type','event_link_id','content','original_locator']
        if c.get('source_sha256')!=digest({k:source.get(k) for k in fields}):return {'status':'IDENTITY_ERROR','lines':[],'reason':'Citation source digest differs'}
    return {'status':'GROUNDED','lines':[int(s.rsplit(':L',1)[1]) for s in ids],
            'text':'\n'.join(anchors[s]['quote'] for s in ids),'reason':'Exact supplied source anchors; semantic scope checked separately'}


def match_identity(fact,spec,source):
    ev=evidence(fact,source)
    if ev['status']!='GROUNDED':return ev['status'],ev['reason']
    if fact.get('kind')!=spec['kind']:return 'NO_MATCH','Different family'
    if re.search(r'other patient|another patient',fact.get('statement',''),re.I):return 'IDENTITY_ERROR','Statement assigns the proposition to another patient'
    if re.search(r'thyroid|potassium|lipid|fructosamine|albumin',fact.get('statement',''),re.I) and not re.search(r'hba1c|hgb|hemoglobin|glycated hemoglobin',fact.get('statement',''),re.I):return 'NO_MATCH','Different clinical event/analyte in proposition'
    actual=frame(fact)
    if actual=='UNKNOWN' and set(ev['lines'])&set(spec['identity_lines']):return 'MATCH_UNRESOLVED','Unknown proposition with potentially related evidence'
    if actual!=spec['frame']:return 'NO_MATCH','Distinct proposition, regardless of shared context'
    if not set(ev['lines'])&set(spec['identity_lines']):return 'NO_MATCH','Missing proposition source evidence'
    label=spec.get('event_label')
    if label:
        text=fact.get('statement','').lower();other=[s for s in spec.get('competing_labels',[]) if s.lower() in text]
        if label.lower() in text and not other:return 'MATCH','Explicit event label in proposition plus grounded scope'
        if other and label.lower() not in text:return 'NO_MATCH','Different explicit event label'
        selected=set(ev['lines'])&set(spec['event_primary_lines']);foreign=set(ev['lines'])&set(spec.get('competing_event_lines',[]))
        if selected and not foreign:return 'MATCH','Unique original event locator, not selected by field values'
        return 'MATCH_UNRESOLVED','Event identity has overlapping evidence and no unique statement label'
    return 'MATCH','Patient/source + semantic proposition frame + original supporting locator; no correctness fields used'


def coherent_ambiguous_date(fact,spec):
    d=spec['ambiguous_date'];role=fact.get('date_role');fd=fact.get('fact_date');target=fact.get('target_date')
    if role=='order_issued' and fd==d and target is None:return 'COHERENT_ORDER_DATE'
    if role=='requested_test' and fd in {None,d} and target==d:return 'COHERENT_REQUESTED_DATE'
    if role=='actual_test' or (role=='order_issued' and target==d):return 'INCOHERENT_ROLE_BUNDLE'
    return 'UNRESOLVED_ROLE_BUNDLE'


def extra_category(fact,source,expected,*,matched=False):
    ev=evidence(fact,source)
    if ev['status']!='GROUNDED':return 'UNSUPPORTED',ev['reason']
    f=frame(fact);value=fact.get('value');text=fact.get('statement','')
    if expected.get('no_target'):
        if value is None and re.search(r'no|not|unknown|does not',text,re.I):return 'SUPPORTED_OUT_OF_SCOPE','Administrative absence placeholder, not a performed test'
        return 'UNSUPPORTED','No source-supported target fact in administrative control'
    if fact.get('authenticated') is False and re.search(r'no (?:authentication|signature information)|does not document authentication',ev['text'],re.I):
        return 'UNSUPPORTED','Missing authentication documentation is not explicit unsigned evidence'
    if f=='future_discussion':
        return ('UNRESOLVED','Readable discussion is grounded but regimen boolean scope is underspecified') if value is not None else ('SUPPORTED_IN_SCOPE','Future discussion separate from current implementation')
    if f=='other_test':
        named=re.search(r'thyroid|potassium|lipid|fructosamine|albumin',text,re.I)
        if not named or not re.search(re.escape(named[0]),ev['text'],re.I):return 'UNSUPPORTED','Different analyte has no cited support'
        return 'SUPPORTED_OUT_OF_SCOPE','Separate analyte retained; not target evidence'
    if f=='other_subject_condition':
        if not re.search(r'sibling|family history|another patient|other patient',ev['text'],re.I):return 'UNSUPPORTED','Different subject has no cited support'
        return 'SUPPORTED_OUT_OF_SCOPE','Separate subject retained; not target evidence'
    if f=='performance_documentation':
        if type(value) is bool:return 'UNRESOLVED','Boolean test_mention value does not define the proposition it negates/affirms'
        return 'SUPPORTED_IN_SCOPE','Receipt/performance documentation differs from historical result'
    if f=='UNKNOWN':return 'UNRESOLVED','Finite matcher cannot establish proposition'
    if f=='diabetes_context' and value is not None and re.search(r'not documented|not been documented|uncertain|unavailable',ev['text'],re.I):return 'UNSUPPORTED','Unknown documentation promoted to definite disease state'
    if f=='test_intention_mention':
        if type(value) is bool:return 'UNRESOLVED','Boolean test_mention value has no uniquely defined semantics'
        return 'SUPPORTED_IN_SCOPE','Source test intention mention; not independent performance'
    if value is None:
        if re.search(r'not|no |missing|unknown|supplied|document',text,re.I):return 'SUPPORTED_IN_SCOPE','Source/documentation uncertainty; not a definite clinical fact'
        return 'UNRESOLVED','Null assertion meaning not established'
    return 'UNRESOLVED','Extra definite assertion needs hash-bound AI review; not presumed correct'


def score_output(facts,source,expected,*,proposal_identity=None):
    metrics=Counter(candidate_fields=0,scored_fields=0,correct_fields=0,unresolved_fields=0,wrong_definite=0,
        unnecessary_null=0,missing_fields=0,missing_propositions=0,binding_errors=0,required_propositions=len(expected['facts']),
        complete_propositions=0,duplicate_propositions=0,contradictory_propositions=0,date_bundle_errors=0)
    checks=[];assignments=defaultdict(list);grounding=[]
    for i,f in enumerate(facts):grounding.append({'index':i,**evidence(f,source)})
    identity_error=proposal_identity is not None and any(proposal_identity.get(k)!=source[k] for k in ['patient_id','source_id'])
    for spec in expected['facts']:
        matches=[];uncertain=[];reasons=[]
        for i,f in enumerate(facts):
            status,reason=match_identity(f,spec,source)
            if identity_error:status='IDENTITY_ERROR';reason='Proposal identity differs from source'
            if status=='MATCH':matches.append(i);assignments[i].append(spec['constraint_id'])
            if status=='MATCH_UNRESOLVED':uncertain.append(i)
            if status in {'MATCH','MATCH_UNRESOLVED'}:reasons.append({'index':i,'status':status,'reason':reason})
        row={'constraint_id':spec['constraint_id'],'proposition':spec['proposition'],'matched_indexes':matches,'uncertain_indexes':uncertain,'matching_reasons':reasons,'fields':[]}
        if not matches and not uncertain:metrics['missing_propositions']+=1
        if len(matches)>1:metrics['duplicate_propositions']+=1
        for field,allowed in spec['fields'].items():
            metrics['candidate_fields']+=1
            if field in spec.get('unresolved_fields',{}) or uncertain:
                status='UNRESOLVED';observations=[];reason=spec.get('unresolved_fields',{}).get(field,'Match identity unresolved')
                metrics['unresolved_fields']+=1
            else:
                observations=[]
                for i in matches:
                    value=facts[i].get(field,MISSING)
                    fs,projection=field_status(value,allowed,numeric=spec.get('numeric_value',False) and field=='value',bare_allowed=spec.get('bare_numeric_allowed',False))
                    observations.append({'index':i,'value':value,'status':fs,'canonical_projection':projection})
                statuses=[o['status'] for o in observations]
                status='MISSING' if not matches else 'WRONG_DEFINITE' if 'WRONG_DEFINITE' in statuses else 'UNRESOLVED' if 'UNRESOLVED' in statuses else 'MISSING' if 'MISSING' in statuses else 'UNNECESSARY_NULL' if 'UNNECESSARY_NULL' in statuses else 'CORRECT'
                reason='All matched output objects independently checked; never stitch fields or choose a correct object'
                if status=='UNRESOLVED':metrics['unresolved_fields']+=1
                else:
                    metrics['scored_fields']+=1;metrics['correct_fields']+=int(status=='CORRECT')
                    metrics['wrong_definite']+=int(status=='WRONG_DEFINITE');metrics['unnecessary_null']+=int(status=='UNNECESSARY_NULL');metrics['missing_fields']+=int(status=='MISSING')
                    metrics['binding_errors']+=int(status=='WRONG_DEFINITE' and field in {'target_date','fact_date','date_role','temporal_status','provider','authenticated'})
            row['fields'].append({'field':field,'status':status,'allowed':allowed,'observations':observations,'reason':reason})
        if spec.get('numeric_value'):
            row['statement_information_review']=[{'index':i,'source':'model_statement_only','statement':facts[i].get('statement'),
                'field_value':facts[i].get('value',MISSING),'does_not_fill_value_field':True} for i in matches]
        row['complete_scored_fields']=bool(matches) and all(f['status'] in {'CORRECT','UNRESOLVED'} for f in row['fields'])
        row['fully_resolved']=not any(f['status']=='UNRESOLVED' for f in row['fields'])
        metrics['complete_propositions']+=int(row['complete_scored_fields'] and row['fully_resolved'])
        if len(matches)>1 and any(f['status']=='WRONG_DEFINITE' for f in row['fields']):metrics['contradictory_propositions']+=1
        if spec.get('ambiguous_date'):
            row['date_bundle_review']=[{'index':i,'status':coherent_ambiguous_date(facts[i],spec)} for i in matches]
            metrics['date_bundle_errors']+=sum(b['status']=='INCOHERENT_ROLE_BUNDLE' for b in row['date_bundle_review'])
        checks.append(row)
    extras=[]
    for i,f in enumerate(facts):
        if i in assignments:continue
        category,reason=extra_category(f,source,expected)
        extras.append({'index':i,'fact_sha256':digest(f),'frame':frame(f),'category':category,'reason':reason,'original_fact':f})
    metrics['grounding_identity_errors']=sum(g['status']!='GROUNDED' for g in grounding)+int(identity_error)
    return {'metrics':dict(metrics),'constraints':checks,'extras':extras,'grounding':grounding,
        'complete_common_scored_constraints':not metrics['grounding_identity_errors'] and not metrics['date_bundle_errors'] and not any(f['status'] not in {'CORRECT','UNRESOLVED'} for c in checks for f in c['fields']),
        'unresolved_present':any(f['status']=='UNRESOLVED' for c in checks for f in c['fields']) or any(e['category']=='UNRESOLVED' for e in extras)}


def run(original,directory):
    state=check_deadline(directory,reserve_pass=True);number=state['full_rescore_passes'];out=directory/f'pass-{number:02d}'
    overlay=read(directory/'expected_review_overlay.json');audit=read(original/'call-audit.json');rows=[]
    save(out/'version.json',{'analysis':'POST_HOC_REANALYSIS','version':VERSION,'scorer_sha256':sha(__file__),
        'overlay_sha256':sha(directory/'expected_review_overlay.json'),'contract_sha256':sha(directory/'evaluation_contract_v2.md')})
    for e in audit['executions']:
        check_deadline(directory)
        execution=e['execution'];case=execution['case_id'];source=e['source'];expected=overlay['cases'][case]
        if digest(source)!=expected['source_sha256']:raise ValueError('Source changed')
        first=e['stages'][0]['raw_response'] if e['stages'] else None
        firstfacts=first.get('facts',[]) if isinstance(first,dict) else []
        packet=e.get('packet');finalfacts=packet.get('facts',[]) if isinstance(packet,dict) else []
        row={k:execution[k] for k in ['execution_id','case_id','split','candidate','repeat','calls']}
        row.update(first=score_output(firstfacts,source,expected,proposal_identity=first),final=score_output(finalfacts,source,expected),
            source_sha256=digest(source),first_sha256=digest(first),final_sha256=digest(finalfacts),old=e['score'],
            materials_missing=first is None or packet is None,criteria_preserved=[{'criterion_id':c['criterion_id'],'status':c['status']} for c in packet['criteria']] if packet else [],
            saved_validator_errors=[s['runtime_validation_error'] for s in e['stages']],
            repair_stage_count=max(0,len(e['stages'])-1),usage_is_historical=True)
        rows.append(row)
    groups={}
    for split in ['dev','confirm']:
        for candidate in ['A','B']:
            selected=[r for r in rows if r['split']==split and r['candidate']==candidate];group={'executions':len(selected)}
            for layer in ['first','final']:
                total=Counter();extras=Counter()
                for r in selected:total.update(r[layer]['metrics']);extras.update(e['category'] for e in r[layer]['extras'])
                group[layer]={'metrics':dict(total),'extra_categories':dict(extras),
                    'complete_common_scored_constraints':sum(r[layer]['complete_common_scored_constraints'] for r in selected),
                    'unresolved_executions':sum(r[layer]['unresolved_present'] for r in selected)}
            groups[f'{split}-{candidate}']=group
    paired=[]
    for split in ['dev','confirm']:
        ids=sorted({(r['case_id'],r['repeat']) for r in rows if r['split']==split})
        for case,repeat in ids:
            a=next(r for r in rows if r['case_id']==case and r['repeat']==repeat and r['candidate']=='A');b=next(r for r in rows if r['case_id']==case and r['repeat']==repeat and r['candidate']=='B')
            pair={'case_id':case,'repeat':repeat,'split':split}
            for layer in ['first','final']:
                cells=lambda r:{(c['constraint_id'],f['field']):f['status'] for c in r[layer]['constraints'] for f in c['fields']}
                ac,bc=cells(a),cells(b);common=[k for k in ac if ac[k]!='UNRESOLVED' and bc[k]!='UNRESOLVED']
                changes=[{'constraint_id':k[0],'field':k[1],'A':ac[k],'B':bc[k]} for k in common if ac[k]!=bc[k]]
                gain=sum(ac[k]!='CORRECT' and bc[k]=='CORRECT' for k in common);loss=sum(ac[k]=='CORRECT' and bc[k]!='CORRECT' for k in common)
                direction='IMPROVED' if gain and not loss else 'REGRESSED' if loss and not gain else 'MIXED' if gain and loss else 'SAME'
                pair[layer]={'common_fields':len(common),'A_correct':sum(ac[k]=='CORRECT' for k in common),'B_correct':sum(bc[k]=='CORRECT' for k in common),
                    'gain':gain,'loss':loss,'direction':direction,'changes':changes,'excluded_unresolved_fields':[list(k) for k in ac if k not in common]}
            paired.append(pair)
    # Deduplicate historical request IDs; cumulative usage is never added twice.
    calls={s['call'] for e in audit['executions'] for s in e['stages']};historical=[]
    for n in sorted(calls):
        u=read(original/'calls'/f'call-{n:03d}'/'usage.json');cm=u.get('call_metrics',[]);historical.append({'call':n,'usage':cm[-1].get('tokens') if cm else None})
    result={'analysis':'POST_HOC_REANALYSIS','version':VERSION,'groups':groups,'rows':rows,'paired':paired,
        'unique_original_notes':len({r['case_id'] for r in rows}),'execution_count':len(rows),'new_model_calls':0,'new_experiment_tokens':0,
        'historical_unique_requests':len(calls),'historical_usage':historical,'human_review_completed':False,'reviewer_type':'AI_ASSISTED',
        'overall_fact_precision_recall':'UNAVAILABLE: partial labelled constraint coverage; extras not exhaustively adjudicated',
        'default_prompt':'A','missing_materials':sum(r['materials_missing'] for r in rows)}
    save(out/'scores.json',result)
    state=read(directory/'rescore_state.json');state['phase']='REVIEW_RESULTS';state['latest_pass']=str(out);save(directory/'rescore_state.json',state)
    print(json.dumps({'groups':groups,'new_model_calls':0,'historical_calls':len(calls)},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--original',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.original.resolve(),a.output.resolve())

if __name__=='__main__':main()
