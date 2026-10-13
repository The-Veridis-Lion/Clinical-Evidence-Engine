"""Real local HTTP lifecycle and CLI, with no external service dependencies."""
import http.client
import json
import subprocess
import sys
from threading import Thread
from urllib.parse import quote

import pytest

from clinical_intelligence.careflow.api import make_server, MAX_BODY_BYTES
from clinical_intelligence.careflow.demo import referral_case, supplemental
from clinical_intelligence.careflow.report import markdown
from clinical_intelligence.careflow.contracts import Case
from clinical_intelligence.careflow.engine import evaluate


@pytest.fixture
def api(tmp_path):
    server = make_server(tmp_path / 'api.sqlite', port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def call(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, payload, headers or ({'Content-Type': 'application/json'} if body is not None else {}))
        response = conn.getresponse()
        raw = response.read().decode('utf-8')
        status, content_type = response.status, response.getheader('Content-Type')
        conn.close()
        return status, raw if content_type.startswith('text/') else json.loads(raw)
    yield call
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.mark.parametrize('kind,patient', [('referral', 'HTTP-PAT-1'), ('prior_authorization', 'HTTP-PAT-2')])
def test_http_complete_workflow(api, kind, patient):
    assert api('GET', '/health')[0] == 200
    assert len(api('GET', '/v1/rules')[1]) == 2
    assert 'case' in api('GET', '/v1/schemas')[1]
    raw = referral_case(patient=patient, request='HTTP-REQ', case_id='HTTP-CASE/中文', request_type=kind)
    status, before = api('POST', '/v1/cases', raw)
    assert status == 201 and before['readiness'] == 'NEEDS_EVIDENCE'
    route = '/v1/cases/' + quote(raw['case_id'], safe='')
    assert api('POST', '/v1/cases', raw)[0] == 409
    assert api('GET', route)[1] == before
    assert api('GET', route + '/review-input')[1]['model_calls'] == 0
    review = {'reviewer_id': 'http-ai', 'reviewer_type': 'advanced_ai', 'model': 'offline-json', 'model_version': '1',
              'basis_revision': 1, 'basis_packet_sha256': before['packet_sha256'], 'fact_ids': [],
              'judgment': 'AGREE', 'reason': 'Missing summary confirmed; rules remain unchanged.'}
    assert api('POST', route + '/reviews', review)[0] == 201
    assert api('GET', route)[1] == before
    extra = supplemental('clinical_summary', True, 'Request-specific new summary.', patient=patient, request='HTTP-REQ')
    update = {'expected_revision': 1, 'review': review, **extra}
    status, after = api('POST', route + '/evidence', update)
    assert status == 201 and after['readiness'] == 'DOCUMENTATION_READY'
    assert api('POST', route + '/evidence', update)[0] == 409
    assert api('GET', route + '?revision=1')[1] == before
    assert api('GET', route + '/audit')[1]['verified']
    assert len(api('GET', route + '/reviews')[1]) == 2
    status, report = api('GET', route + '/report')
    assert status == 200 and after['packet_sha256'] in report
    for check in after['checks']:
        assert check['rule_id'] in report and check['status'] in report
    assert 'http-ai' in report and 'offline-json' in report
    assert api('GET', route + '/model-calls')[1]['product_model_calls'] == 0


def test_api_rejects_rule_override_malformed_review_and_large_body(api):
    raw = referral_case()
    raw['request']['ruleset_version'] = 'not-installed'
    assert api('POST', '/v1/cases', raw)[0] == 400
    assert api('GET', '/v1/cases/CF-REF-001')[0] == 404
    raw['request']['ruleset_version'] = '1.0.0'
    packet = api('POST', '/v1/cases', raw)[1]
    assert api('POST', '/v1/cases/CF-REF-001/reviews', {'readiness': 'DOCUMENTATION_READY'})[0] == 422
    assert api('GET', '/v1/cases/CF-REF-001?revision=-1')[0] == 400
    assert api('GET', '/v1/cases/CF-REF-001?revision=3')[0] == 404
    assert api('POST', '/v1/cases', {}, {'Content-Type': 'text/plain'})[0] == 400
    assert api('POST', '/v1/cases', {'padding': 'x' * MAX_BODY_BYTES})[0] == 413
    assert api('GET', '/v1/cases/CF-REF-001')[1] == packet


@pytest.mark.parametrize('kind', ['referral', 'prior_authorization'])
def test_http_clinical_context_is_reviewable_and_does_not_fill_material_gap(api, kind):
    from test_careflow_clinical_context import clinical_case
    raw = clinical_case(kind, patient='HTTP-CONTEXT-' + kind)
    status, packet = api('POST', '/v1/cases', raw)
    assert status == 201 and packet['readiness'] == 'NEEDS_EVIDENCE'
    identifier = packet['clinical_context'][0]['facts'][0]['context_fact_id']
    route = '/v1/cases/' + quote(raw['case_id'], safe='')
    review = {'reviewer_id': 'source-reviewer', 'reviewer_type': 'advanced_ai', 'model': 'offline-fixture', 'model_version': '1',
        'basis_revision': 1, 'basis_packet_sha256': packet['packet_sha256'], 'fact_ids': [identifier],
        'judgment': 'ESCALATE', 'reason': 'Clinical context exists; request summary material remains missing.'}
    assert api('POST', route + '/reviews', review)[0] == 201
    assert api('GET', route)[1] == packet
    assert identifier in api('GET', route + '/report')[1]
    assert api('GET', route + '/audit')[1]['verified']


def test_report_preserves_unicode_offsets_raw_fields_and_excluded_evidence():
    raw = referral_case(patient='患者-报告', request='请求-报告')
    extra = supplemental('clinical_summary', True, '原文：```<script>内容|断言</script>。\n第二行。',
                         patient='患者-报告', request='请求-报告')
    raw['sources'] += extra['sources']
    raw['facts'] += extra['facts']
    packet = evaluate(Case.model_validate_json(json.dumps(raw)))
    report = markdown(packet)
    cited = packet['facts'][-1]['citations'][0]
    assert cited['quote'] == extra['sources'][0]['content'][:cited['end']]
    assert cited['quote'] in report
    assert packet['packet_sha256'] in report and packet['ruleset']['sha256'] in report
    assert '````' in report  # Evidence cannot terminate its literal fence.


def test_cli_demo_persists_both_request_types_and_refuses_overwrite(tmp_path):
    root = tmp_path / 'output'
    db = tmp_path / 'demo.sqlite'
    cmd = [sys.executable, '-m', 'clinical_intelligence.careflow', '--db', str(db), 'demo', '--output', str(root)]
    first = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    assert len(summary) == 2 and all(s['after'] == 'DOCUMENTATION_READY' and s['audit_verified'] for s in summary)
    assert all(s['model_calls']['research_model_calls'] == 0 for s in summary)
    before_report = (root / 'referral-report.md').read_bytes()
    second = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    assert second.returncode == 1 and 'Case already exists' in second.stderr
    assert (root / 'referral-report.md').read_bytes() == before_report
