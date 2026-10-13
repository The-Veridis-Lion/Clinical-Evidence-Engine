"""Source-only product extraction using the frozen engine prompt and validator."""
from dataclasses import asdict
import json
from pathlib import Path

from ..clinical_notes.runner import SingleDispatchProvider
from ..clinical_notes.dataset import sha
from ..dialogue_first.dataset import Document
from ..dialogue_first.contract import inspect, inspect_repair, schema
from ..dialogue_first.prompt import prompt, repair_prompt
from ..provider import ProviderConfig
from .evaluation.corpus import canonical, load_frozen, write_once
from .scheduler import CallLedger


def source_contract(record):
    document = Document(record['document_id'], record['case_group'], record['dataset'], record['text'],
                        sha(record['text']), record.get('source_sha256', sha(record['text'])),
                        record.get('original_row', 0), input_kind='dialogue' if record['input_kind'] == 'dialogue' else 'note')
    initial_prompt, shape = prompt(document), schema(document)
    identity = {'document_id': document.document_id, 'source_sha256': sha(document.text),
                'prompt_sha256': sha(initial_prompt), 'schema_sha256': sha(canonical(shape)),
                'model': 'gpt-6-luna', 'reasoning_effort': 'high'}
    return document, initial_prompt, shape, identity


def validate_cached(root, document, identity, ledger):
    """Reconstruct the accepted first output, including repair preservation checks.

    Corruption is a local integrity error, never authorization for inference.
    Original snapshots and call records remain the evidence of what was accepted.
    """
    root = Path(root)
    try:
        result = json.loads((root / 'result.json').read_text(encoding='utf-8'))
        expected_document = {k: v for k, v in asdict(document).items() if k != 'text'}
        if (result['identity'] != identity or result['document'] != expected_document
                or result['status'] != 'VALID' or result['source_only'] is not True
                or type(result['attempt']) is not int or not 1 <= result['attempt'] <= 3):
            raise ValueError('Cache source/model/attempt identity differs')
        fingerprint = sha(canonical(identity))
        calls = [r for r in ledger.attempts() if r['run_id'] == fingerprint and r['project'] == 'careflow'
                 and r['document_id'] == document.document_id and r['model'] == identity['model']
                 and r['purpose'] == 'product_extraction']
        accepted = next((r for r in calls if r['attempt'] == result['attempt'] and r['status'] == 'SUCCESS'), None)
        if accepted is None or json.loads(accepted['usage']) != result['usage']:
            raise ValueError('Cache has no corresponding successful ledger attempt')
        base_raw, base_outcome = None, None
        for number in range(1, result['attempt'] + 1):
            folder = root / f'attempt-{number}'
            response = folder / 'raw-response-snapshot.json'
            if not response.exists():
                if number == result['attempt']:
                    raise ValueError('Cache accepted response is missing')
                continue  # Upstream failure has no response to reconstruct.
            raw = response.read_text(encoding='utf-8')
            outcome = inspect_repair(raw, base_raw, base_outcome, document) if base_raw is not None else inspect(raw, document)
            if outcome['status'] == 'VALID':
                if number != result['attempt'] or canonical(outcome['result']) != canonical(result['extraction']):
                    raise ValueError('Cache differs from first mechanically accepted original output')
                return result
            if outcome['result'] is not None:
                base_raw, base_outcome = raw, outcome
        raise ValueError('Cache accepted output no longer validates')
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Cache evidence is incomplete or invalid') from exc


