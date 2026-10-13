"""Existing extractor integration; product calls have their own durable ledger."""
import json
import os
import sqlite3
from pathlib import Path
from time import perf_counter

from .source_adapter import inspect, schema, prompt
from ..provider import ProviderConfig
from ..clinical_notes.runner import SingleDispatchProvider
from .models import Packet, Source, digest, now
from .service import build_packet


def mark_partial(packet, errors):
    packet.extraction_status = 'partial'
    from .service import issue
    packet.issues.append(issue('partial_extraction', [], 'Some proposed facts or relationships failed Engine validation. Inspect the saved raw response and validation_errors.', 'high'))
    return packet.seal()


def create_from_bundle(bundle, *, case_id=None):
    source = Source.model_validate(bundle['source'])
    return build_packet(case_id or bundle['case_id'], bundle['patient_id'], source,
        bundle.get('extraction'), extraction_error=bundle.get('extraction_error'),
        metadata={'mode': 'supplied_extraction', 'origin': bundle.get('origin', 'supplied'),
                  'model_calls': 0, 'clinical_accuracy': 'not_measured',
                  'atomic_source_assertions': bundle.get('atomic_source_assertions', []),
                  'source_atomic_enumeration': bundle.get('source_atomic_enumeration'),
                  'source_verification_reviews': bundle.get('source_verification_reviews', [])},
        projection_version='soap/v5')


def import_engine_cache(root, encounter_id, *, patient_id, case_id=None):
    """Read frozen original inputs and saved facts without inference or label access."""
    root = Path(root)
    inputs = json.loads((root/'inputs.json').read_text(encoding='utf-8'))
    doc = next((d for d in inputs if d['encounter_id'] == encounter_id), None)
    if doc is None:
        raise ValueError('Encounter not in frozen Engine inputs')
    src = Source(document_id=doc['document_id'], text=doc['text'], sha256=doc['note_sha256'],
                 input_kind=doc['input_kind'], origin='engine_cache:'+encounter_id)
    # Caller may point to a separate revalidation root through the explicit --facts path.
    facts_path = root/'encounters'/encounter_id/'facts.json'
    payload = json.loads(facts_path.read_text(encoding='utf-8'))
    extraction = payload.get('extraction', payload)
    return build_packet(case_id or encounter_id, patient_id, src, extraction,
        metadata={'mode': 'engine_cache', 'model_calls': 0,
                  'input_file_hash': digest((root/'inputs.json').read_text(encoding='utf-8')),
                  'facts_file_hash': digest(facts_path.read_text(encoding='utf-8')),
                  'clinical_accuracy': 'not_measured'}, projection_version='soap/v5')


