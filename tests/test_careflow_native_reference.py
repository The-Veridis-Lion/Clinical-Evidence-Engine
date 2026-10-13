import json

import pytest

from clinical_intelligence.careflow.evaluation.native_reference import native_units, freeze_native, native_comparison
from clinical_intelligence.careflow.evaluation.public import expand_compact, public_metrics


@pytest.mark.parametrize('group,value', [('P-A','Completed therapy'), ('P-B','A test was planned')])
def test_native_fields_preserve_context_placeholders_and_original_values(tmp_path, group, value):
    record = {'document_id': group, 'case_group': group, 'dataset': 'ACN',
              'reference': {'original_summary': {'treatments': [{'name': value, 'dose': 'None'}],
                           'history': {'smoking': None}}, 'reference_error': None}}
    result = native_units(record)
    assert len(result['facts']) == 1 and len(result['nonassertions']) == 2
    assert result['facts'][0]['original_label_evidence']['raw_value'] == value
    assert result['facts'][0]['context'] == {'name': value, 'dose': 'None'}
    assert result['complete_clinical_gold'] is False
    frozen = freeze_native([record], tmp_path/'refs')
    assert freeze_native([record], tmp_path/'refs') == frozen
    changed = {**record, 'reference': {**record['reference'], 'original_summary': {'corrected': 'new gold'}}}
    with pytest.raises(ValueError, match='Frozen artifact differs'):
        freeze_native([changed], tmp_path/'refs')


def test_malformed_native_label_retains_failed_document_and_unknown_recall():
    record = {'document_id': 'BAD-LABEL', 'case_group': 'P', 'dataset': 'ACN', 'text': 'Clinical source.',
              'reference': {'original_summary': None, 'reference_error': 'invalid_original_summary_json'}}
    result = native_units(record)
    assert result['status'] == 'REFERENCE_FAILED' and not result['complete_clinical_gold']
    comparison, refs, preds = native_comparison(record, None, result)
    metrics = public_metrics([(record, comparison, refs, preds)], [], [])
    assert metrics['documents'] == metrics['reference_transcription_failed_documents'] == 1
    assert metrics['source_checked_auxiliary']['recall'] is None
    assert metrics['meets_scoped_source_targets'] is False


def test_compact_reviews_keep_all_semantic_fields_and_identity():
    # CLASSES alphabetical: BOTH_WRONG,EQUIVALENT,MODEL_ERROR,REFERENCE_ERROR,UNRESOLVED.
    row = {'documents': [{'document_id': 'D', 'predictions': [[4,2,False,None,[],[3],[3,4],'unit/subject mismatch']],
                          'references': [[2,1,True,True,[4],[3],[],'source assertion covered']]}]}
    result = expand_compact(row)['documents'][0]
    assert result['predictions'][0]['i'] == 4
    assert result['predictions'][0]['c'] == 'MODEL_ERROR'
    assert result['predictions'][0]['errors'] == ['unit','subject']
    assert result['references'][0]['p'] == [4]
    with pytest.raises(ValueError):
        expand_compact({'documents':[{'document_id':'D','predictions':[[0,99]],'references':[]}]})
