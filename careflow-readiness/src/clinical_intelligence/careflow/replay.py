"""Replay validated public clinical extractions into reviewable request cases."""
from collections import defaultdict
from pathlib import Path
import json

from .contracts import Case
from .evaluation.acceptance import verify_packet
from .evaluation.corpus import canonical, load_frozen, write_once
from .extraction import source_contract, validate_cached
from .clinical_context import sha
from .report import markdown
from .scheduler import CallLedger
from .service import CareFlow


def replay_development(frozen_root, extraction_root, ledger_path, database, output, *, received_at):
    """No inference or artificial documentation facts; absent caches stay absent.

    Dataset case identities are grouped as synthetic product patients, never
    inferred to represent insured people or real referral/PA requests.
    """
    frozen_root, extraction_root, output = Path(frozen_root), Path(extraction_root), Path(output)
    cohort = json.loads((extraction_root / 'cohort.json').read_text(encoding='utf-8'))
    manifest = json.loads((frozen_root / 'manifest.json').read_text(encoding='utf-8'))
    if (cohort['partition'] != 'development'
            or cohort['source_corpus_manifest_sha256'] != manifest['manifest_sha256']
            or len(cohort['document_ids']) != len(set(cohort['document_ids']))):
        raise ValueError('Replay cohort differs from frozen development sources')
    records = {r['document_id']: r for r in load_frozen(frozen_root, 'development')}
    ledger = CallLedger(ledger_path)
    grouped = defaultdict(list)
    for identifier in cohort['document_ids']:
        if identifier not in records:
            raise ValueError('Replay document is outside the frozen development partition')
        record = records[identifier]
        document, _, _, identity = source_contract(record)
        result = validate_cached(extraction_root / 'cache' / sha(canonical(identity)), document, identity, ledger)
        grouped[record['case_group']].append((record, result))
    if not grouped:
        raise ValueError('Empty replay cohort')
    # Validate all caches before creating anything. A corrupt cache cannot produce
    # half a successful product receipt or cause a replacement model attempt.
    cases = []
    for group, pairs in sorted(grouped.items()):
        patient_id = 'PUBLIC-CASE-' + sha(group)[:24]
        sources, context = [], []
        for record, result in pairs:
            identifier = record['document_id']
            sources.append({'source_id': identifier, 'patient_id': patient_id, 'encounter_id': group,
                'available_at': received_at, 'origin': 'public_clinical_dataset', 'source_kind': 'clinical_text',
                'recorded_at': None, 'event_date': None, 'record_type': 'note', 'event_link_id': None,
                'content': record['text'], 'availability_basis': 'export_snapshot_received',
                'original_locator': {'dataset': record['dataset'], 'document_id': identifier,
                    'input_kind': record['input_kind'], 'original_row': record.get('original_row'),
                    'source_sha256': record.get('source_sha256'), 'case_group': group}})
            context.append({'source_id': identifier, 'extraction': result['extraction']})
        for kind in ('referral', 'prior_authorization'):
            case_id = 'CF-PUBLIC-' + sha(canonical([manifest['manifest_sha256'], group, kind]))[:24]
            request = {'request_id': 'REQUEST-' + case_id, 'patient_id': patient_id, 'encounter_id': group,
                'request_type': kind, 'service_code': 'specialty-consult', 'code_system': 'careflow-constructed-request',
                'requested_service_date': received_at, 'ruleset_id': 'careflow-referral' if kind == 'referral' else 'careflow-pa',
                'ruleset_version': '1.0.0'}
            cases.append(Case.model_validate_json(canonical({'case_id': case_id, 'request': request,
                'review_as_of': received_at, 'sources': sources, 'facts': [], 'clinical_context': context})))
    output.mkdir(parents=True, exist_ok=False)
    app, rows = CareFlow(database), []
    for case in cases:
        packet = app.create(case)
        verified = verify_packet(packet)
        write_once(output / f'{case.case_id}.json', (canonical(packet) + '\n').encode('utf-8'))
        write_once(output / f'{case.case_id}.md', markdown(packet).encode('utf-8'))
        write_once(output / f'{case.case_id}-input.json', (canonical(case.model_dump(mode='json')) + '\n').encode('utf-8'))
        rows.append({'case_id': case.case_id, 'request_type': case.request.request_type,
            'clinical_facts': sum(len(c['facts']) for c in packet['clinical_context']),
            'readiness': packet['readiness'], 'packet_sha256': packet['packet_sha256'],
            'source_bundle_validation': all(verified['source_checks']), 'rule_validation': all(verified['rule_checks']),
            'audit_verified': app.audit(case.case_id)['verified']})
    receipt = {'schema_version': 'careflow-public-context-replay/2', 'cohort': cohort, 'cases': rows,
        'new_model_calls': 0, 'source_checked_precision': None, 'source_checked_recall': None,
        'boundary': 'Constructed requests and source-grounded clinical context. No PA approval gold or semantic accuracy claim.'}
    write_once(output / 'replay-receipt.json', (canonical(receipt) + '\n').encode('utf-8'))
    return receipt
