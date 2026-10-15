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

STRUCTURED_TASK = 'clinical-structured-extraction/1'
LEGACY_TASK = 'legacy-clinical-extraction/1'


def structured_contract():
    from ..evidence_bridge import verification_package
    verification_package()
    from evidence_verification.extensions import structured_extraction
    return structured_extraction


def structured_catalogue(document):
    from ..dialogue_first.dataset import source_index
    from ..evidence_bridge import verification_package
    verification_package()
    from evidence_verification.extensions.source_index import source_index as compatible_index
    return compatible_index(document, legacy_index=source_index)


def typed_schema(document):
    """The existing typed/2 representation supplied to the common wire builder."""
    from typing import Literal
    from ..clinical_notes.schema import StrictModel
    from ..dialogue_first.contract import ProposedFact, Proposal
    class ClinicalSemanticsV2(StrictModel):
        version: Literal['clinical-fact-semantics/2']
        frequency: str | None
        event_time: str | None
        duration: str | None
        action_state: Literal['planned', 'completed', 'not_completed', 'ongoing', 'discussed', 'unknown']
        completion_scope: Literal['single_event', 'course', 'full_course', 'unknown'] | None
        assertion_basis: Literal['patient_report', 'patient_reported', 'clinician_assessment',
            'clinician_observation', 'documented_history', 'discussion', 'unknown']
        action_type: str | None
    class TypedFact(ProposedFact):
        semantics: ClinicalSemanticsV2
    class TypedProposal(Proposal):
        facts: list[TypedFact]
    shape = TypedProposal.model_json_schema()
    shape['properties']['document_id']['enum'] = [document.document_id]
    shape['$defs']['References']['properties']['source_ids']['items']['enum'] = [
        row['source_id'] for row in structured_catalogue(document)['source_catalogue']]
    return shape


def inspect_structured(raw, document):
    """Normalize once, retain quarantines, and resolve the original catalogue."""
    from ..dialogue_first import contract as engine
    from ..clinical_notes.schema import Evidence, validate_extraction
    try:
        document.verify()
        catalogue = structured_catalogue(document)['source_catalogue']
        normalized = structured_contract().normalize(json.loads(raw), catalogue, typed_schema(document))
        payload = normalized['payload']
        if payload['document_id'] != document.document_id:
            raise ValueError('Structured document identity mismatch')
        indexed = {item['source_id']: item for item in catalogue}
        facts = []
        anchors = {row['fact_index']:row for row in normalized['anchors']}
        for index, item in enumerate(payload['facts']):
            proposed = engine.ProposedFact.model_validate(item)
            anchor = anchors[index]
            spans = engine.resolve_references(engine.References(source_ids=anchor['selected_source_ids']), document, indexed)
            primary = next((span for span in spans if span['source_id']==anchor['primary_source_id']), spans[0])
            value = proposed.model_dump(exclude={'evidence'})
            value.update(original_term=primary['quote'],
                evidence={k: primary[k] for k in Evidence.model_fields},
                supporting_evidence=[{k: s[k] for k in Evidence.model_fields} for s in spans if s is not primary],
                provenance=spans)
            facts.append(engine.DialogueFact.model_validate(value).model_dump(mode='json'))
        relationships = [engine.resolve_relationship(item, document, indexed,
            {i:i for i in range(len(facts))}) for item in payload['relationships']]
        result = engine.Extraction(document_id=document.document_id, facts=facts,
            relationships=relationships).model_dump(mode='json')
        validate_extraction(json.dumps(engine.primary_projection(result)), document)
        metadata = {key: value for key, value in normalized.items() if key != 'payload'}
        metadata.update(version=STRUCTURED_TASK, source_sha256=sha(document.text),
            raw_response=raw, raw_response_sha256=sha(raw))
        # Isolated invalid fields and relations are retained, not retried for a
        # different semantic answer. No accepted facts means a mechanical failure.
        return {'status': 'VALID' if facts else 'INVALID', 'result': result,
            'accepted_indices': normalized.get('accepted_original_indices', []),
            'errors': normalized.get('errors', []), 'structured_extraction': metadata,
            'partial': bool(normalized.get('errors') or normalized.get('field_quarantine')
                            or normalized.get('relationship_quarantine', {}).get('items') or normalized.get('rejected_facts'))}
    except (ValueError, TypeError, KeyError) as exc:
        return {'status':'INVALID', 'result':None, 'accepted_indices':[], 'errors':[str(exc)]}


def extraction_context(source_id, result):
    value = {'source_id':source_id, 'extraction':result['extraction']}
    if 'structured_extraction' in result:
        value.update(structured_extraction=result['structured_extraction'],
            source_index_version='copilot-source-index/v1')
    return value


