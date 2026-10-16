"""Invalid source scope must fail before files, reservation, or dispatch."""
import json
import pytest
from clinical_intelligence.careflow.source_demo import source_intake
from clinical_intelligence.careflow.raw_input import build_case
from clinical_intelligence.careflow import source_workflow


@pytest.mark.parametrize('invalid', ['patient', 'encounter', 'receipt_date'])
def test_scope_rejection_precedes_any_model_reservation(tmp_path, monkeypatch, invalid):
    intake = source_intake('referral', patient='DATASET:SCOPE-GROUP', case_id='scope-preflight')
    intake['request']['encounter_id'] = 'SCOPE-GROUP'
    if invalid == 'encounter':
        intake['request']['encounter_id'] = 'UNRELATED-ENCOUNTER'
    case, _ = build_case(**{k:v for k,v in intake.items() if k != 'schema_version'})
    record = {'document_id':'scope-source', 'case_group':'UNRELATED-PATIENT' if invalid=='patient' else 'SCOPE-GROUP',
              'dataset':'authored_synthetic', 'text':'Patient reports cough.', 'input_kind':'note'}
    inputs = {'document.json':record, 'case.json':case.model_dump(mode='json'),
              'attachments.json':[{'binding_id':'scope-binding', 'binding_source_id':'scope-attachment',
                                   'requirement':'referral_reason', 'fact_indices':[0]}]}
    for name, value in inputs.items():
        (tmp_path/name).write_text(json.dumps(value), encoding='utf-8')
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid scope reached the extractor')
    monkeypatch.setattr(source_workflow, 'extract_document', forbidden)
    with pytest.raises(ValueError, match='receipt date' if invalid=='receipt_date' else 'does not match'):
        source_workflow.run_source_workflow(tmp_path/'cases.sqlite3', tmp_path/'output',
            tmp_path/'document.json', tmp_path/'case.json', tmp_path/'attachments.json',
            tmp_path/'cache', tmp_path/'ledger.sqlite3',
            received_at='not-a-date' if invalid=='receipt_date' else '2026-10-13')
    assert not (tmp_path/'output').exists()
    assert not (tmp_path/'ledger.sqlite3').exists()
    assert not (tmp_path/'cases.sqlite3').exists()
