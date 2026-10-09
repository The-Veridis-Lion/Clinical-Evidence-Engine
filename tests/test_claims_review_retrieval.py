"""Synthetic mechanism fixtures; not original-data benchmark results."""
import csv
import io
import json
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch
import pytest
from clinical_intelligence.claims_review.retrieval import retrieve, RetrievalQuery, records
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.review import run_review
from clinical_intelligence.claims_review import cli

def query():
    q=json.loads((Path(__file__).resolve().parents[1]/'examples/claims_review/raw/target-query.json').read_text(encoding='utf-8'))
    q['claim']['patient_id']='P';q['claim']['encounter_id']='E';q['review_context']['history_start']='2026-01-01'
    return RetrievalQuery.model_validate_json(json.dumps(q))

def archive(path, rows):
    tables={'observations.csv':rows,'conditions.csv':[],'medications.csv':[],
            'procedures.csv':[dict(PATIENT='P',ENCOUNTER='E',START='2026-06-01',CODE='43396009')],
            'encounters.csv':[dict(Id='E',PATIENT='P',START='2026-06-01')],
            'claims.csv':[dict(Id='CLAIM',PATIENTID='P',APPOINTMENTID='E',CURRENTILLNESSDATE='2026-06-01')]}
    with zipfile.ZipFile(path,'w') as z:
        for name,data in tables.items():
            text=io.StringIO(newline='');w=csv.DictWriter(text,fieldnames=list(data[0]) if data else ['PATIENT','CODE','START'])
            w.writeheader();w.writerows(data);z.writestr(name,text.getvalue())
    return path

def obs(**updates):
    return dict(PATIENT='P',ENCOUNTER='E',DATE='2026-06-01',CODE='4548-4',VALUE='0',**updates)

def test_patient_code_scope_no_date_or_encounter_merge(tmp_path):
    a=archive(tmp_path/'raw.zip',[obs(),{**obs(),'PATIENT':'OTHER'},{**obs(),'CODE':'OTHER'},obs()])
    r=retrieve(a,query(),snapshot_available_at=date(2026,10,9))
    assert 'SYNTHEA-OBSERVATIONS-2' not in r['matched_source_ids'] and 'SYNTHEA-OBSERVATIONS-3' not in r['matched_source_ids']
    packet=run_review(CaseInput.model_validate_json(json.dumps(r['case'])))
    assert len(packet.timeline)==2 and all(e['counted_as_tests'] is None for e in packet.timeline)
    assert all(c['counted_as_test'] is False for c in r['linked_records'])
    assert [f.value for f in packet.facts if f.kind=='test_event']==['0','0']

@pytest.mark.parametrize('available',[None,'2026-10-10'])
def test_unknown_and_later_availability_are_distinct_and_excluded(tmp_path,available):
    a=archive(tmp_path/'raw.zip',[obs()]);r=retrieve(a,query(),metadata={
        'SYNTHEA-OBSERVATIONS-1':{'patient_id':'P','available_at':available,'evidence':'Synthetic mechanism metadata, not original CSV availability.'}})
    assert 'SYNTHEA-OBSERVATIONS-1' not in r['matched_source_ids']
    reasons=[x['reason'] for x in r['excluded_sources'] if x['source_id']=='SYNTHEA-OBSERVATIONS-1']
    assert ('availability_unknown' if available is None else 'not_available_as_of') in reasons

def test_explicit_link_duplicate_and_window_conflict_preserved(tmp_path):
    a=archive(tmp_path/'raw.zip',[{**obs(),'DATE':'2025-12-01'},obs()])
    metadata={f'SYNTHEA-OBSERVATIONS-{i}':{'patient_id':'P','event_link_id':'EXPLICIT-EVENT','evidence':'Fixture shared accession.'} for i in [1,2]}
    r=retrieve(a,query(),snapshot_available_at=date(2026,10,9),metadata=metadata)
    packet=run_review(CaseInput.model_validate_json(json.dumps(r['case'])))
    assert packet.timeline[0]['dates']==['2025-12-01','2026-06-01'] and packet.timeline[0]['conflicted']
    assert packet.timeline[0]['counted_as_tests'] is None
    a=archive(tmp_path/'same.zip',[obs(),obs()]);r=retrieve(a,query(),snapshot_available_at=date(2026,10,9),metadata=metadata)
    packet=run_review(CaseInput.model_validate_json(json.dumps(r['case'])))
    assert len(packet.timeline)==1 and packet.timeline[0]['counted_as_tests']==1

def test_missing_target_not_created_by_request(tmp_path):
    r=retrieve(archive(tmp_path/'raw.zip',[obs()]),query(),snapshot_available_at=date(2026,10,9))
    p=run_review(CaseInput.model_validate_json(json.dumps(r['case'])))
    assert p.status=='NEEDS_HUMAN_REVIEW' and all(f.fact_date!=p.target.service_date for f in p.facts if f.kind=='test_event')

