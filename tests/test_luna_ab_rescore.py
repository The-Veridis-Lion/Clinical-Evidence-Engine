"""Ten preregistered offline mechanism groups; no model/service requests."""
import copy
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from luna_ab_rescore import numeric_projection,field_status,frame,score_output,coherent_ambiguous_date,match_identity,run,read,save,digest


@pytest.fixture
def source():
    lines=['Patient has established diabetes.',
           'Historical HbA1c result 6.7 percent collected February 12, 2026.',
           'The courier receipt does not indicate a new blood draw.',
           'Change has not been implemented; a future discussion is planned.',
           'North: HbA1c requested August 18, 2026.',
           'South: HbA1c requested August 20, 2026.']
    anchors=[];start=0
    for n,line in enumerate(lines,1):
        anchors.append({'span_id':f'N:L{n:03d}','quote':line,'start':start,'end':start+len(line)});start+=len(line)+1
    return {'patient_id':'P','source_id':'N','content':'\n'.join(lines),'line_anchors':anchors}


def result_fact(**updates):
    f={'kind':'test_mention','statement':'Historical HbA1c result is 6.7 percent.',
       'value':6.7,'fact_date':'2026-02-12','date_role':'actual_test','temporal_status':'historical','span_ids':['N:L002']}
    f.update(updates);return f
def result_spec(**updates):
    s={'constraint_id':'S:result','proposition':'Historical test','kind':'test_mention','frame':'test_result','identity_lines':[2],
       'numeric_value':True,'bare_numeric_allowed':True,'fields':{'value':[6.7],'fact_date':['2026-02-12'],'date_role':['actual_test'],'temporal_status':['historical']}}
    s.update(updates);return s


# 1: numeric equality requires compatible encoding/concept/unit and polarity.
@pytest.mark.parametrize('value',[6.7,'6.7 percent','HbA1c result: 6.7 percent','Hgb A1c 6.70%'])
def test_1_equivalent_values(value):assert field_status(value,[6.7],numeric=True,bare_allowed=True)[0]=='CORRECT'
@pytest.mark.parametrize('value',[7.6,'6.7 mg/dL','thyroid 6.7 percent','not 6.7 percent','<6.7 percent','other patient HbA1c 6.7 percent',True])
def test_1_real_errors(value):assert field_status(value,[6.7],numeric=True,bare_allowed=True)[0]!='CORRECT'
def test_1_missing_unit_and_multiple_numbers_unresolved():
    assert field_status('6.7',[6.7],numeric=True)[0]=='UNRESOLVED'
    assert numeric_projection('HbA1c 6.7 and 7.1 percent')['status']=='UNRESOLVED'


# 2: ambiguous fields do not license contradictory date bundles.
def test_2_dates(source):
    spec={'ambiguous_date':'2026-08-18'}
    assert coherent_ambiguous_date({'date_role':'order_issued','fact_date':'2026-08-18','target_date':None},spec)=='COHERENT_ORDER_DATE'
    assert coherent_ambiguous_date({'date_role':'requested_test','fact_date':None,'target_date':'2026-08-18'},spec)=='COHERENT_REQUESTED_DATE'
    assert coherent_ambiguous_date({'date_role':'order_issued','fact_date':'2026-08-18','target_date':'2026-08-18'},spec)=='INCOHERENT_ROLE_BUNDLE'
    e={'facts':[result_spec()]}
    assert score_output([result_fact(date_role='requested_test')],source,e)['metrics']['wrong_definite']==1


# 3: values absent, null, false and numeric zero remain distinct.
def test_3_distinct_values():
    assert field_status(None,[None])[0]=='CORRECT'
    assert field_status(False,[None])[0]=='WRONG_DEFINITE'
    assert field_status(False,[0])[0]=='WRONG_DEFINITE'
    assert field_status(0,[False])[0]=='WRONG_DEFINITE'
    assert field_status('__FIELD_MISSING__',[None])[0]=='MISSING'