def source_contract(record, *, task_version=None):
    document = Document(record['document_id'], record['case_group'], record['dataset'], record['text'],
                        sha(record['text']), record.get('source_sha256', sha(record['text'])),
                        record.get('original_row', 0), input_kind='dialogue' if record['input_kind'] == 'dialogue' else 'note')
    if task_version is None:
        initial_prompt, shape = prompt(document), schema(document)
    elif task_version == STRUCTURED_TASK:
        from ..dialogue_first.prompt import DIALOGUE_INSTRUCTION, NOTE_INSTRUCTION
        adapter = structured_contract()
        catalogue = structured_catalogue(document)
        shape = adapter.build_schema(typed_schema(document), catalogue['source_catalogue'])
        instruction = DIALOGUE_INSTRUCTION if document.input_kind == 'dialogue' else NOTE_INSTRUCTION
        initial_prompt = instruction + '\n' + adapter.prompt_fragment() + '\n' + json.dumps({
            'document_id':document.document_id, 'encounter_id':document.encounter_id,
            'input_kind':document.input_kind, 'text':document.text, **catalogue}, ensure_ascii=False)
    else:
        raise ValueError('Unsupported clinical extraction task')
    identity = {'document_id': document.document_id, 'source_sha256': sha(document.text),
                'prompt_sha256': sha(initial_prompt), 'schema_sha256': sha(canonical(shape)),
                'model': 'gpt-6-luna', 'reasoning_effort': 'high'}
    if task_version is not None:
        identity.update(task_version=task_version, semantics_version='clinical-fact-semantics/2',
            source_index_version='copilot-source-index/v1')
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
            outcome = (inspect_structured(raw, document) if identity.get('task_version') == STRUCTURED_TASK else
                inspect_repair(raw, base_raw, base_outcome, document) if base_raw is not None else inspect(raw, document))
            if outcome['status'] == 'VALID':
                if number != result['attempt'] or canonical(outcome['result']) != canonical(result['extraction']):
                    raise ValueError('Cache differs from first mechanically accepted original output')
                if outcome.get('structured_extraction') != result.get('structured_extraction'):
                    raise ValueError('Cache structured fields differ from original raw output')
                return result
            if outcome['result'] is not None:
                base_raw, base_outcome = raw, outcome
        raise ValueError('Cache accepted output no longer validates')
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Cache evidence is incomplete or invalid') from exc


def extract_document(record, cache_root, ledger, *, provider=None, max_attempts=3, task_version=None):
    """Cache identity uses only source, prompt, schema and requested model settings.

    References are never serialized into the request directory. A valid first
    extraction is final; semantic scores cannot authorize another attempt.
    """
    if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise ValueError('Extraction permits one to three mechanical attempts')
    configured_model = getattr(getattr(provider, 'config', None), 'model', None)
    if configured_model is not None and configured_model != 'gpt-6-luna':
        raise ValueError('CareFlow clinical extraction accepts gpt-6-luna only; external evaluations are offline')
    document, initial_prompt, shape, identity = source_contract(record, task_version=task_version)
    if task_version == STRUCTURED_TASK:
        max_attempts = 1
    fingerprint = sha(canonical(identity))
    root = Path(cache_root).resolve() / fingerprint
    root.mkdir(parents=True, exist_ok=True)
    write_once(root / 'identity.json', (canonical(identity) + '\n').encode('utf-8'))
    result_path = root / 'result.json'
    if result_path.exists():
        return validate_cached(root, document, identity, ledger)
    provider = provider or SingleDispatchProvider(ProviderConfig(model='gpt-6-luna', reasoning_effort='high', timeout_seconds=300))
    if callable(getattr(provider, 'preflight', None)):
        provider.preflight()
    previous = None
    raw_response = None
    repair_base_raw, repair_base_outcome = None, None
    for local_attempt in range(max_attempts):
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
            if status == 'UNRESOLVED_DISPATCH' or token['attempt'] == 3 or local_attempt + 1 == max_attempts:
                raise
            previous = None
            continue
        write_once(folder / 'raw-response-snapshot.json', raw_response.encode('utf-8'))
        outcome = (inspect_structured(raw_response, document) if task_version == STRUCTURED_TASK else
                   inspect_repair(raw_response, repair_base_raw, repair_base_outcome, document)
                   if repair_base_raw is not None else inspect(raw_response, document))
        write_once(folder / 'mechanical-outcome.json', (canonical(outcome) + '\n').encode('utf-8'))
        status = 'SUCCESS' if outcome['status'] == 'VALID' else 'MECHANICAL_FAILURE'
        ledger.finish(token, status, usage=usage, error=None if status == 'SUCCESS' else canonical(outcome['errors']))
        if status == 'SUCCESS':
            result = {'schema_version': 'careflow-source-extraction/2', 'document': {k: v for k, v in asdict(document).items() if k != 'text'},
                      'source_only': True, 'identity': identity, 'extraction': outcome['result'],
                      'status': 'VALID', 'attempt': token['attempt'], 'usage': usage,
                      'boundary': 'Mechanical source validity, not semantic accuracy or documentation satisfaction.'}
            if 'structured_extraction' in outcome:
                result.update(structured_extraction=outcome['structured_extraction'], partial=outcome['partial'])
            write_once(result_path, (canonical(result) + '\n').encode('utf-8'))
            return result
        if outcome['result'] is not None:
            repair_base_raw, repair_base_outcome = raw_response, outcome
        previous = outcome
    raise ValueError(f'{max_attempts} extraction attempt(s) failed mechanical validation; all originals retained')


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