def replay_product_response(source_packet_path, raw_path, ledger_path, *, case_id):
    """Revalidate an actual saved product outcome without dispatching a provider."""
    original = Packet.model_validate_json(Path(source_packet_path).read_text(encoding='utf-8'))
    original.verify()
    key = original.extraction_metadata.get('request_key')
    if not key:
        raise ValueError('Original packet has no durable product request identity')
    # Open the existing ledger read-only; do not initialize/migrate or rewrite it.
    with sqlite3.connect(Path(ledger_path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT * FROM requests WHERE request_key=?', (key,)).fetchone()
    if row is None or row['status'] not in {'valid', 'partial'}:
        raise ValueError('Only a confirmed saved product outcome can be replayed')
    raw = Path(raw_path).read_text(encoding='utf-8')
    if raw != row['raw_response'] or original.source.sha256 != row['source_hash']:
        raise ValueError('Raw response/source differs from the original product ledger')
    inspected = inspect(raw, original.source.document())
    if inspected['status'] == 'INVALID' or inspected['result'] is None:
        raise ValueError('Saved response failed current mechanical/source validation')
    packet = build_packet(case_id, original.patient_id, original.source, inspected['result'], metadata={
        'mode': 'saved_actual_product_response', 'original_request_key': key,
        'original_packet_hash': original.content_hash, 'original_model': row['model'],
        'raw_response_sha256': digest(raw), 'new_model_calls': 0,
        'validation_errors': inspected['errors'], 'upstream_usage': json.loads(row['usage']) if row['usage'] else None,
        'clinical_accuracy': 'not_measured'}, projection_version='soap/v5')
    return mark_partial(packet, inspected['errors']) if inspected['status'] == 'PARTIAL' else packet


class ProductLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests (
                request_key TEXT PRIMARY KEY, purpose TEXT, status TEXT,
                source_hash TEXT, prompt_hash TEXT, model TEXT, started_at TEXT,
                ended_at TEXT, latency_seconds REAL, raw_response TEXT,
                result TEXT, error TEXT, dispatched INTEGER, usage TEXT)''')
            if 'document_id' not in {r[1] for r in db.execute('PRAGMA table_info(requests)')}:
                db.execute('ALTER TABLE requests ADD COLUMN document_id TEXT')
            db.executescript("""
                CREATE TRIGGER IF NOT EXISTS no_product_terminal_update BEFORE UPDATE ON requests
                  WHEN OLD.status!='reserved' BEGIN SELECT RAISE(ABORT,'Product attempt immutable'); END;
                CREATE TRIGGER IF NOT EXISTS no_product_delete BEFORE DELETE ON requests
                  BEGIN SELECT RAISE(ABORT,'Product attempt immutable'); END;
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def get(self, key):
        with self.connect() as db:
            r = db.execute('SELECT * FROM requests WHERE request_key=?', (key,)).fetchone()
        return dict(r) if r else None

    def reserve(self, key, source, request_prompt, model):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM requests WHERE source_hash=? ORDER BY started_at',
                (source.sha256,)).fetchall()
            if any(r['document_id'] not in {None, source.document_id} for r in prior):
                raise ValueError('Renaming identical source bytes cannot reset the durable document attempt budget; use the original source identity.')
            if any(r['status'] in {'valid','reserved','uncertain'} for r in prior):
                raise ValueError('Successful or uncertain document request cannot replay with a new request ID')
            if len(prior)>=3:
                raise ValueError('Document already consumed three attempts')
            if prior and not (prior[-1]['dispatched'] and prior[-1]['status'] in {'failed','partial'}):
                raise ValueError('Retry requires an eligible dispatched failure')
            db.execute('INSERT INTO requests (request_key,purpose,status,source_hash,prompt_hash,model,started_at,dispatched,document_id) VALUES (?,?,?,?,?,?,?,0,?)',
                (key, 'product_extraction', 'reserved', source.sha256, digest(request_prompt), model, now(),source.document_id))
            # Retain the earliest partial assertion baseline even if an intervening
            # repair attempt failed upstream or validation.
            baseline=next((r for r in prior if r['status']=='partial'),None)
            return dict(baseline or prior[-1]) if prior else None

    def mark_dispatched(self, key):
        with self.connect() as db:
            db.execute('UPDATE requests SET dispatched=1 WHERE request_key=?', (key,))

    def finish(self, key, *, status, latency, raw=None, result=None, error=None, usage=None):
        with self.connect() as db:
            db.execute('UPDATE requests SET status=?,ended_at=?,latency_seconds=?,raw_response=?,result=?,error=?,usage=? WHERE request_key=?',
                (status, now(), latency, raw, json.dumps(result) if result is not None else None,
                 error, json.dumps(usage) if usage is not None else None, key))

    def summary(self):
        with self.connect() as db:
            rows = db.execute('SELECT request_key,purpose,status,model,source_hash,started_at,ended_at,latency_seconds,dispatched,usage,error FROM requests ORDER BY started_at').fetchall()
        return {'kind': 'product_calls', 'research_calls': 0, 'requests': [dict(r) for r in rows],
                'dispatch_attempts': sum(r['dispatched'] for r in rows), 'automatic_retries': 0}


def extract_live(case_id, patient_id, source, ledger, *, provider_factory=None, request_id='first', model='gpt-6-luna'):
    """Explicit opt-in. Same request key resumes the saved outcome, never resamples.

    A different request_id permits only an eligible failure retry, at most three
    attempts per original document. Successful/uncertain outcomes cannot resample.
    """
    if model!='gpt-6-luna':
        raise ValueError('Clinical extraction must use gpt-6-luna/high; no silent model substitution')
    doc = source.document()
    request_prompt = prompt(doc)
    shape = schema(doc)
    key = digest([case_id, patient_id, source.sha256, doc.document_id, digest(request_prompt), digest(shape), model, request_id])
    previous = ledger.get(key)
    if previous:
        if previous['status'] in {'reserved', 'uncertain'}:
            raise ValueError('Uncertain previous request; automatic replay blocked. Inspect the product ledger.')
        resolved = json.loads(previous['result']) if previous['result'] else None
        p = build_packet(case_id, patient_id, source, resolved,
            extraction_error=previous['error'] if resolved is None else None,
            metadata={'mode': 'live_saved_outcome', 'request_key': key, 'new_model_calls': 0,
                      'validation_errors': json.loads(previous['error']) if resolved and previous['error'] else []},
            projection_version='soap/v5')
        return mark_partial(p, p.extraction_metadata['validation_errors']) if previous['status'] == 'partial' else p
    try:
        prior=ledger.reserve(key, source, request_prompt, model)
    except sqlite3.IntegrityError:
        raise ValueError('Request already reserved; concurrent automatic replay blocked') from None
    start = perf_counter()
    raw, inspected, usage = None, None, None
    try:
        if prior and prior['status']=='partial' and prior['raw_response']:
            initial=inspect(prior['raw_response'],doc)
            request_prompt+='\nMECHANICAL REPAIR ONLY: preserve accepted facts and all clinical fields, count and order. Change schema/source references only.\n'+json.dumps({'previous_output':prior['raw_response'],'mechanical_errors':initial['errors']},ensure_ascii=False)
            with ledger.connect() as db:
                db.execute('UPDATE requests SET prompt_hash=? WHERE request_key=?',(digest(request_prompt),key))
        from .evaluation.concurrency import LunaSlots
        path = Path(os.environ.get('CLINICAL_LUNA_SLOTS', str(Path.cwd().parent/'artifacts'/'clinical-luna-shared.sqlite3')))
        if provider_factory is not None:
            path=ledger.path.parent/'test-product-slots.sqlite3'
        slots=LunaSlots(path)
        with slots.hold(key):
            if provider_factory is not None:
                provider = provider_factory()
                ledger.mark_dispatched(key)
                response = provider.structured_output(request_prompt, shape, purpose='copilot_product_extraction')
                raw = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
                if hasattr(provider, 'usage'):
                    usage = provider.usage(perf_counter()-start).model_dump(mode='json')
            else:
                provider=SingleDispatchProvider(ProviderConfig(model=model,reasoning_effort='high'))
                provider.preflight()
                folder=ledger.path.parent/'product-requests'/key
                folder.mkdir(parents=True,exist_ok=True)
                from ..clinical_notes.dataset import write_json
                write_json(folder/'schema.json',shape,immutable=True)
                (folder/'prompt.txt').write_text(request_prompt,encoding='utf-8')
                ledger.mark_dispatched(key)
                raw,usage=provider.dispatch(doc,folder.resolve())
        inspected = inspect(raw, doc)
        if prior and prior['status']=='partial' and prior['raw_response']:
            from .evaluation.execution import preserving_repair
            preserving_repair(prior['raw_response'],raw,initial,inspected,doc)
        if inspected['result'] is None or inspected['status'] == 'INVALID':
            raise ValueError('Extractor failed source/schema validation: ' + '; '.join(inspected['errors']))
        ledger.finish(key, status=inspected['status'].lower(), latency=perf_counter()-start, raw=raw,
                      result=inspected['result'], error=json.dumps(inspected['errors']) if inspected['errors'] else None, usage=usage)
        p = build_packet(case_id, patient_id, source, inspected['result'], metadata={
            'mode': 'live', 'request_key': key, 'model': model, 'new_model_calls': 1,
            'validation_errors': inspected['errors'], 'accepted_original_indices': inspected['accepted_indices']},
            projection_version='soap/v5')
        if inspected['status'] == 'PARTIAL':
            mark_partial(p, inspected['errors'])
        return p
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        if ledger.get(key)['status'] != 'reserved':
            # A projection defect cannot rewrite an already durable provider outcome.
            # The same saved request can be reprojected after a code repair, without inference.
            raise RuntimeError('Saved provider outcome preserved; projection failed for ' + key) from exc
        dispatched = bool(ledger.get(key)['dispatched'])
        # A lost stream/timeout is not proof that the remote request failed.
        # Preserve a usable failure draft, while preventing same-source retries
        # through either the same or a newly invented request ID.
        delivery_unknown = dispatched and raw is None and (
            isinstance(exc, (TimeoutError, ConnectionError))
            or any(word in str(exc).casefold() for word in ('timeout', 'stream interrupted', 'stream disconnected', 'no replay')))
        ledger.finish(key, status='uncertain' if delivery_unknown else 'failed',
                      latency=perf_counter()-start, raw=raw, error=error, usage=usage)
        return build_packet(case_id, patient_id, source, None, extraction_error=error,
            metadata={'mode': 'live', 'request_key': key, 'new_model_calls': ledger.get(key)['dispatched'],
                      'model': model, 'automatic_retries': 0,
                      'delivery_status': 'uncertain' if delivery_unknown else 'failed'},
            projection_version='soap/v5')
