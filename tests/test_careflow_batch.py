import json

import pytest

from clinical_intelligence.careflow.evaluation.batch import run_batch
from clinical_intelligence.careflow.extraction import extract_document
from clinical_intelligence.careflow.scheduler import CallLedger
from clinical_intelligence.dialogue_first.dataset import source_index


def records():
    return [{'document_id': f'DOC-{i}', 'case_group': f'PATIENT-{i}', 'dataset': 'fixture',
             'input_kind': 'note' if i % 2 else 'dialogue', 'text': text, 'reference': {}}
            for i, text in enumerate(['Patient reports pain.', 'Patient denies cough.',
                                      'An examination is planned.', 'The test was completed.'])]


class Provider:
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def preflight(self):
        pass

    def dispatch(self, document, folder):
        self.calls += 1
        if self.fail:
            (folder / 'usage.json').write_text(json.dumps({'input_tokens': 12, 'output_tokens': 0}))
            raise RuntimeError('Upstream transport unavailable')
        source = source_index(document)['source_catalogue'][0]['source_id']
        return json.dumps({'document_id': document.document_id, 'facts': [{
            'category': 'other', 'concept': 'documented assertion', 'polarity': 'uncertain',
            'temporality': 'unknown', 'experiencer': 'patient', 'attributes': None,
            'assertion_basis': 'unknown', 'attribution_confidence': 'uncertain',
            'clinical_status': None, 'evidence': {'source_ids': [source]}}],
            'relationships': []}), {'input_tokens': 20, 'output_tokens': 15}


def test_transport_stop_preserves_full_cohort_and_failed_usage(tmp_path):
    provider = Provider(fail=True)
    summary = run_batch(records(), tmp_path/'output', tmp_path/'cache', tmp_path/'calls.sqlite',
                        workers=1, provider=provider)
    assert summary['documents'] == 4 and summary['failed_documents'] == 4
    assert [r['status'] for r in summary['results']] == ['FAILED', 'FAILED', 'NOT_ATTEMPTED', 'NOT_ATTEMPTED']
    assert summary['halted_after_upstream_failures'] is True
    assert provider.calls == 6  # At most two additional transport retries/document.
    ledger = CallLedger(tmp_path/'calls.sqlite')
    assert ledger.stats()['unknown_usage'] == 0
    assert all(json.loads(r['usage'])['input_tokens'] == 12 for r in ledger.attempts())


@pytest.mark.parametrize('mutation', ['concept', 'polarity'])
def test_result_wrapper_cannot_replace_first_accepted_output(tmp_path, mutation):
    provider = Provider()
    options = dict(workers=1, provider=provider)
    run_batch(records(), tmp_path/'output', tmp_path/'cache', tmp_path/'calls.sqlite', **options)
    path = next((tmp_path/'output/results').glob('*.json'))
    value = json.loads(path.read_text())
    value['extraction']['facts'][0][mutation] = 'invented diagnosis' if mutation == 'concept' else 'present'
    path.write_text(json.dumps(value))
    # The immutable convenience wrapper disagrees with reconstructed model output.
    summary = run_batch(records(), tmp_path/'output', tmp_path/'cache', tmp_path/'calls.sqlite', **options)
    assert summary['valid_documents'] == 3 and summary['failed_documents'] == 1
    assert provider.calls == 4


def test_valid_sources_reused_without_semantic_resampling(tmp_path):
    provider = Provider()
    first = run_batch(records(), tmp_path/'output', tmp_path/'cache', tmp_path/'calls.sqlite', workers=2, provider=provider)
    # A distinct output run may reuse the exact original model cache.
    second = run_batch(records(), tmp_path/'replay', tmp_path/'cache', tmp_path/'calls.sqlite', workers=2, provider=provider)
    assert first['valid_documents'] == second['valid_documents'] == 4
    assert provider.calls == 4
