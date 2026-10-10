"""General mechanism tests, independent of the former confirmation IDs."""
import copy
import json
from datetime import date
import pytest
from clinical_intelligence.claims_review.grounding import terminology, explicit_dates, authentication
from clinical_intelligence.claims_review.relationships import reconcile
from clinical_intelligence.claims_review.note_extractor import validate_proposal, extract_note, RuntimeValidationError
from clinical_intelligence.claims_review.review import run_review, load_policy
from clinical_intelligence.claims_review.prepare import prepare_case
from test_claims_review_integration import case, changed, source, FixtureProvider, statuses


def assertion(s,kind,value,**updates):
    anchor=s['line_anchors'][0]
    row=dict(kind=kind,value=value,statement=anchor['quote'],fact_date=None,date_role='unknown',temporal_status='actual',
             target_date=None,test_specific=None,provider=None,reporter=None,authenticated=None,span_ids=[anchor['span_id']])
    row.update(updates)
    return row


@pytest.mark.parametrize('phrase', ['HbA1c', 'Hgb A1c', 'haemoglobin A1c', 'Hemoglobin A1c', 'A1c'])
def test_exact_concepts_do_not_invent_assay_codes(phrase):
    m=terminology(phrase)['mentions'][0]
    assert m['concept']=='hba1c' and m['mapping_status']=='exact_synonym'
    assert m['original_phrase']==phrase and m['code'] is None


@pytest.mark.parametrize('phrase', ['glycated hemoglobin', 'glycosylated haemoglobin'])
def test_family_mapping_is_not_full_assay_equivalence(phrase):
    m=terminology(phrase)['mentions'][0]
    assert m['concept']=='glycated_hemoglobin' and m['mapping_status']=='contextual_family'


def test_only_explicit_verified_code_has_a_code_system():
    assert terminology('LOINC: 4548-4')['mentions'][0]['code_system']=='LOINC'
    assert terminology('LOINC: 9999-9')['status']=='unresolved'
    assert terminology('4548-4')['status']=='unresolved'


@pytest.mark.parametrize('phrase', ['fructosamine', 'glycated albumin', 'glycated protein'])
def test_other_analytes_never_gain_target_binding(phrase):
    c=changed(case(2),lambda b:b['sources'][3].update(content=f'Please order {phrase}.'))
    s=source(c);row=assertion(s,'order_intent',True,test_specific=True,span_ids=[s['line_anchors'][0]['span_id']])
    r=run_review(c,mode='fixture',provider=FixtureProvider(dict(patient_id=s['patient_id'],source_id=s['source_id'],facts=[row])))
    f=next(f for f in r.facts if f.source_id==s['source_id'])
    assert f.test_specific is True and not f.details['test_mapping_supported']
    assert statuses(r)['ORDER_INTENT']=='INSUFFICIENT_EVIDENCE'


@pytest.mark.parametrize('text', ['September 22, 2026', '22 Sep 2026', '2026/9/22', '2026-09-22'])
def test_date_grounding_preserves_source_formats(text):
    assert explicit_dates(text)[0]['date']=='2026-09-22'
    c=changed(case(2),lambda b:b['sources'][3].update(content=f'Hgb A1c requested for {text}.'))
    s=source(c);row=assertion(s,'test_mention',None,target_date='2026-09-22',span_ids=[s['line_anchors'][0]['span_id']],temporal_status='planned')
    assert validate_proposal(dict(patient_id=s['patient_id'],source_id=s['source_id'],facts=[row]),s,c.review_context.as_of)


@pytest.mark.parametrize('text', ['09/10/2026', 'September 2026', '2026-02-30'])
def test_ambiguous_partial_invalid_dates_do_not_become_known(text):
    assert explicit_dates(text)==[]


def test_negation_and_plan_do_not_produce_actual_test_events():
    c=changed(case(2),lambda b:b['sources'][3].update(content='No HbA1c was performed. An A1c next month is merely planned.'))
    s=source(c);row=assertion(s,'test_mention',None,temporal_status='planned',test_specific=True,span_ids=[s['line_anchors'][0]['span_id']])
    r=run_review(c,mode='fixture',provider=FixtureProvider(dict(patient_id=s['patient_id'],source_id=s['source_id'],facts=[row])))
    assert len([f for f in r.facts if f.kind=='test_event'])==2
    assert next(f for f in r.facts if f.source_id==s['source_id']).temporal_status=='planned'


def test_signature_declarations_remain_provider_scoped():
    assert authentication('DR. Jane  Q','Digital signature: Dr. Jane Q') is True
    assert authentication('Dr. Jane Q','Unauthenticated by Dr. Jane Q') is False
    assert authentication('Dr. Jane Q','Signed by Dr. Jane Q\nUnsigned by Dr. Other') is True
    assert authentication('Dr. Jane Q','Signed by Dr. Other') is None
    assert authentication('Dr. Jane Q','Signed by Dr. Jane Q\nNot signed by Dr. Jane Q') is None


def test_repair_cannot_silently_discard_independently_valid_facts():
    c=case(2);s=source(c)
    valid=assertion(s,'diabetes_context',True)
    bad=assertion(s,'order_intent',True,provider='Invented author')
    identity=dict(patient_id=s['patient_id'],source_id=s['source_id'])
    p=FixtureProvider({**identity,'facts':[valid,bad]},{**identity,'facts':[]})
    facts,record=extract_note(p,s,c.claim.model_dump(mode='json'),c.review_context.as_of)
    assert record['status']=='failed' and record['calls']==2
    assert any(f.kind=='diabetes_context' and f.value is True for f in facts)
    assert 'independently valid' in record['errors'][-1]


