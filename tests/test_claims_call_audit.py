"""The audit retains raw proposals and actual reported errors without rewriting."""
import json
import sys
from audit_claims_calls import main


def test_originals_errors_repair_delta_and_downstream_are_preserved(tmp_path,monkeypatch):
    inputs=tmp_path/'inputs';packets=tmp_path/'packets';traces=tmp_path/'traces'
    for folder in [inputs,packets,traces]:folder.mkdir()
    source=dict(source_kind='synthetic_note',patient_id='SYN-P',source_id='NOTE',content='A named clinical test.')
    (inputs/'CASE.json').write_text(json.dumps(dict(case_id='CASE',sources=[source])))
    packet=dict(facts=[],criteria=[{'status':'INSUFFICIENT_EVIDENCE'}],execution={'note_sources':[]},status='NEEDS_HUMAN_REVIEW')
    (packets/'CASE.json').write_text(json.dumps(packet))
    originals=[]
    for number,specific in [(1,True),(2,None)]:
        folder=traces/f'call-{number:03d}';folder.mkdir()
        raw=dict(patient_id='SYN-P',source_id='NOTE',facts=[dict(kind='order_intent',statement='A named test is ordered.',test_specific=specific)])
        (folder/'answer.json').write_text(json.dumps(raw));originals.append((folder/'answer.json').read_bytes())
        (folder/'schema.json').write_text(json.dumps({'properties':{'patient_id':{'enum':['SYN-P']},'source_id':{'enum':['NOTE']}}}))
        (folder/'prompt.txt').write_text('Source' if number==1 else 'Source\nRUNTIME VALIDATION ERRORS:\nnamed-test guard\nPREVIOUS PROPOSAL:\n{}')
    output=tmp_path/'audit.json'
    monkeypatch.setattr(sys,'argv',['audit','--inputs',str(inputs),'--packets',str(packets),'--traces',str(traces),'--output',str(output)])
    main();result=json.loads(output.read_text())['cases'][0]
    stages=result['notes'][0]['stages']
    assert stages[0]['original_visible_response']['facts'][0]['test_specific'] is True
    assert stages[1]['runtime_errors_reported_to_this_repair']=='named-test guard'
    delta=stages[1]['before_after_changes'][0]['fields']['test_specific']
    assert delta=={'before':True,'after':None}
    assert result['downstream']['criteria']==packet['criteria']
    assert originals==[(traces/f'call-{n:03d}'/'answer.json').read_bytes() for n in [1,2]]
