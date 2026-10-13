"""Reference transcription sees labels only and preserves its own raw source."""
import json

from clinical_intelligence.careflow.evaluation.public import prepare_references, reference_document
from clinical_intelligence.dialogue_first.dataset import source_index
from test_careflow_extraction import proposal


def test_reference_transcription_is_frozen_without_candidate_or_clinical_source(tmp_path):
    records = [{'document_id': 'PUBLIC-A', 'case_group': 'CASE-A', 'dataset': 'ACI-BENCH',
                'text': 'PRIVATE-CLINICAL-SOURCE-NOT-FOR-LABEL-TRANSCRIPTION',
                'reference': {'original_note': 'Patient reports cough.'}},
               {'document_id': 'PUBLIC-B', 'case_group': 'CASE-B', 'dataset': 'ACI-BENCH',
                'text': 'DIFFERENT-PRIVATE-CLINICAL-SOURCE', 'reference': {'original_note': 'History of cough.'}}]
    documents = {reference_document(r, {}).document_id: reference_document(r, {}) for r in records}
    class Provider:
        calls = 0
        def preflight(self):
            pass
        def dispatch(self, document, folder):
            self.calls += 1
            assert folder.is_absolute()
            assert (folder / 'schema.json').is_file()
            text = (folder / 'prompt.txt').read_text(encoding='utf-8')
            assert 'PRIVATE-CLINICAL-SOURCE' not in text
            assert 'candidate_prediction' not in text
            return json.dumps({'documents': [json.loads(proposal(d)) for d in documents.values()]}), None
    provider = Provider()
    result = prepare_references(records, {}, tmp_path / 'refs', tmp_path / 'calls.sqlite', provider=provider, workers=1)
    assert result['valid'] == 2 and not result['failures']
    assert result['freeze']['candidate_predictions_supplied'] is False
    assert result['calls']['research_attempts'] == 1
    again = prepare_references(records, {}, tmp_path / 'refs', tmp_path / 'calls.sqlite', provider=provider, workers=1)
    assert again == result and provider.calls == 1


def test_extra_source_assertions_are_not_automatically_correct_and_denominators_stay_fixed():
    from clinical_intelligence.careflow.evaluation.public import comparison_for, public_metrics
    from clinical_intelligence.careflow.evaluation.corpus import canonical
    from clinical_intelligence.clinical_notes.dataset import sha
    record = {'document_id': 'SOURCE-C', 'case_group': 'CASE-C', 'dataset': 'fixture', 'text': 'Pain and weakness.'}
    base = {'category': 'symptom', 'concept': 'pain', 'polarity': 'present', 'temporality': 'current',
        'experiencer': 'patient', 'attributes': None, 'assertion_basis': 'patient_report', 'clinical_status': 'reported',
        'evidence': {'start': 0, 'end': 4, 'quote': 'Pain'}, 'supporting_evidence': []}
    prediction = {'extraction': {'facts': [base, {**base, 'concept': 'weakness'}]}}
    reference = {'facts': [base]}
    comparison, refs, preds = comparison_for(record, prediction, reference)
    items = [(record, comparison, refs, preds)]
    before = public_metrics(items, [], [])
    assert before['original_frozen_reference_transcription_metrics']['precision'] == .5
    assert before['source_checked_auxiliary']['precision'] == .5
    assert before['source_checked_auxiliary']['unreviewed_predictions'] == 1
    finding = {'document_id': record['document_id'], 'kind': 'predictions', 'entity_id': preds[1]['fact_id'],
        'classification': 'REFERENCE_ERROR', 'source_supported': True, 'covered': None, 'error_fields': [],
        'comparison_sha256': sha(canonical(comparison)), 'source_sha256': sha(record['text'])}
    after = public_metrics(items, [finding], [])
    assert after['source_checked_auxiliary']['precision'] == 1
    assert after['source_checked_auxiliary']['prediction_denominator'] == 2
    assert after['source_checked_auxiliary']['reference_denominator'] == 1
    assert after['original_frozen_reference_transcription_metrics'] == before['original_frozen_reference_transcription_metrics']
    unrelated = {**finding, 'comparison_sha256': 'old-snapshot'}
    assert public_metrics(items, [unrelated], [])['source_checked_auxiliary']['precision'] == .5


def test_missing_reference_cannot_be_zero_denominator_full_recall():
    from clinical_intelligence.careflow.evaluation.public import comparison_for, public_metrics
    record = {'document_id': 'FAILED-REFERENCE', 'text': 'A documented result.'}
    comparison, refs, preds = comparison_for(record, {'extraction': {'facts': []}},
                                             {'facts': [], 'status': 'REFERENCE_FAILED'})
    metrics = public_metrics([(record, comparison, refs, preds)], [], [])
    assert metrics['source_checked_auxiliary']['recall'] is None
    assert metrics['source_checked_auxiliary']['f1'] is None
    assert metrics['original_frozen_reference_transcription_metrics']['recall'] is None
    assert metrics['known_reference_coverage_diagnostic']['missing_reference_document_denominators_are_unknown_not_zero']
    assert metrics['meets_scoped_source_targets'] is False


def test_unmatched_reference_can_cite_matching_fact_without_reauditing_it(tmp_path):
    from clinical_intelligence.careflow.evaluation.public import comparison_for, source_audit_batches
    record = {'document_id': 'MULTI-REFERENCE', 'case_group': 'CASE', 'dataset': 'fixture',
              'input_kind': 'note', 'text': 'Patient reports cough.', 'reference': {}}
    fact = {'category': 'symptom', 'concept': 'cough', 'polarity': 'present', 'temporality': 'current',
            'experiencer': 'patient', 'attributes': None, 'assertion_basis': 'patient_report',
            'clinical_status': 'reported', 'evidence': {'start': 0, 'end': 22, 'quote': record['text']}}
    comparison, refs, preds = comparison_for(record, {'extraction': {'facts': [fact]}}, {'facts': [fact, fact]})
    class Provider:
        def preflight(self):
            pass
        def dispatch(self, document, folder):
            return json.dumps({'documents': [{'document_id': record['document_id'], 'predictions': [],
                'references': [{'i': 0, 'c': 'EQUIVALENT', 's': True, 'covered': True,
                                'p': [0], 'e': [0], 'errors': [], 'reason': 'Same source-backed assertion.'}]}]}), None
    findings, failures = source_audit_batches([(record, comparison, refs, preds)], tmp_path/'audit',
                                             tmp_path/'calls.sqlite', provider=Provider())
    assert not failures and len(findings) == 1
    assert findings[0]['kind'] == 'references' and findings[0]['fact_ids'] == [preds[0]['fact_id']]
