"""Integration contracts; fake inference is explicitly separate from live evidence."""
import copy
import json
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from clinical_intelligence.copilot.models import Source
from clinical_intelligence.copilot.runtime import ProductLedger, extract_live
from clinical_intelligence.copilot.store import CaseStore
from clinical_intelligence.copilot.workbench import Workbench
from clinical_intelligence.copilot.workbench_calls import AuxiliaryCalls
from clinical_intelligence.copilot.source_adapter import source_index


def fake_extractor(calls):
    def run(case, patient, source, ledger):
        class Fake:
            def structured_output(self, prompt, schema, purpose):
                calls.append(source.document_id)
                if 'transport unknown' in source.text:
                    raise TimeoutError('Provider timeout; no replay')
                if 'mechanical failure' in source.text:
                    return '{malformed'
                refs = [s['source_id'] for s in source_index(source.document())['source_catalogue']]
                return {'document_id': source.document_id, 'facts': [{
                    'category': 'symptom', 'concept': 'cough', 'polarity': 'present', 'temporality': 'current',
                    'experiencer': 'patient', 'attributes': None, 'assertion_basis': 'patient_report',
                    'attribution_confidence': 'context_supported', 'clinical_status': None,
                    'evidence': {'source_ids': refs}}], 'relationships': []}
        return extract_live(case, patient, source, ledger, provider_factory=Fake, semantics_version=None, task_version=None)
    return run


@pytest.fixture
def bench(tmp_path):
    store, ledger = CaseStore(tmp_path/'cases.sqlite3'), ProductLedger(tmp_path/'product-calls.sqlite3')
    calls = []
    workbench = Workbench(store, ledger=ledger, live=True, extractor=fake_extractor(calls))
    workbench.create_patient({'patient_id': 'p-one', 'display_label': 'Patient one'})
    yield workbench, calls
    workbench.close()


def source(identity='a', text='Patient reports cough.', encounter='visit-one', day='2026-06-18'):
    return dict(document_id=identity, filename=identity+'.txt', text=text, input_kind='note',
                encounter_id=encounter, encounter_time=day, source_patient_id='p-one')


def settle(bench):
    end = time.monotonic()+10
    while time.monotonic() < end:
        workspace = bench.workspace('p-one')
        if all(d['status'] not in {'queued', 'processing'} for d in workspace['documents']):
            return workspace
        time.sleep(.02)
    raise AssertionError('Extraction worker did not settle')


def test_same_patient_batch_reuses_source_and_keeps_partial_failure_separate(bench):
    wb, calls = bench
    rows = [source(), source('b', 'Patient reports cough again.'),
            source('bad', 'mechanical failure'), source('unknown', 'transport unknown')]
    result = wb.upload('p-one', {'files': rows})
    assert all(r['status'] == 'queued' for r in result['files'])
    workspace = settle(wb)
    assert sorted(r['status'] for r in workspace['documents']) == ['failed', 'succeeded', 'succeeded', 'uncertain']
    assert len(workspace['encounters']) == 1 and len(calls) == 4
    repeat = wb.upload('p-one', {'files': [{**r, 'document_id': 'renamed-'+r['document_id']} for r in rows]})
    assert all(r['reused'] and r['new_model_calls'] == 0 for r in repeat['files'])
    assert len(calls) == wb.ledger.summary()['dispatch_attempts'] == 4
    assert len(wb.soap('p-one', 'visit-one')['saved_version']) == 4
    query = wb.query('p-one', {'family': 'visit_count', 'filters': {}})
    assert query['answer']['visit_count'] == 1 and query['model_calls'] == 0
    assert query['missing_data']
    assert len(calls) == 4


def test_concurrent_duplicate_upload_only_ever_dispatches_once(bench):
    wb, calls = bench
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: wb.upload('p-one', {'files': [source()]}), range(6)))
    settle(wb)
    assert sum(not r['files'][0].get('reused', False) for r in results) == 1
    assert len(calls) == 1


