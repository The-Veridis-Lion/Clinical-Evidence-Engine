"""Frozen original sources -> cached extraction -> both request workflows."""
import json

import pytest

from clinical_intelligence.careflow.cli import main
from clinical_intelligence.careflow.evaluation.corpus import freeze_corpus
from clinical_intelligence.careflow.extraction import run_development
from clinical_intelligence.careflow.scheduler import CallLedger
from test_careflow_extraction import Provider


def prepared(tmp_path):
    records = []
    for patient in ('PAT-A', 'PAT-B', 'PAT-C'):
        for kind in ('note', 'dialogue'):
            records.append({'document_id': patient + '-' + kind, 'case_group': patient,
                'dataset': 'fixture', 'input_kind': kind, 'text': patient + ' ' + kind + ': Reports cough.',
                'reference_origin': 'constructed_mechanical_test',
                'reference': {'private_reference_marker': 'MUST-NOT-ENTER-MODEL-INPUT'}})
    frozen, extracted, ledger = tmp_path / 'frozen', tmp_path / 'extracted', tmp_path / 'calls.sqlite'
    freeze_corpus(records, frozen, development_groups=2, holdout_groups=1, source_metadata={'dataset': 'fixture'})
    provider = Provider()
    provider.preflight = lambda: None
    result = run_development(frozen, extracted, ledger, groups=2, provider=provider)
    assert len(result['successes']) == 4
    return frozen, extracted, ledger, provider


def test_cli_replays_distinct_patients_sources_and_requests_without_inference(tmp_path, capsys):
    frozen, extracted, ledger, provider = prepared(tmp_path)
    db, output = tmp_path / 'product.sqlite', tmp_path / 'packets'
    assert main(['--db', str(db), 'replay-extraction', '--frozen', str(frozen), '--extraction', str(extracted),
                 '--ledger', str(ledger), '--received-at', '2026-10-13', '--output', str(output)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert len(receipt['cases']) == 4 and receipt['new_model_calls'] == 0
    assert {r['request_type'] for r in receipt['cases']} == {'referral', 'prior_authorization'}
    assert all(r['readiness'] == 'NEEDS_EVIDENCE' and r['audit_verified'] and r['source_bundle_validation'] for r in receipt['cases'])
    assert len({json.loads(p.read_text())['request']['patient_id'] for p in output.glob('*-input.json')}) == 2
    assert provider.calls == 4 and CallLedger(ledger).stats()['attempts'] == 4


def test_replay_corrupt_cache_does_not_create_product_or_resample(tmp_path, capsys):
    frozen, extracted, ledger, provider = prepared(tmp_path)
    path = next((extracted / 'cache').rglob('result.json'))
    value = json.loads(path.read_text())
    value['extraction']['facts'][0]['concept'] = 'invented'
    path.write_text(json.dumps(value))
    db = tmp_path / 'rejected.sqlite'
    assert main(['--db', str(db), 'replay-extraction', '--frozen', str(frozen), '--extraction', str(extracted),
                 '--ledger', str(ledger), '--received-at', '2026-10-13', '--output', str(tmp_path / 'packets')]) == 1
    assert not db.exists() and provider.calls == 4


def test_cohort_count_cannot_silently_shrink(tmp_path):
    frozen, extracted, ledger, provider = prepared(tmp_path)
    with pytest.raises(ValueError, match='group count'):
        run_development(frozen, tmp_path / 'too-large', ledger, groups=3, provider=provider)
    assert provider.calls == 4