# 4: one source line supports different propositions, never a duplicate by span.
def test_4_current_negative_and_future_discussion(source):
    spec={'constraint_id':'implementation','proposition':'Current change','kind':'regimen_change','frame':'regimen_state','identity_lines':[4],'fields':{'value':[False],'temporal_status':['actual']}}
    now={'kind':'regimen_change','statement':'The change has not been implemented.','value':False,'temporal_status':'actual','span_ids':['N:L004']}
    future={'kind':'regimen_change','statement':'A future discussion is planned.','value':None,'temporal_status':'planned','span_ids':['N:L004']}
    score=score_output([now,future],source,{'facts':[spec]})
    assert score['metrics']['correct_fields']==2 and score['metrics']['duplicate_propositions']==0
    assert score['extras'][0]['category']=='SUPPORTED_IN_SCOPE'
    assert score_output([{**now,'temporal_status':'planned'}],source,{'facts':[spec]})['metrics']['binding_errors']==1


# 5: historical result and receipt/nonperformance remain distinct after context.
def test_5_receipt_is_not_result(source):
    receipt={'kind':'test_mention','statement':'The courier receipt does not indicate a new blood draw.','value':None,'span_ids':['N:L003','N:L002']}
    score=score_output([result_fact(),receipt],source,{'facts':[result_spec()]})
    assert score['metrics']['wrong_definite']==0 and score['metrics']['duplicate_propositions']==0
    assert score['extras'][0]['category']=='SUPPORTED_IN_SCOPE'
    assert not score_output([result_fact(value=7.6),receipt],source,{'facts':[result_spec()]})['complete_common_scored_constraints']


# 6: identity is stable under order, relevant added context and paraphrase.
def test_6_context_order_and_quotes(source):
    a=result_fact();b=result_fact(statement='Earlier HbA1c result was 6.7 percent.',span_ids=['N:L001','N:L002'])
    e={'facts':[result_spec()]}
    assert score_output([a],source,e)['metrics']==score_output([b],source,e)['metrics']
    assert score_output([result_fact(span_ids=['N:L999'])],source,e)['metrics']['grounding_identity_errors']==1
    assert score_output([result_fact(span_ids=['N:L003'])],source,e)['metrics']['missing_propositions']==1


# 7: same number does not establish patient/source/event identity.
def test_7_wrong_identity(source):
    e={'facts':[result_spec()]}
    for updates in [{'patient_id':'OTHER'},{'source_id':'OTHER'},{'statement':'Another patient had HbA1c result 6.7 percent.'}]:
        s=score_output([result_fact(**updates)],source,e)
        assert s['metrics']['correct_fields']==0
    event={'kind':'order_intent','statement':'South requests HbA1c.','value':True,'span_ids':['N:L006']}
    north={'constraint_id':'north','proposition':'North request','kind':'order_intent','frame':'order_intent','identity_lines':[5],'event_label':'North','competing_labels':['South'],'event_primary_lines':[5],'competing_event_lines':[6],'fields':{'value':[True]}}
    assert match_identity(event,north,source)[0]=='NO_MATCH'
    ambiguous={**event,'statement':'HbA1c requested.','span_ids':['N:L005','N:L006']}
    assert match_identity(ambiguous,north,source)[0]=='MATCH_UNRESOLVED'


# 8: a correct object cannot hide an incorrect one; fields cannot be stitched.
def test_8_duplicates_and_no_stitching(source):
    e={'facts':[result_spec()]}
    s=score_output([result_fact(),result_fact(value=7.6)],source,e)
    assert s['metrics']['contradictory_propositions']==1 and not s['complete_common_scored_constraints']
    partial1=result_fact(value=None);partial2=result_fact(fact_date=None)
    s=score_output([partial1,partial2],source,e)
    assert s['metrics']['correct_fields']==2 and not s['complete_common_scored_constraints']


