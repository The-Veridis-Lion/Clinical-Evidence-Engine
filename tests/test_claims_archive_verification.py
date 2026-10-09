"""Independent tamper mechanisms; no reserved confirmation input or gold."""
import json
from datetime import date
from unittest.mock import patch
import pytest
from test_claims_review_retrieval import archive, obs, query
from clinical_intelligence.claims_review.retrieval import retrieve
from clinical_intelligence.claims_review.archive_verification import verify_archive
from clinical_intelligence.claims_review.prepare import digest
from clinical_intelligence.claims_review import cli


def snapshot(tmp_path):
    path = archive(tmp_path/'original.zip', [obs()])
    return path, retrieve(path, query(), snapshot_available_at=date(2026,10,9))


def test_original_rows_reverified_and_lightweight_replay_is_labelled(tmp_path):
    path, body = snapshot(tmp_path)
    result = verify_archive(body, path)
    assert result['original_archive_reverified'] and result['verified_source_count'] == len(body['case']['sources'])
    assert not result['availability_and_event_link_metadata_verified']
    saved=tmp_path/'saved.json';saved.write_text(json.dumps(body),encoding='utf-8')
    for verified in [False, True]:
        out=tmp_path/f'{verified}.json'
        args=['run','--retrieval',str(saved),'--output',str(out)]
        if verified:args+=['--verify-archive',str(path)]
        assert cli.main(args)==0
        assert json.loads(out.read_text(encoding='utf-8'))['execution']['archive_verification']['original_archive_reverified'] is verified


@pytest.mark.parametrize('field', ['content','member_sha','row_sha','row_number','physical_line','patient','encounter','event_date'])
def test_recomputed_internal_digest_cannot_attest_original_rows(tmp_path, field):
    path, body=snapshot(tmp_path);s=body['case']['sources'][0];loc=s['original_locator']
    if field=='content':s['content']['VALUE']='95.9'
    elif field=='member_sha':body['archive']['members'][0]['sha256']='0'*64
    elif field=='row_sha':loc['original_row_sha256']='0'*64
    elif field=='row_number':loc['data_record_number']=9999
    elif field=='physical_line':loc['physical_line_start']=999
    elif field=='patient':s['patient_id']='OTHER'
    elif field=='encounter':s['encounter_id']='OTHER'
    else:s['event_date']='2026-06-02'
    body['case_sha256']=digest(body['case'])
    saved=tmp_path/'tampered.json';saved.write_text(json.dumps(body),encoding='utf-8');out=tmp_path/'out.json'
    with patch.object(cli,'live_provider',side_effect=AssertionError('Cannot call model before archive verification')):
        assert cli.main(['run','--retrieval',str(saved),'--verify-archive',str(path),'--mode','live','--output',str(out)])==1
    assert json.loads(out.read_text(encoding='utf-8'))['stage']=='archive_verification'


def test_wrong_missing_archive_and_wrong_source_member_rejected(tmp_path):
    path,body=snapshot(tmp_path)
    with pytest.raises(ValueError,match='unavailable'):verify_archive(body,tmp_path/'missing.zip')
    other=archive(tmp_path/'other.zip',[{**obs(),'VALUE':'77'}])
    with pytest.raises(ValueError,match='archive SHA'):verify_archive(body,other)
    body['case']['sources'][0]['original_locator']['source_file']='conditions.csv'
    with pytest.raises(ValueError):verify_archive(body,path)


def test_case_mode_and_overwriting_archive_rejected(tmp_path):
    path,body=snapshot(tmp_path);saved=tmp_path/'case.json';saved.write_text(json.dumps(body['case']),encoding='utf-8')
    assert cli.main(['run','--case',str(saved),'--verify-archive',str(path),'--output',str(tmp_path/'out.json')])==1
    before=path.read_bytes()
    assert cli.main(['run','--retrieval',str(saved),'--verify-archive',str(path),'--output',str(path)])==1
    assert path.read_bytes()==before