def test_identity_conflict_and_rebinding_do_not_spend_model_calls(bench):
    wb, calls = bench
    bad = [source(text='Patient ID: p-two\nPatient reports cough.'),
           {**source('b'), 'source_patient_id': 'p-two'},
           {**source('c'), 'text': 'binary\x00'}, {**source('d'), 'encounter_id': None}]
    assert all(r['status'] == 'rejected' for r in wb.upload('p-one', {'files': bad})['files'])
    assert calls == []
    wb.upload('p-one', {'files': [source()]})
    settle(wb)
    result = wb.upload('p-one', {'files': [source(encounter='wrong')]})
    assert result['files'][0]['status'] == 'rejected' and len(calls) == 1
    wb.create_patient({'patient_id': 'p-two', 'display_label': 'Same name is not identity'})
    with pytest.raises(KeyError):
        wb.evidence('p-two', wb.workspace('p-one')['documents'][0]['case_id'])


def test_unknown_membership_is_not_a_visit_and_correction_updates_current_only(bench):
    wb, calls = bench
    wb.upload('p-one', {'files': [source(), source('b', 'Patient reports cough later.', None, None)]})
    workspace = settle(wb)
    assert len(workspace['encounters']) == 1
    selected = workspace['documents'][0]['case_id']
    old = wb.store.get(selected)
    item = old.facts[0]
    replacement = item.assertion.model_dump()
    replacement['concept'] = 'reported cough'
    result = wb.correct('p-one', selected, item.fact_id, {
        'base_version': 1, 'action': 'correct', 'reason': 'Retain reported wording',
        'evidence_ids': item.evidence_ids, 'replacement': replacement,
        'reviewer': {'reviewer_id': 'user', 'reviewer_type': 'human', 'version': 'test'}})
    assert result['packet']['version'] == 2 and result['model_calls'] == 0
    assert wb.store.get(selected, 1).content_hash == old.content_hash
    assert wb.workspace('p-one')['evidence_version'] != workspace['evidence_version']
    assert wb.soap('p-one', 'visit-one')['saved_version'][0]['version'] == 2
    assert len(calls) == 2


def test_restart_never_redispatches_unknown_attempt(bench):
    wb, calls = bench
    wb.upload('p-one', {'files': [source(text='transport unknown')]})
    settle(wb)
    wb.close()
    reopened = Workbench(wb.store, ledger=wb.ledger, live=True, extractor=fake_extractor(calls))
    try:
        assert reopened.workspace('p-one')['documents'][0]['status'] == 'uncertain'
        reopened.upload('p-one', {'files': [source(text='transport unknown')]})
        assert len(calls) == 1
    finally:
        reopened.close()


def test_existing_ordinary_saved_source_is_reused_without_model_call(bench):
    wb, calls = bench
    src = Source.create('original-source-id', 'Patient reports cough.', 'note', encounter_time='2026-06-18')
    packet = fake_extractor(calls)('ordinary-case', 'p-one', src, wb.ledger)
    wb.store.save(packet, expected_version=0)
    wb.live = False  # Reading a saved result does not require the provider.
    result = wb.upload('p-one', {'files': [source('renamed')]})['files'][0]
    assert result['reused'] and result['case_id'] == 'ordinary-case'
    assert result['document_id'] == 'original-source-id' and len(calls) == 1


def test_lost_careflow_create_response_retains_ownership_and_recovers_by_read(bench):
    wb, _ = bench
    wb.upload('p-one', {'files': [source()]}); settle(wb)
    original = {'case_id':'cf-one','request':{'patient_id':'p-one'},'materials':[]}
    remote, creates = {}, []
    def cf(path, body=None):
        if path == '/v1/shared-intake':
            creates.append(body)
            remote.update(body)
            raise ValueError('HTTP response lost after remote commit')
        if path.endswith('/audit'):
            return {'events':[{'event_type':'SHARED_EVIDENCE_IMPORTED','payload':{'sources':remote['sources']}}]}
        return {'case_id':'cf-one','request':remote['request'],'revision':1,'packet_sha256':'saved'}
    wb._cf = cf
    with pytest.raises(ValueError, match='response lost'):
        wb.cf_create('p-one', original)
    binding = wb.cf_requests('p-one')['requests'][0]
    assert binding['status'] == 'uncertain' and binding['case_id'] == 'cf-one'
    recovered = wb.cf_create('p-one', original)
    assert recovered['recovered'] and len(creates) == 1
    assert wb.cf_requests('p-one')['requests'][0]['status'] == 'current'


