"""Offline checks of the bounded experiment, not additional model measurements."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from clinical_intelligence.claims_review.note_extractor import PROMPT, note_request
from clinical_intelligence.claims_review.note_prompt_b import PROMPT_B
from clinical_intelligence.claims_review.prepare import line_anchors
from luna_bounded_ab import fixed_plan, RoundProvider, StopRound, save, read
from score_luna_ab import score_facts


def test_plan_fixed_complete_interleaved():
    plan=fixed_plan()
    assert len(plan)==48 and plan==fixed_plan()
    assert len({i['execution_id'] for i in plan})==48
    assert sum(i['split']=='dev' for i in plan)==16
    for n in range(0,48,2):
        assert {p['candidate'] for p in plan[n:n+2]}=={'A','B'}
        assert plan[n]['case_id']==plan[n+1]['case_id']


def test_prompt_only_and_default_unchanged():
    text='HbA1c request.'
    source=dict(patient_id='SYN',source_id='NOTE',encounter_id=None,recorded_at=None,available_at=None,
                line_anchors=line_anchors('NOTE',text))
    a,sa=note_request(source,{})
    b,sb=note_request(source,{},prompt_variant='B')
    assert a.startswith(PROMPT) and b.startswith(PROMPT_B) and sa==sb
    assert a[len(PROMPT):]==b[len(PROMPT_B):]
    with pytest.raises(ValueError):note_request(source,{},prompt_variant='C')


@pytest.mark.parametrize('attempts,seconds,stop',[(96,120,'BUDGET_STOP'),(0,5,'TIMEBOX_STOP')])
def test_guard_runs_before_provider(tmp_path,attempts,seconds,stop):
    class Never:
        def structured_output(self,*a,**k):raise AssertionError('Provider must not run')
    state={'execution_deadline':(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(),'attempts':attempts,'phase':'PREDICTING'}
    adapter=RoundProvider(tmp_path,state,{'calls':[]},Never())
    with pytest.raises(StopRound):adapter.structured_output('x',{},purpose='test')
    assert read(tmp_path/'round_state.json')['phase']==stop


def test_competing_fact_cannot_be_hidden_and_wrong_event_does_not_match():
    spec={'facts':[{'proposition':'Test Oak','kind':'order_intent','identity_lines':[2],
        'statement_regex':'Oak','fields':{'target_date':['2026-08-18'],'value':[True]}}]}
    good={'kind':'order_intent','statement':'Oak test','span_ids':['N:L002'],'value':True,'target_date':'2026-08-18'}
    wrong={**good,'target_date':'2026-08-19'}
    source={'content':'Header\nOak request\nElm request'}
    score=score_facts([good,wrong],spec,source)
    assert score['metrics']['wrong_definite']==1 and not score['complete_selected_constraints']
    other={**good,'statement':'Elm test','span_ids':['N:L003']}
    score=score_facts([other],spec,source)
    assert score['metrics']['missing']==1 and score['metrics']['unscored_extras']==1


def test_no_target_does_not_accept_empty_fact_objects():
    assert score_facts([],{'facts':[],'no_target':True},{'content':'Office address'})['complete_selected_constraints']
    s=score_facts([{'kind':'purpose','statement':'Unknown','value':None,'span_ids':['N:L001']}],
        {'facts':[],'no_target':True},{'content':'Office address'})
    assert s['metrics']['unsupported_extras']==1 and not s['complete_selected_constraints']
