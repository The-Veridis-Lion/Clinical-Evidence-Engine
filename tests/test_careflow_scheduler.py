"""Shared interprocess limits and retry identity, without real model dispatch."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from clinical_intelligence.careflow.scheduler import CallLedger, SlotBusy


def test_global_and_per_project_limits_across_connections(tmp_path):
    path = tmp_path / 'shared.sqlite'
    a = CallLedger(path, global_limit=4, project_limit=2)
    b = CallLedger(path, global_limit=4, project_limit=2)
    a.reserve('run', 'careflow', 'd1', 'gpt-6-luna', 'product_extraction', payload_sha256='1')
    b.reserve('run', 'careflow', 'd2', 'gpt-6-luna', 'product_extraction', payload_sha256='2')
    with pytest.raises(SlotBusy):
        a.reserve('run', 'careflow', 'd3', 'gpt-6-luna', 'product_extraction', payload_sha256='3')
    b.reserve('run', 'copilot', 'd4', 'gpt-6-luna', 'product_extraction', payload_sha256='4')
    b.reserve('run', 'copilot', 'd5', 'gpt-6-luna', 'product_extraction', payload_sha256='5')
    with pytest.raises(SlotBusy):
        a.reserve('run', 'third-project', 'd6', 'gpt-6-luna', 'product_extraction', payload_sha256='6')
    assert a.stats()['reserved'] == 4


@pytest.mark.parametrize('status', ['UPSTREAM_FAILURE', 'PARSE_FAILURE', 'MECHANICAL_FAILURE'])
def test_two_extra_retries_only_for_allowed_failures_and_all_attempts_kept(tmp_path, status):
    ledger = CallLedger(tmp_path / 'calls.sqlite')
    for attempt in (1, 2, 3):
        token = ledger.reserve('run', 'careflow', 'document', 'gpt-6-luna', 'product_extraction',
                               payload_sha256=f'request-{attempt}')
        assert token['attempt'] == attempt
        ledger.finish(token, status, error='observed failure', usage=None)
    with pytest.raises(ValueError, match='retry'):
        ledger.reserve('run', 'careflow', 'document', 'gpt-6-luna', 'product_extraction', payload_sha256='fourth')
    assert ledger.stats()['attempts'] == 3 and ledger.stats()['failures'] == 3 and ledger.stats()['retries'] == 2
    assert len(ledger.attempts()) == 3


@pytest.mark.parametrize('status', ['SUCCESS', 'SEMANTIC_DISAGREEMENT', 'UNRESOLVED_DISPATCH'])
def test_semantic_disagreement_success_and_uncertain_dispatch_never_resample(tmp_path, status):
    ledger = CallLedger(tmp_path / 'calls.sqlite')
    token = ledger.reserve('run', 'careflow', 'document', 'gpt-6-luna', 'product_extraction', payload_sha256='one')
    ledger.finish(token, status, usage=None)
    with pytest.raises(ValueError, match='retry'):
        ledger.reserve('run', 'careflow', 'document', 'gpt-6-luna', 'product_extraction', payload_sha256='two')


def test_same_document_cannot_be_dispatched_concurrently_or_replayed(tmp_path):
    ledger = CallLedger(tmp_path / 'calls.sqlite', global_limit=2, project_limit=2)
    def attempt():
        try:
            return ledger.reserve('run', 'careflow', 'one-document', 'gpt-6-luna', 'product_extraction', payload_sha256='same')['attempt']
        except ValueError:
            return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results, key=str) == [1, 'BLOCKED']
    assert ledger.stats()['attempts'] == 1
