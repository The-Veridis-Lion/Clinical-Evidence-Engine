"""Actual dispatcher contract with offline fakes; no clinical scoring resampling."""
import json

import pytest

from clinical_intelligence.careflow.extraction import extract_document
from clinical_intelligence.careflow.scheduler import CallLedger
from clinical_intelligence.dialogue_first.dataset import source_index


def record():
    return {'document_id': 'SOURCE-NOTE', 'case_group': 'GROUP-A', 'dataset': 'fixture', 'input_kind': 'note',
            'text': 'The patient reports cough.', 'reference': {'private_reference_marker': 'MUST-NOT-ENTER-MODEL-INPUT'}}


def proposal(document, *, wrong_source=False, changed=False, invalid_relation=False):
    source = source_index(document)['source_catalogue'][0]['source_id']
    fact = {'category': 'symptom', 'concept': 'different concept' if changed else 'cough', 'polarity': 'present',
            'temporality': 'current', 'experiencer': 'patient', 'attributes': None,
            'assertion_basis': 'patient_report', 'attribution_confidence': 'context_supported',
            'clinical_status': 'reported symptom', 'evidence': {'source_ids': ['invalid'] if wrong_source else [source]}}
    relationship = {'from_fact_index': 0, 'to_fact_index': 99, 'relation': 'reported', 'evidence': {'source_ids': [source]}}
    return json.dumps({'document_id': document.document_id, 'facts': [fact],
                       'relationships': [relationship] if invalid_relation else []})


class Provider:
    def __init__(self, mode='valid'):
        self.calls, self.mode = 0, mode
    def dispatch(self, document, folder):
        self.calls += 1
        assert 'MUST-NOT-ENTER-MODEL-INPUT' not in (folder / 'prompt.txt').read_text(encoding='utf-8')
        if self.mode == 'change_valid_on_repair':
            return proposal(document, invalid_relation=self.calls == 1, changed=self.calls > 1), None
        return proposal(document, wrong_source=self.mode == 'repair' and self.calls == 1), None


def test_valid_extraction_is_cached_even_if_reference_changes(tmp_path):
    provider = Provider()
    ledger = CallLedger(tmp_path / 'calls.sqlite')
    before = extract_document(record(), tmp_path / 'cache', ledger, provider=provider)
    changed = record()
    changed['reference'] = {'different_expected_answer': 'must not trigger resampling'}
    after = extract_document(changed, tmp_path / 'cache', ledger, provider=provider)
    assert after == before and provider.calls == 1 and ledger.stats()['attempts'] == 1


def test_mechanical_repair_preserves_original_attempts(tmp_path):
    ledger = CallLedger(tmp_path / 'calls.sqlite')
    provider = Provider('repair')
    result = extract_document(record(), tmp_path / 'cache', ledger, provider=provider)
    assert result['attempt'] == 2 and provider.calls == 2
    assert ledger.stats()['attempts'] == 2 and ledger.stats()['failures'] == 1
    assert len(list((tmp_path / 'cache').rglob('raw-response-snapshot.json'))) == 2


def test_structural_retry_cannot_change_previously_valid_clinical_facts(tmp_path):
    ledger = CallLedger(tmp_path / 'calls.sqlite')
    with pytest.raises(ValueError):
        extract_document(record(), tmp_path / 'cache', ledger, provider=Provider('change_valid_on_repair'))
    assert not list((tmp_path / 'cache').rglob('result.json'))


@pytest.mark.parametrize('mutation', ['concept', 'quote', 'document', 'attempt'])
def test_corrupt_cache_is_rejected_without_resampling(tmp_path, mutation):
    provider = Provider()
    ledger = CallLedger(tmp_path / 'calls.sqlite')
    extract_document(record(), tmp_path / 'cache', ledger, provider=provider)
    path = next((tmp_path / 'cache').rglob('result.json'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    if mutation == 'concept':
        saved['extraction']['facts'][0]['concept'] = 'invented diagnosis'
    elif mutation == 'quote':
        saved['extraction']['facts'][0]['evidence']['quote'] = 'invented evidence'
    elif mutation == 'document':
        saved['document']['document_id'] = 'OTHER-SOURCE'
    else:
        saved['attempt'] = 3
    path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ValueError, match='[Cc]ache'):
        extract_document(record(), tmp_path / 'cache', ledger, provider=provider)
    assert provider.calls == 1 and ledger.stats()['attempts'] == 1