def test_original_multiline_row_locator_and_fields():
    raw=b'PATIENT,DESCRIPTION\r\nP,"first\nsecond"\r\n'
    n,row,start,end,sha=list(records(raw))[0]
    assert row['DESCRIPTION']=='first\nsecond' and (start,end)==(2,3)

def test_metadata_cannot_assign_other_patient_or_unknown_row(tmp_path):
    a=archive(tmp_path/'raw.zip',[obs()])
    with pytest.raises(ValueError,match='matching patient'):
        retrieve(a,query(),metadata={'SYNTHEA-OBSERVATIONS-1':{'patient_id':'OTHER','evidence':'wrong'}})
    with pytest.raises(ValueError,match='not discovered'):
        retrieve(a,query(),metadata={'MISSING':{'patient_id':'P','evidence':'missing'}})

def test_offline_retrieval_cli_and_archive_protection(tmp_path):
    a=archive(tmp_path/'raw.zip',[obs()]);before=a.read_bytes();q=tmp_path/'query.json';q.write_text(query().model_dump_json(),encoding='utf-8')
    output=tmp_path/'retrieval.json'
    with patch.object(cli,'live_provider',side_effect=AssertionError('offline provider')):
        assert cli.main(['retrieve','--archive',str(a),'--query',str(q),'--snapshot-available-at','2026-10-09','--output',str(output)])==0
        assert cli.main(['run','--retrieval',str(output),'--output',str(tmp_path/'review.json')])==0
    assert cli.main(['download','--output',str(a)])==1 and a.read_bytes()==before

def test_changed_retrieval_case_digest_rejected(tmp_path):
    r=retrieve(archive(tmp_path/'raw.zip',[obs()]),query());r['case']['case_id']='ALTERED'
    saved=tmp_path/'r.json';saved.write_text(json.dumps(r),encoding='utf-8')
    out=tmp_path/'out.json';assert cli.main(['run','--retrieval',str(saved),'--output',str(out)])==1
    assert json.loads(out.read_text(encoding='utf-8'))['stage']=='input'


def test_summary_retains_scope_gaps_and_original_locators(tmp_path):
    from clinical_intelligence.claims_review.review import concise_markdown
    r=retrieve(archive(tmp_path/'raw.zip',[obs()]),query(),snapshot_available_at=date(2026,10,9))
    p=run_review(CaseInput.model_validate_json(json.dumps(r['case'])))
    original=p.model_dump_json();text=concise_markdown(p)
    assert 'NEEDS_HUMAN_REVIEW' in text and 'no approval' in text
    assert 'human/clinical review: false' in text and 'real calls: 0' in text
    assert 'SYNTHEA-OBSERVATIONS-1' in text and 'observations.csv data row 1' in text
    assert 'INSUFFICIENT_EVIDENCE' in text and p.model_dump_json()==original


def test_invalid_event_date_is_unknown_not_request_or_receipt(tmp_path):
    r=retrieve(archive(tmp_path/'raw.zip',[{**obs(),'DATE':'2026-06-01Tnot-a-time'}]),query(),snapshot_available_at=date(2026,10,9))
    p=run_review(CaseInput.model_validate_json(json.dumps(r['case'])))
    fact=next(f for f in p.facts if f.kind=='test_event')
    assert fact.fact_date is None and fact.value=='0'
    assert p.timeline[0]['counted_as_tests'] is None


def test_empty_relevant_history_is_not_missing_target_proof(tmp_path):
    r=retrieve(archive(tmp_path/'raw.zip',[{**obs(),'PATIENT':'OTHER'}]),query(),snapshot_available_at=date(2026,10,9))
    p=run_review(CaseInput.model_validate_json(json.dumps(r['case'])))
    assert not p.timeline and not any(f.kind=='test_event' for f in p.facts)
    assert p.status=='NEEDS_HUMAN_REVIEW' and all(not c.evidence_complete for c in p.criteria)


def test_citation_audit_rejects_equal_value_from_wrong_source(tmp_path):
    from audit_claims_packet import audit
    r=retrieve(archive(tmp_path/'raw.zip',[obs(),obs()]),query(),snapshot_available_at=date(2026,10,9))
    case=CaseInput.model_validate_json(json.dumps(r['case']));packet=run_review(case)
    assert audit(case,packet)['passed']
    first=next(f for f in packet.facts if f.kind=='test_event')
    ref=next(c for c in first.citations if c.locator.endswith('/content/VALUE'))
    ref.locator=ref.locator.replace('/sources/0/','/sources/1/')
    result=audit(case,packet)
    assert not result['passed'] and result['semantic_citation_precision'] is None