def extract_document(record, cache_root, ledger, *, provider=None):
    """Cache identity uses only source, prompt, schema and requested model settings.

    References are never serialized into the request directory. A valid first
    extraction is final; semantic scores cannot authorize another attempt.
    """
    document, initial_prompt, shape, identity = source_contract(record)
    fingerprint = sha(canonical(identity))
    root = Path(cache_root).resolve() / fingerprint
    root.mkdir(parents=True, exist_ok=True)
    write_once(root / 'identity.json', (canonical(identity) + '\n').encode('utf-8'))
    result_path = root / 'result.json'
    if result_path.exists():
        return validate_cached(root, document, identity, ledger)
    provider = provider or SingleDispatchProvider(ProviderConfig(model='gpt-6-luna', reasoning_effort='high', timeout_seconds=300))
    previous = None
    raw_response = None
    repair_base_raw, repair_base_outcome = None, None
    for _ in range(3):
        text = initial_prompt if previous is None else repair_prompt(document, repair_base_raw or raw_response or '', previous['errors'])
        token = ledger.reserve(fingerprint, 'careflow', document.document_id, 'gpt-6-luna', 'product_extraction',
                               payload_sha256=sha(text))
        folder = root / f"attempt-{token['attempt']}"
        folder.mkdir(exist_ok=False)
        write_once(folder / 'schema.json', (canonical(shape) + '\n').encode('utf-8'))
        write_once(folder / 'prompt.txt', text.encode('utf-8'))
        usage = None
        try:
            raw_response, usage = provider.dispatch(document, folder)
        except Exception as exc:
            # Provider timeout has uncertain delivery; never blindly replay it.
            if (folder / 'usage.json').exists():
                usage = json.loads((folder / 'usage.json').read_text(encoding='utf-8'))
            status = 'UNRESOLVED_DISPATCH' if 'timeout' in str(exc).casefold() else 'UPSTREAM_FAILURE'
            ledger.finish(token, status, error=f'{type(exc).__name__}: {exc}', usage=usage)
            write_once(folder / 'failure.json', (canonical({'status': status, 'error_type': type(exc).__name__,
                                                           'error': str(exc), 'usage': usage}) + '\n').encode('utf-8'))
            if status == 'UNRESOLVED_DISPATCH' or token['attempt'] == 3:
                raise
            previous = None
            continue
        write_once(folder / 'raw-response-snapshot.json', raw_response.encode('utf-8'))
        outcome = (inspect_repair(raw_response, repair_base_raw, repair_base_outcome, document)
                   if repair_base_raw is not None else inspect(raw_response, document))
        write_once(folder / 'mechanical-outcome.json', (canonical(outcome) + '\n').encode('utf-8'))
        status = 'SUCCESS' if outcome['status'] == 'VALID' else 'MECHANICAL_FAILURE'
        ledger.finish(token, status, usage=usage, error=None if status == 'SUCCESS' else canonical(outcome['errors']))
        if status == 'SUCCESS':
            result = {'schema_version': 'careflow-source-extraction/2', 'document': {k: v for k, v in asdict(document).items() if k != 'text'},
                      'source_only': True, 'identity': identity, 'extraction': outcome['result'],
                      'status': 'VALID', 'attempt': token['attempt'], 'usage': usage,
                      'boundary': 'Mechanical source validity, not semantic accuracy or documentation satisfaction.'}
            write_once(result_path, (canonical(result) + '\n').encode('utf-8'))
            return result
        if outcome['result'] is not None:
            repair_base_raw, repair_base_outcome = raw_response, outcome
        previous = outcome
    raise ValueError('Three extraction attempts failed mechanical validation; all originals retained')


def select_group_documents(frozen_root, *, groups):
    manifest = json.loads((Path(frozen_root) / 'manifest.json').read_text(encoding='utf-8'))
    if type(groups) is not int or not 1 <= groups <= len(manifest['partitions']['development']):
        raise ValueError('Requested group count must fit the frozen development partition')
    records = {r['document_id']: r for r in load_frozen(frozen_root, 'development')}
    selected = []
    for group in manifest['partitions']['development'][:groups]:
        members = [records[identifier] for identifier in group['document_ids']]
        # Selection is by original case identity, never output quality or labels.
        representative = min({r['case_group'] for r in members}, key=lambda key: sha(group['group_id'] + ':' + key))
        for kind in ('note', 'dialogue'):
            candidates = [r for r in members if r['case_group'] == representative and r['input_kind'] == kind]
            if candidates:
                selected.append(min(candidates, key=lambda r: r['document_id']))
    return selected


def run_development(frozen_root, output, ledger_path, *, groups=1, provider=None):
    if groups < 1:
        raise ValueError('Positive pilot/cohort group count required')
    records = select_group_documents(frozen_root, groups=groups)
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cohort = {'source_corpus_manifest_sha256': json.loads((Path(frozen_root) / 'manifest.json').read_text(encoding='utf-8'))['manifest_sha256'],
              'partition': 'development', 'group_count_requested': groups,
              'document_ids': [r['document_id'] for r in records], 'selection': 'fixed group order + identity-hashed representative; full note and dialogue',
              'reference_input_to_model': False}
    write_once(root / 'cohort.json', (canonical(cohort) + '\n').encode('utf-8'))
    ledger = CallLedger(ledger_path)
    provider = provider or SingleDispatchProvider(ProviderConfig(model='gpt-6-luna', reasoning_effort='high', timeout_seconds=300))
    provider.preflight()
    successes, failures = [], []
    for record in records:
        try:
            result = extract_document(record, root / 'cache', ledger, provider=provider)
            successes.append({'document_id': record['document_id'], 'facts': len(result['extraction']['facts']),
                              'status': result['status'], 'attempt': result['attempt']})
        except Exception as exc:
            failures.append({'document_id': record['document_id'], 'error_type': type(exc).__name__, 'error': str(exc)})
    result = {'cohort': cohort, 'documents': len(records), 'successes': successes, 'failures': failures,
              'call_statistics': ledger.stats(), 'source_checked_precision': None, 'source_checked_recall': None,
              'scoring_status': 'Extraction only; frozen reference comparison and source dispute review remain separate.'}
    write_once(root / 'extraction-summary.json', (canonical(result) + '\n').encode('utf-8'))
    return result
