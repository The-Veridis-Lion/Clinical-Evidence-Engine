"""Declared structured mappings and source-scoped citations; no model inference."""
from datetime import date
from .contracts import Citation, EvidenceFact
from .prepare import digest

VERSION = 'claims-review-structured/1'
PURPOSES = {
    'routine monitoring of established type 2 diabetes': 'monitoring',
    'monitor response after the treatment change': 'monitoring',
    'monitoring established type 2 diabetes': 'monitoring',
    'diabetes screening during preventive care': 'screening',
}


def source_key(source):
    # Content equivalence does not erase patient, record, encounter or provenance identity.
    return digest({k: source.get(k) for k in [
        'patient_id', 'source_id', 'encounter_id', 'available_at', 'availability_basis',
        'event_date', 'recorded_at', 'origin', 'record_type', 'event_link_id',
        'content', 'original_locator']})


def pointer(source, field):
    value = source.get(field) if field != 'content' and not field.startswith('content/') else source['content']
    if field.startswith('content/'):
        value = source['content'][field.split('/',1)[1]]
    encoded = '/'.join(p.replace('~','~0').replace('/','~1') for p in field.split('/'))
    return Citation(patient_id=source['patient_id'],source_id=source['source_id'],source_sha256=source_key(source),
        method='input_json_pointer',locator=source['source_ref']['json_pointer']+'/'+encoded,
        raw_value=value,original_locator=({**source['original_locator'], 'column':field.split('/',1)[1]}
            if source['original_locator'] is not None and field.startswith('content/') else source['original_locator']))


def parsed_date(value):
    if value is None:return None
    if not isinstance(value,str):return None
    try:return date.fromisoformat(value)
    except ValueError:return None


def target_test(source):
    c=source['content']
    return isinstance(c,dict) and (c.get('service_concept')=='hba1c' or
        source['origin']=='synthea_export' and c.get('CODE')=='4548-4')


def actual_test(source):
    if not target_test(source):return False
    c=source['content'];status=c.get('status')
    return source['record_type']=='observation' and (status=='final' or source['origin']=='synthea_export') or (
        source['record_type']=='procedure' and status=='completed')


def make_fact(source,kind,value,*,statement=None,fact_date=None,date_role='unknown',temporal_status='unknown',
              target_date=None,test_specific=None,provider=None,authenticated=None,reporter=None,citations=None,details=None):
    payload=dict(patient_id=source['patient_id'],source_id=source['source_id'],kind=kind,
        statement=statement or f'{source["record_type"]}: {source["content"].get("description",kind)}',value=value,
        fact_date=fact_date,date_role=date_role,temporal_status=temporal_status,target_date=target_date,
        test_specific=test_specific,provider=provider,reporter=reporter,authenticated=authenticated,
        event_link_id=source['event_link_id'],citations=citations or [pointer(source,'content/'+k) for k in source['content']]+[pointer(source,'event_date')],
        details=details or {})
    fact=EvidenceFact(fact_id='pending',**payload)
    return fact.model_copy(update={'fact_id':digest(fact.model_dump(mode='json',exclude={'fact_id'}))[:24]})


def structured_facts(prepared):
    facts=[]
    for s in prepared['source_candidates']:
        if s['source_kind']!='structured_record':continue
        c=s['content'];d=parsed_date(s['event_date']);kind=s['record_type']
        facts.append(make_fact(s,'source_record',None,details={'raw_content':c,'interpretation':'Unmodified structured fields; not a clinical assertion.'}))
        if actual_test(s):
            facts.append(make_fact(s,'test_event',c.get('value',c.get('VALUE')),
                fact_date=d,date_role='actual_test',temporal_status='actual',test_specific=True,
                details={'actual_performance_supported':True,'raw_content':c}))
        elif kind=='procedure' and target_test(s):
            facts.append(make_fact(s,'test_mention',None,fact_date=d,date_role='requested_test',
                temporal_status='planned' if c.get('status')=='scheduled' else 'unknown',test_specific=True))
        if kind=='condition' and (c.get('description')=='Established type 2 diabetes mellitus' or
            s['origin']=='synthea_export' and c.get('CODE')=='44054006'):
            active=c.get('status')=='active'
            facts.append(make_fact(s,'diabetes_context',True,fact_date=d,date_role='background_review',
                temporal_status='actual' if active else 'historical',details={'current_activity':True if active else None,'raw_content':c}))
        if kind=='medication_order':
            started=c.get('administration_or_start_confirmed')
            started=started if isinstance(started,bool) else None
            facts.append(make_fact(s,'regimen_change',started,
                fact_date=parsed_date(c.get('actual_start_date')) if started is True else None,
                date_role='adjustment_start' if started is True else 'unknown',
                temporal_status='actual' if started is True else 'planned',details={'raw_content':c,'order_issued_date':s['event_date']}))
        if kind=='order' and target_test(s):
            target=parsed_date(c.get('requested_service_date'))
            auth={'electronically_signed':True,'signed':True,'unsigned':False}.get(c.get('authentication_status'))
            intent={'issued':True,'cancelled':False}.get(c.get('order_status'))
            facts.append(make_fact(s,'order_intent',intent,fact_date=d,date_role='order_issued',temporal_status='planned',
                target_date=target,test_specific=True,provider=c.get('ordering_provider'),authenticated=auth,
                details={'raw_content':c,'authentication_scope':'This order only; not other records.'}))
            purpose=c.get('purpose')
            if isinstance(purpose,str):
                facts.append(make_fact(s,'purpose',PURPOSES.get(purpose.casefold()),target_date=target,
                    temporal_status='planned',test_specific=True,details={'raw_purpose':purpose,'mapping':'Declared finite purpose vocabulary.'}))
    return facts


def test_timeline(case,prepared,facts):
    grouped={};by_id={s.source_id:s.model_dump(mode='json') for s in case.sources}
    for f in facts:
        if f.kind!='test_event':continue
        key=f.event_link_id or 'unlinked:'+f.source_id
        g=grouped.setdefault(key,dict(event_key=key,source_ids=[],dates=[],date_unknown=False,identity_explicit=f.event_link_id is not None,citations=[]))
        g['source_ids'].append(f.source_id)
        if f.fact_date is None:g['date_unknown']=True
        else:g['dates'].append(f.fact_date.isoformat())
        g['citations'] += [c.model_dump(mode='json') for c in f.citations]
    for group in prepared['explicit_event_groups']:
        g=grouped.get(group['event_link_id'])
        if g is None:continue
        for member in group['members']:
            # Available, correctly scoped excluded-window members still expose actual-date conflicts.
            s=by_id[member['source_id']]
            if not actual_test(s):continue
            if member['source_id'] not in g['source_ids']:
                s['source_ref']=member['source_ref']
                g['source_ids'].append(s['source_id'])
                g['citations'] += [pointer(s,'event_date').model_dump(mode='json'),pointer(s,'content').model_dump(mode='json')]
            if s['event_date'] is None:g['date_unknown']=True
            else:g['dates'].append(s['event_date'])
    for g in grouped.values():
        g['dates']=sorted(set(g['dates']));g['conflicted']=len(g['dates'])>1
        g['counted_as_tests']=1 if g['identity_explicit'] and not g['conflicted'] and not g['date_unknown'] else None
    return list(grouped.values())