def test_repair_can_augment_citations_and_fill_unknowns():
    from clinical_intelligence.claims_review.note_extractor import preserves
    original=dict(kind='purpose',value='monitoring',target_date=None,statement='Short original phrasing',span_ids=['L1'],date_role='unknown')
    final={**original,'target_date':'2026-09-01','statement':'Equivalent longer phrasing','span_ids':['L1','L2'],'date_role':'requested_test'}
    assert preserves(original,[final])
    assert not preserves(original,[{**final,'value':None}])


def records():
    c=case(2);rows=prepare_case(c,load_policy(),input_label='fixture')['source_candidates']
    original=copy.deepcopy(next(s for s in rows if s['record_type']=='observation'))
    original['source_id']='ORIGINAL';original['event_link_id']='LAB-EVENT';original['event_date']='2026-05-01'
    correction=copy.deepcopy(original);correction['source_id']='AMENDMENT';correction['event_date']='2026-07-01'
    correction['content']['source_relationship']=dict(relation='amends',target_source_id='ORIGINAL',field='event_date',replacement='2026-07-01',authenticated=True,authority_scope='event_date')
    copyrow=copy.deepcopy(original);copyrow['source_id']='LATE-COPY';copyrow['available_at']='2026-10-01'
    copyrow['content']['retransmission_of_source_id']='ORIGINAL'
    return [original,correction,copyrow]


def test_late_copy_cannot_undo_field_amendment_and_original_is_immutable():
    rows=records();saved=copy.deepcopy(rows);out=reconcile(rows)
    assert rows==saved
    assert out['derived']['LATE-COPY']['event_date']['values']==['2026-07-01']
    assert out['derived']['ORIGINAL']['content/value']['values']==[8.1]
    assert all(r['relationship']['citations'] for r in out['relationships'])


@pytest.mark.parametrize('change', ['patient','event','target','signature','scope','replacement'])
def test_invalid_amendments_never_override_original(change):
    rows=records()[:2];r=rows[1]['content']['source_relationship']
    if change=='patient':rows[1]['patient_id']='OTHER'
    if change=='event':rows[1]['event_link_id']='OTHER'
    if change=='target':r['target_source_id']='MISSING'
    if change=='signature':r['authenticated']=None
    if change=='scope':r['authority_scope']='content/value'
    if change=='replacement':r['replacement']='2026-07-03'
    out=reconcile(rows)
    assert out['relationships'][0]['status']=='UNRESOLVED'
    assert out['derived']['ORIGINAL']['event_date']['values']==['2026-05-01']


def test_competing_amendments_and_cycles_preserve_uncertainty():
    rows=records()[:2];other=copy.deepcopy(rows[1]);other['source_id']='OTHER-AMENDMENT';other['event_date']='2026-07-02';other['content']['source_relationship']['replacement']='2026-07-02';rows.append(other)
    view=reconcile(rows)['derived']['ORIGINAL']['event_date']
    assert view['status']=='CONFLICTED' and len(view['values'])==2
    rows[0]['content']['source_relationship']=dict(relation='amends',target_source_id='AMENDMENT',field='event_date',replacement=rows[0]['event_date'],authenticated=True,authority_scope='event_date')
    assert reconcile(rows)['derived']['ORIGINAL']['event_date']['status']=='UNRESOLVED'


def test_result_only_amendment_does_not_change_date():
    rows=records()[:2];rows[1]['event_date']=rows[0]['event_date'];rows[1]['content']['value']=7.4
    rows[1]['content']['source_relationship'].update(field='content/value',replacement=7.4,authority_scope='content/value')
    out=reconcile(rows)['derived']['ORIGINAL']
    assert out['content/value']['values']==[7.4] and out['event_date']['values']==['2026-05-01']


def test_policy_dimensions_preserve_known_clinical_evidence():
    c=changed(case(1),lambda b:b['claim'].update(service_date=None));r=run_review(c)
    assert set(statuses(r).values())=={'NOT_EVALUATED'}
    assert any(f.kind=='test_event' and f.value is not None for f in r.facts)
    assert all(x.derivation['applicability']['status']=='UNRESOLVED' for x in r.criteria)
    assert any(x.derivation['clinical_evidence_status']!='NOT_EVALUATED' for x in r.criteria)


def test_nonrequired_unknowns_do_not_globally_block_policy():
    c=changed(case(1),lambda b:b['sources'][0].update(event_date=None))
    r=run_review(c)
    assert all(x.derivation['applicability']['status']=='EVALUABLE' for x in r.criteria)


def test_relationship_schema_rejects_untyped_authority():
    rows=records();rows[1]['content']['source_relationship']['authenticated']='true'
    with pytest.raises(ValueError):reconcile(rows)


def test_unknown_result_is_not_a_conflicting_known_value():
    def append_partial(b):
        original=next(s for s in b['sources'] if s['record_type']=='observation')
        partial=copy.deepcopy(original);partial['source_id']='PARTIAL-RESULT';partial['content']['value']=None
        b['sources'].append(partial)
    r=run_review(changed(case(1),append_partial))
    group=next(e for e in r.timeline if 'PARTIAL-RESULT' in e['source_ids'])
    assert group['result_unknown'] and not group['result_conflicted']
    assert any(v is not None for v in group['result_values'])
    assert group['counted_as_tests']==1
