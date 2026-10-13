"""Reproducible real HTTP intake -> clinical binding -> packet/audit workflow."""
from pathlib import Path
from threading import Thread
from urllib.parse import quote
import http.client
import json

from .api import make_server
from .contracts import Case, EvidenceUpdate
from .evaluation.acceptance import verify_packet
from .evaluation.corpus import canonical, write_once


def run_http_workflow(database, output, case_path, update_path):
    case = Case.model_validate_json(Path(case_path).read_text(encoding='utf-8'))
    update = EvidenceUpdate.model_validate_json(Path(update_path).read_text(encoding='utf-8'))
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    server = make_server(database, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def call(method, route, value=None):
        client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=30)
        client.request(method, route, canonical(value).encode('utf-8') if value is not None else None,
                       {'Content-Type': 'application/json'} if value is not None else {})
        response = client.getresponse()
        raw, content_type, status = response.read().decode('utf-8'), response.getheader('Content-Type'), response.status
        client.close()
        parsed = raw if content_type.startswith('text/') else json.loads(raw)
        if status not in {200, 201}:
            raise ValueError(f'HTTP workflow failed: {status} {parsed}')
        return parsed
    route = '/v1/cases/' + quote(case.case_id, safe='')
    try:
        before = call('POST', '/v1/cases', case.model_dump(mode='json'))
        basis = update.review or update.intake
        if update.expected_revision != before['revision'] or basis.basis_packet_sha256 != before['packet_sha256']:
            raise ValueError('Replay update does not reference the exact initial packet')
        after = call('POST', route + '/evidence', update.model_dump(mode='json'))
        audit, report = call('GET', route + '/audit'), call('GET', route + '/report')
        historical = call('GET', route + '?revision=1')
        checks = verify_packet(after)
        if historical != before or not audit['verified'] or not all(checks['source_checks'] + checks['rule_checks']):
            raise ValueError('HTTP workflow failed historical/audit/citation verification')
        for name, value in [('before', before), ('after', after), ('audit', audit)]:
            write_once(root / (name + '.json'), (canonical(value) + '\n').encode('utf-8'))
        write_once(root / 'report.md', report.encode('utf-8'))
        receipt = {'case_id': case.case_id, 'request_type': case.request.request_type,
            'before': before['readiness'], 'after': after['readiness'], 'before_sha256': before['packet_sha256'],
            'after_sha256': after['packet_sha256'], 'audit_verified': audit['verified'],
            'source_reference_checks': len(checks['source_checks']), 'rule_reference_checks': len(checks['rule_checks']),
            'model_calls_by_this_http_replay': 0,
            'source_extraction': 'Uses supplied source-validated extraction; upstream actual attempts are in its separate ledger.'}
        write_once(root / 'receipt.json', (canonical(receipt) + '\n').encode('utf-8'))
        return receipt
    finally:
        server.shutdown(); server.server_close(); thread.join(5)