def test_careflow_transport_timeout_is_bounded_error_not_lost_fact_save(bench, monkeypatch):
    wb, _ = bench
    wb.careflow_url='http://127.0.0.1:9999'
    def timeout(*args, **kwargs):
        raise TimeoutError('socket timed out')
    monkeypatch.setattr('clinical_intelligence.copilot.workbench.urlopen', timeout)
    with pytest.raises(ValueError, match='saved clinical facts remain intact'):
        wb._cf('/v1/config')


def test_auxiliary_contract_preflight_and_success_dedup_and_unknown_budget(tmp_path):
    from clinical_intelligence.copilot.patient_queries import interpretation_schema, validate_interpretation
    calls = []
    class Fake:
        def structured_output(self, prompt, schema, purpose):
            calls.append(purpose)
            if prompt == 'uncertain':
                raise TimeoutError('transport unknown')
            return {'status': 'ready', 'query_spec': {'family': 'visit_count', 'filters': {
                'start': None, 'end': None, 'concept': None, 'experiencer': None, 'service_type': None}},
                'clarification_question': None, 'explanation': None}
    ledger = AuxiliaryCalls(tmp_path/'cases.sqlite3', Fake)
    value, receipt = ledger.run('p', 'r1', 'query_interpretation', 'question', interpretation_schema(), validate_interpretation)
    cached, cached_receipt = ledger.run('p', 'r2', 'query_interpretation', 'question', interpretation_schema(), validate_interpretation)
    assert cached == value and receipt['new_model_calls'] == 1 and cached_receipt['new_model_calls'] == 0
    with pytest.raises(ValueError, match='uncertain'):
        ledger.run('p', 'r3', 'query_interpretation', 'uncertain', interpretation_schema(), validate_interpretation)
    with pytest.raises(ValueError, match='no automatic retry'):
        ledger.run('p', 'r4', 'query_interpretation', 'uncertain', interpretation_schema(), validate_interpretation)
    assert len(calls) == 2
    with pytest.raises(ValueError):
        ledger.run('p', 'r5', 'query_interpretation', 'new', {'type': 'object'}, validate_interpretation)
    assert len(calls) == 2


def test_workbench_http_uses_normal_security_and_patient_owner_checks(tmp_path):
    from clinical_intelligence.copilot.server import make_server
    calls=[]
    server=make_server(CaseStore(tmp_path/'cases.sqlite3'), port=0, live=True,
        ledger=ProductLedger(tmp_path/'product-calls.sqlite3'), workbench_extractor=fake_extractor(calls))
    thread=threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    def request(path, body=None, token=None):
        headers={'Content-Type':'application/json'}
        if token: headers['X-Copilot-Token']=token
        with urlopen(Request(base+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)) as result:
            return json.load(result)
    try:
        token=request('/api/config')['csrf_token']
        with pytest.raises(HTTPError) as exc:
            request('/ui/patients', {'patient_id':'p-one','display_label':'One'})
        assert exc.value.code == 403
        request('/ui/patients', {'patient_id':'p-one','display_label':'One'}, token)
        request('/ui/patients/p-one/files', {'files':[source()]}, token)
        settle(server.workbench)
        answer=request('/ui/patients/p-one/queries', {'family':'visit_count'}, token)
        assert answer['answer']['visit_count']==1 and len(calls)==1
        assert request('/ui/patients/p-one/encounters/visit-one/soap')['scope']=='selected_encounter'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