# 9: scope deviations are distinct from fabricated definite findings.
def test_9_extras(source):
    unknown={'kind':'diabetes_context','statement':'No diagnosis is documented.','value':None,'span_ids':['N:L001']}
    control={'facts':[],'no_target':True}
    assert score_output([],source,control)['complete_common_scored_constraints']
    assert score_output([unknown],source,control)['extras'][0]['category']=='SUPPORTED_OUT_OF_SCOPE'
    assert score_output([{**unknown,'value':True}],source,control)['extras'][0]['category']=='UNSUPPORTED'
    scope=score_output([{'kind':'test_mention','statement':'Potassium result is discussed.','value':None,'span_ids':['N:L002']}],source,{'facts':[]})
    assert scope['extras'][0]['category']=='UNSUPPORTED'
    potassium='Potassium result discussed.'
    extended={**source,'line_anchors':source['line_anchors']+[{'span_id':'N:L007','quote':potassium,'start':len(source['content'])+1,'end':len(source['content'])+1+len(potassium)}],'content':source['content']+'\n'+potassium}
    extra={'kind':'test_mention','statement':potassium,'value':None,'span_ids':['N:L007']}
    assert score_output([extra],extended,{'facts':[]})['extras'][0]['category']=='SUPPORTED_OUT_OF_SCOPE'


# 10: candidate/repeat/order are not scorer inputs; related unresolved cells only.
def test_10_labels_and_unresolved(source):
    spec=result_spec(unresolved_fields={'fact_date':'AMBIGUOUS_SOURCE'})
    e={'facts':[spec]};facts=[result_fact(),{'kind':'test_mention','statement':'Courier receipt is not a new test.','value':None,'span_ids':['N:L003']}]
    a=score_output(facts,source,e);b=score_output(list(reversed(facts)),source,e)
    assert a['metrics']==b['metrics']
    assert a['metrics']['candidate_fields']==4 and a['metrics']['scored_fields']==3 and a['metrics']['unresolved_fields']==1
    c=score_output([result_fact(value=7.6)],source,e)
    assert c['metrics']['wrong_definite']==1


def test_offline_no_provider_entry(source,monkeypatch):
    # Any actual provider/service invocation is an immediate test failure.
    from clinical_intelligence.provider import CodexCLIProvider
    monkeypatch.setattr(CodexCLIProvider,'structured_output',lambda *a,**k:pytest.fail('Forbidden provider call'))
    monkeypatch.setattr(CodexCLIProvider,'run_cli',lambda *a,**k:pytest.fail('Forbidden CLI process'))
    assert score_output([result_fact()],source,{'facts':[result_spec()]})['metrics']['correct_fields']==4


def test_offline_full_entry_and_metadata_invariance(source,monkeypatch,tmp_path,capsys):
    from clinical_intelligence.provider import CodexCLIProvider
    monkeypatch.setattr(CodexCLIProvider,'structured_output',lambda *a,**k:pytest.fail('Forbidden provider call'))
    monkeypatch.setattr(CodexCLIProvider,'run_cli',lambda *a,**k:pytest.fail('Forbidden CLI process'))
    original=tmp_path/'historical';out=tmp_path/'rescore';original.mkdir();out.mkdir()
    deadline=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()
    save(out/'rescore_state.json',{'work_deadline':deadline,'max_new_provider_calls':0,'new_provider_calls':0,'full_rescore_passes':0,'max_full_rescore_passes':2})
    expected={'facts':[result_spec()],'source_sha256':digest(source)}
    save(out/'expected_review_overlay.json',{'cases':{'CASE':expected}});(out/'evaluation_contract_v2.md').write_text('Test-only contract')
    entries=[]
    for n,c in enumerate(['A','B'],1):
        entries.append({'execution':{'execution_id':f'test-{c}','case_id':'CASE','split':'dev','candidate':c,'repeat':1,'calls':[n]},
            'source':source,'stages':[{'call':n,'raw_response':{'patient_id':'P','source_id':'N','facts':[result_fact()]},'runtime_validation_error':None}],
            'packet':{'facts':[result_fact()],'criteria':[]},'score':{}})
        save(original/'calls'/f'call-{n:03d}'/'usage.json',{'call_metrics':[{'tokens':{'input_tokens':1,'output_tokens':1}}]})
    save(original/'call-audit.json',{'executions':entries});run(original,out)
    first=read(out/'pass-01/scores.json')
    for e in entries:e['execution']['candidate']='B' if e['execution']['candidate']=='A' else 'A';e['execution']['repeat']=2
    save(original/'call-audit.json',{'executions':list(reversed(entries))});run(original,out)
    second=read(out/'pass-02/scores.json')
    assert first['groups']==second['groups']
    assert first['new_model_calls']==second['new_model_calls']==0
    assert first['historical_unique_requests']==second['historical_unique_requests']==2
