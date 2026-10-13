"""Frozen development cohorts, legacy cache reuse and bounded actual extraction."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from time import perf_counter, sleep
import json
import uuid

from ...clinical_notes.runner import SingleDispatchProvider
from ...provider import ProviderConfig
from ..contracts import Case
from ..extraction import extract_document, select_group_documents
from ..scheduler import CallLedger, SlotBusy
from .corpus import canonical, load_frozen, write_once
from ...clinical_notes.dataset import sha


def development_records(aci_root, acn_root):
    aci = load_frozen(aci_root, 'development')
    acn = select_group_documents(acn_root, groups=200)
    return [*sorted(aci, key=lambda r: r['document_id']), *acn]


def source_for(record, extraction, *, received_at='2026-10-13'):
    return {'source_id': record['document_id'], 'patient_id': 'DATASET:' + record['case_group'],
        'encounter_id': record['case_group'], 'available_at': received_at,
        'origin': 'public_clinical_dataset', 'source_kind': 'clinical_text', 'recorded_at': None,
        'event_date': None, 'record_type': 'note', 'event_link_id': None, 'content': record['text'],
        'availability_basis': 'export_snapshot_received', 'original_locator': {
            'dataset': record['dataset'], 'document_id': extraction['document_id'], 'input_kind': record['input_kind'],
            'original_document_id': record['document_id'], 'original_row': record.get('original_row'),
            'case_group': record['case_group'], 'source_sha256': record.get('source_sha256')}}


def validate_source_result(record, extraction):
    # Public document IDs can alias older IDs, but clinical output, offsets,
    # original provenance and document identity are preserved verbatim.
    request = {'request_id': 'VALIDATE-' + record['document_id'], 'patient_id': 'DATASET:' + record['case_group'],
        'encounter_id': record['case_group'], 'request_type': 'referral', 'service_code': 'specialty-consult',
        'code_system': 'careflow-constructed-request', 'requested_service_date': None,
        'ruleset_id': 'careflow-referral', 'ruleset_version': '1.0.0'}
    return Case.model_validate_json(canonical({'case_id': request['request_id'], 'request': request,
        'review_as_of': '2026-10-13', 'sources': [source_for(record, extraction)], 'facts': [],
        'clinical_context': [{'source_id': record['document_id'], 'extraction': extraction}]}))


def import_aci_cache(records, legacy_root, output):
    legacy_root, output = Path(legacy_root), Path(output)
    freeze = json.loads((legacy_root / 'artifacts/dialogue-first-clinical-audit-v1/freeze.json').read_text(encoding='utf-8'))
    old_inputs = json.loads((legacy_root / 'artifacts/dialogue-first-v1/inputs.json').read_text(encoding='utf-8'))
    documents = {d['encounter_id']: d for d in old_inputs}
    cached = {e['encounter_id']: e for e in freeze['encounters']}
    results = {}
    for record in records:
        group = record['case_group']
        if record['dataset'] != 'ACI-BENCH' or group not in cached:
            continue
        original = documents[group]
        if original['text'] != record['text']:
            raise ValueError('Existing ACI cache text differs from frozen original source')
        path = legacy_root / cached[group]['effective_path']
        raw = path.read_bytes()
        extraction = json.loads(raw)['extraction']
        validate_source_result(record, extraction)
        result = {'document_id': record['document_id'], 'extraction': extraction, 'status': 'VALID',
            'origin': 'existing_luna_cache', 'original_document_id': extraction['document_id'],
            'source_sha256': sha(record['text']), 'original_cache_sha256': sha(raw),
            'original_cache_path': cached[group]['effective_path'], 'new_calls': 0}
        write_once(output / (sha(record['document_id']) + '.json'), (canonical(result) + '\n').encode('utf-8'))
        results[record['document_id']] = result
    return results


def run_batch(records, output, cache, ledger_path, *, legacy_root=None, workers=25, provider=None):
    if type(workers) is not int or not 1 <= workers <= 25:
        raise ValueError('Participating CareFlow workers must be between 1 and25')
    started, root = perf_counter(), Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cohort = {'schema_version': 'careflow-public-development-cohort/3',
        'document_ids': [r['document_id'] for r in records],
        'source_hashes': {r['document_id']: sha(r['text']) for r in records},
        'reference_hashes': {r['document_id']: sha(canonical(r['reference'])) for r in records},
        'selection': 'ACI all47 dev groups; ACN200 frozen groups, identity-hashed representative full-note/dialogue',
        'model': 'gpt-6-luna', 'reasoning_effort': 'high', 'workers': workers,
        'original_references_in_extraction_input': False}
    write_once(root / 'cohort.json', (canonical(cohort) + '\n').encode('utf-8'))
    reused = import_aci_cache(records, legacy_root, root / 'results') if legacy_root else {}
    ledger = CallLedger(ledger_path)
    provider = provider or SingleDispatchProvider(ProviderConfig(model='gpt-6-luna', reasoning_effort='high', timeout_seconds=300))
    provider.preflight()

    def execute(record):
        identifier = record['document_id']
        if identifier in reused:
            return reused[identifier]
        result_file = root / 'results' / (sha(identifier) + '.json')
        # Reconstruct the first accepted output from its raw responses/ledger,
        # even when a convenience result wrapper already exists.
        while True:
            try:
                result = extract_document(record, cache, ledger, provider=provider)
                break
            except SlotBusy:
                sleep(0.2)  # Waiting reserves no attempt and dispatches no model.
        validate_source_result(record, result['extraction'])
        payload = {'document_id': identifier, 'extraction': result['extraction'], 'status': 'VALID',
                   'origin': 'frozen_source_only_luna', 'identity': result['identity'], 'attempt': result['attempt'],
                   'source_sha256': sha(record['text']), 'usage': result['usage']}
        write_once(result_file, (canonical(payload) + '\n').encode('utf-8'))
        return payload

    rows, consecutive_upstream_failures, halted = [], 0, False
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = iter(records)
        futures = {}
        def submit_next():
            record = next(pending, None)
            if record is not None:
                futures[pool.submit(execute, record)] = record['document_id']
        for _ in range(workers):
            submit_next()
        while futures:
            completed, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in completed:
                identifier = futures.pop(future)
                try:
                    result = future.result()
                    row = {'document_id': identifier, 'status': 'VALID', 'facts': len(result['extraction']['facts']),
                           'origin': result['origin']}
                    consecutive_upstream_failures = 0
                except Exception as exc:
                    row = {'document_id': identifier, 'status': 'FAILED', 'error_type': type(exc).__name__, 'error': str(exc)}
                    write_once(root / 'failures' / (sha(identifier) + '.json'), (canonical(row) + '\n').encode('utf-8'))
                    if isinstance(exc, RuntimeError):
                        consecutive_upstream_failures += 1
                        halted |= consecutive_upstream_failures >= 2
                rows.append(row)
                print(json.dumps({'completed': len(rows), 'total': len(records), **row}, ensure_ascii=True), flush=True)
            if not halted:
                for _ in completed:
                    submit_next()
        # A stopped transport cannot turn unattempted documents into successes
        # or silently remove them from the frozen cohort denominator.
        for record in pending:
            rows.append({'document_id': record['document_id'], 'status': 'NOT_ATTEMPTED',
                         'error': 'Batch stopped after two consecutive upstream document failures'})
    summary = {'cohort': cohort, 'documents': len(records), 'results': sorted(rows, key=lambda r: r['document_id']),
        'valid_documents': sum(r['status'] == 'VALID' for r in rows),
        'failed_documents': sum(r['status'] != 'VALID' for r in rows),
        'reused_legacy_documents': len(reused), 'elapsed_seconds': perf_counter() - started,
        'halted_after_upstream_failures': halted,
        'call_statistics': ledger.stats(), 'semantic_scoring': 'Separate frozen reference/source review; structural validity is not semantic correctness.'}
    encoded = (canonical(summary) + '\n').encode('utf-8')
    write_once(root / 'runs' / (str(uuid.uuid4()) + '.json'), encoded)
    if not (root / 'batch-summary.json').exists():
        write_once(root / 'batch-summary.json', encoded)
    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('aci', 'acn', 'output', 'cache', 'ledger'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--legacy-root')
    parser.add_argument('--workers', type=int, default=10)
    args = parser.parse_args()
    result = run_batch(development_records(args.aci, args.acn), args.output, args.cache, args.ledger,
                       legacy_root=args.legacy_root, workers=args.workers)
    print(canonical({key: result[key] for key in ('documents', 'valid_documents', 'failed_documents',
                      'halted_after_upstream_failures', 'elapsed_seconds', 'call_statistics')}))
