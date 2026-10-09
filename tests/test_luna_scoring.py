import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from luna_experiment import fact_view
from luna_experiment import field_equal


def test_compatible_claim_splitting_preserves_facts_without_counting_extra_claim():
    base=dict(kind='service',encounter_ref='E-1',appointment_ref=None,service_date='2026-01-01',service_type='group',evidence_kind='attendance',signed=True,delivered=True,patient_present=True)
    values=fact_view([dict(base,scheduled_intervals=[dict(start=600,end=660)]),dict(base,actual_intervals=[dict(start=610,end=650)])])
    assert len(values)==1
    assert values[0]['scheduled_intervals']==[dict(start=600,end=660)]
    assert values[0]['actual_intervals']==[dict(start=610,end=650)]


def test_scoring_does_not_hide_incompatible_or_differently_bound_reports():
    base=dict(kind='service',encounter_ref='E-1',appointment_ref=None,service_date='2026-01-01',service_type='individual',evidence_kind='clinical')
    values=fact_view([dict(base,reported_minutes=40),dict(base,reported_minutes=50)])
    assert values[0]['reported_minutes']=={'conflicting_values':[40,50]}
    assert len(fact_view([base,dict(base,encounter_ref='E-2')]))==2


def test_instrument_case_is_not_a_different_measure_but_subitem_is():
    assert field_equal('PHQ-9 item 9','PHQ-9 Item 9','instrument')
    assert not field_equal('PHQ-9','PHQ-9 Item 9','instrument')


def test_private_query_oracle_requires_exact_document_group(tmp_path):
    import json
    from luna_quality import independent_scores
    fixtures=tmp_path/'tests/fixtures/luna'
    fixtures.mkdir(parents=True)
    (fixtures/'query_oracles.json').write_text(json.dumps({'samples':{}}))
    private=tmp_path/'artifacts/luna-private'
    private.mkdir(parents=True)
    truth=dict(sessions=[1,1],days=[1,1],minutes=[20,20],minute_alternatives=[20])
    (private/'query_oracles.json').write_text(json.dumps({'restricted-group':{'sample_ids':['doc-a','doc-b'],'utilization':truth}}))
    item=dict(group='restricted-group',candidate='best',repeat=1,answer={})
    rows=[dict(id='doc-a',group='restricted-group')]
    result=independent_scores(tmp_path,rows,dict(downstream=[item],results=[]))
    assert result['independent_query_scores']==[]
    rows.append(dict(id='doc-b',group='restricted-group'))
    result=independent_scores(tmp_path,rows,dict(downstream=[item],results=[]))
    assert len(result['independent_query_scores'])==1
    assert result['independent_query_scores'][0]['expected']==truth
    assert not result['independent_query_scores'][0]['correct']
