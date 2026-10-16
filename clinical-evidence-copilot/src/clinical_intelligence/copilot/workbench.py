"""Patient/encounter bindings around the existing immutable source packets.

This is an application index, not another extraction engine. Each source owns a
durable job; all downstream operations read the saved CaseStore version.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .models import Source, ReviewRequest, SemanticsReviewRequest, digest, now
from .presentation import draft_presentation, _draft_presentation_verified
from .runtime import extract_live
from .store import VersionConflict


VERSION = 'workbench/1'
MAX_FILES = 20
MAX_SOURCE_CHARS = 80_000
ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$')


def identifier(value, name):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f'{name} must be 1–120 letters, digits, dots, dashes, colons or underscores')
    return value


def date_value(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise ValueError('Encounter time must be an explicit ISO date/time or null')
    datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value


class Workbench:
    def __init__(self, store, *, ledger=None, live=False, careflow_url=None,
                 extractor=extract_live, workers=2):
        self.store, self.ledger, self.live = store, ledger, live
        self.extractor = extractor
        self.careflow_url = careflow_url.rstrip('/') if careflow_url else None
        if self.careflow_url:
            parsed = urlparse(self.careflow_url)
            if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}
                    or parsed.path or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise ValueError('CareFlow bridge requires a configured loopback HTTP origin')
        self.pool = ThreadPoolExecutor(max_workers=max(1, min(4, workers)), thread_name_prefix='source-extraction')
        self.pending, self.lock = set(), threading.Lock()
        self.closed = False
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS wb_patients (
                    patient_id TEXT PRIMARY KEY, display_label TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wb_encounters (
                    patient_id TEXT NOT NULL, encounter_id TEXT NOT NULL, encounter_time TEXT,
                    created_at TEXT NOT NULL, PRIMARY KEY(patient_id,encounter_id));
                CREATE TABLE IF NOT EXISTS wb_documents (
                    case_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, document_id TEXT NOT NULL,
                    filename TEXT NOT NULL, source_hash TEXT NOT NULL, source_text TEXT NOT NULL,
                    input_kind TEXT NOT NULL, encounter_id TEXT, encounter_time TEXT,
                    status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(patient_id,source_hash), UNIQUE(patient_id,document_id));
                CREATE TABLE IF NOT EXISTS wb_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, kind TEXT,
                    occurred_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS wb_careflow (
                    case_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, source_case_ids TEXT NOT NULL,
                    source_versions TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS wb_no_event_update BEFORE UPDATE ON wb_events
                    BEGIN SELECT RAISE(ABORT,'Workbench audit is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS wb_no_event_delete BEFORE DELETE ON wb_events
                    BEGIN SELECT RAISE(ABORT,'Workbench audit is append-only'); END;
            ''')
            if 'request_hash' not in {r[1] for r in db.execute('PRAGMA table_info(wb_careflow)')}:
                db.execute('ALTER TABLE wb_careflow ADD COLUMN request_hash TEXT')
            for field, kind in [('revision', 'INTEGER'), ('readiness', 'TEXT')]:
                if field not in {r[1] for r in db.execute('PRAGMA table_info(wb_careflow)')}:
                    db.execute(f'ALTER TABLE wb_careflow ADD COLUMN {field} {kind}')
        # Do not redispatch an interrupted attempt. A committed packet is safe to
        # recover, otherwise require inspection of the original attempt ledger.
        with self.connect() as db:
            interrupted = db.execute("SELECT * FROM wb_documents WHERE status='processing'").fetchall()
        for row in interrupted:
            try:
                packet = self.store.get(row['case_id'])
            except KeyError:
                self._status(row['case_id'], 'uncertain', 'Previous process stopped during extraction; no automatic redispatch.')
            else:
                self._status(row['case_id'], self._packet_status(packet), None)
        if self.live:
            with self.connect() as db:
                queued = db.execute("SELECT case_id FROM wb_documents WHERE status='queued'").fetchall()
            for row in queued:
                self._schedule(row['case_id'])

    def connect(self):
        db = sqlite3.connect(self.store.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def close(self):
        self.closed = True
        # In-flight calls retain their existing provider timeout and ledger.
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _event(self, db, patient, kind, payload):
        db.execute('INSERT INTO wb_events(patient_id,kind,occurred_at,payload) VALUES(?,?,?,?)',
                   (patient, kind, now(), json.dumps(payload, ensure_ascii=False)))

    def patients(self):
        with self.connect() as db:
            return {'patients': [dict(r) for r in db.execute('SELECT * FROM wb_patients ORDER BY created_at,patient_id')]}

    def patient(self, patient_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM wb_patients WHERE patient_id=?', (patient_id,)).fetchone()
        if row is None:
            raise KeyError('Unknown patient identity')
        return dict(row)

    def create_patient(self, body):
        patient_id = identifier(body.get('patient_id'), 'patient_id')
        label = body.get('display_label', patient_id)
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise ValueError('A nonblank display label of at most 200 characters is required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM wb_patients WHERE patient_id=?', (patient_id,)).fetchone()
            if existing:
                if existing['display_label'] != label.strip():
                    raise VersionConflict('This patient ID already has a different label; names do not merge identities')
                return dict(existing)
            db.execute('INSERT INTO wb_patients VALUES(?,?,?)', (patient_id, label.strip(), now()))
            self._event(db, patient_id, 'patient_created', {'display_label': label.strip()})
        return self.patient(patient_id)

    def _document(self, patient_id, case_id):
        self.patient(patient_id)
        with self.connect() as db:
            row = db.execute('SELECT * FROM wb_documents WHERE patient_id=? AND case_id=?', (patient_id, case_id)).fetchone()
        if row is None:
            raise KeyError('Source does not belong to this patient workspace')
        return dict(row)

    def upload(self, patient_id, body):
        self.patient(patient_id)
        incoming = body.get('files')
        if not isinstance(incoming, list) or not 1 <= len(incoming) <= MAX_FILES:
            raise ValueError(f'Upload requires 1–{MAX_FILES} text sources')
        results = []
        for index, item in enumerate(incoming):
            try:
                results.append(self._register(patient_id, item))
            except (ValueError, TypeError, KeyError, VersionConflict) as exc:
                rejection = {'index': index, 'document_id': item.get('document_id') if isinstance(item, dict) else None,
                             'status': 'rejected', 'error': str(exc), 'new_model_calls': 0}
                results.append(rejection)
                with self.connect() as db:
                    self._event(db, patient_id, 'upload_rejected', rejection)
        return {'contract_version': VERSION, 'files': results, 'jobs': results,
                'automatic_retries': 0, 'maximum_parallel_extractions': self.pool._max_workers}

    def _register(self, patient_id, item):
        if not isinstance(item, dict):
            raise ValueError('Each source must be an object')
        text = item.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_SOURCE_CHARS or '\x00' in text:
            raise ValueError(f'Each source must contain 1–{MAX_SOURCE_CHARS} Unicode text characters; PDF/binary is unsupported')
        kind = item.get('input_kind', 'note')
        if kind not in {'note', 'dialogue'}:
            raise ValueError('input_kind must be note or dialogue')
        declared_patient = item.get('source_patient_id')
        if declared_patient not in (None, '', patient_id):
            raise ValueError('Explicit source patient identity differs from selected patient')
        # Exact identifiers only. Never merge patients by names or infer identity
        # from clinical facts. This check catches a common explicit-header mixup.
        headers = re.findall(r'^\s*Patient[ _-]?ID\s*:\s*(\S+)\s*$', text, re.I | re.M)
        if any(value != patient_id for value in headers):
            raise ValueError('Patient ID in the source conflicts with selected identity')
        encounter_id = identifier(item['encounter_id'], 'encounter_id') if item.get('encounter_id') else None
        encounter_time = date_value(item.get('encounter_time'))
        if encounter_id is None and encounter_time is not None:
            raise ValueError('A date alone cannot assign an encounter; provide encounter_id or leave both unknown')
        source_hash = digest(text)
        document_id = identifier(item.get('document_id') or 'src-' + source_hash[:24], 'document_id')
        filename = item.get('filename') or document_id
        if not isinstance(filename, str) or len(filename) > 250:
            raise ValueError('Filename must be at most 250 characters')
        case_id = 'wb-' + digest([patient_id, source_hash])[:28]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM wb_documents WHERE source_hash=?', (source_hash,)).fetchall()
            if any(r['patient_id'] != patient_id for r in prior):
                raise VersionConflict('Identical source already belongs to another patient; resolve identity explicitly')
            if prior:
                old = prior[0]
                if (old['input_kind'], old['encounter_id'], old['encounter_time']) != (kind, encounter_id, encounter_time):
                    raise VersionConflict('Duplicate source has different kind/encounter metadata; existing association was preserved')
                self._event(db, patient_id, 'duplicate_source_reused', {'case_id': old['case_id'], 'uploaded_filename': filename})
                return {'case_id': old['case_id'], 'document_id': old['document_id'], 'status': old['status'],
                        'reused': True, 'new_model_calls': 0, 'error': old['error']}
            saved = db.execute('SELECT case_id,patient_id FROM versions WHERE source_hash=? GROUP BY case_id,patient_id', (source_hash,)).fetchall()
            if any(r['patient_id'] != patient_id for r in saved):
                raise VersionConflict('Saved source belongs to a different patient identity')
            retained = self.store.get(saved[0]['case_id']) if saved else None
            if retained:
                if retained.source.input_kind != kind or retained.source.encounter_time != encounter_time:
                    raise VersionConflict('Saved source metadata differs; preserve original kind/record date')
                case_id, document_id = retained.case_id, retained.source.document_id
            elif not self.live or self.ledger is None:
                raise ValueError('Live extraction is disabled; restart with --live to add a new source')
            if db.execute('SELECT 1 FROM wb_documents WHERE patient_id=? AND document_id=?', (patient_id, document_id)).fetchone():
                raise VersionConflict('Document ID already has different immutable source bytes')
            # Respect a source previously dispatched through the legacy entrypoint.
            if not retained:
                with self.ledger.connect() as attempts:
                    old_attempts = attempts.execute('SELECT * FROM requests WHERE source_hash=? ORDER BY started_at', (source_hash,)).fetchall()
                if old_attempts:
                    raise VersionConflict('Source already has an unsaved product attempt; inspect its original ledger before any recovery')
            if encounter_id:
                prior_encounter = db.execute('SELECT * FROM wb_encounters WHERE patient_id=? AND encounter_id=?', (patient_id, encounter_id)).fetchone()
                if prior_encounter and prior_encounter['encounter_time'] != encounter_time:
                    raise VersionConflict('Encounter ID has different date metadata; existing association was preserved')
                db.execute('INSERT OR IGNORE INTO wb_encounters VALUES(?,?,?,?)', (patient_id, encounter_id, encounter_time, now()))
            status = self._packet_status(retained) if retained else 'queued'
            db.execute('INSERT INTO wb_documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (case_id, patient_id, document_id, filename, source_hash, text, kind, encounter_id,
                 encounter_time, status, None, now(), now()))
            self._event(db, patient_id, 'source_registered', {'case_id': case_id, 'document_id': document_id,
                'source_hash': source_hash, 'encounter_id': encounter_id, 'encounter_time': encounter_time,
                'association_basis': 'explicit_user_metadata', 'existing_packet_reused': bool(retained)})
        if not retained:
            self._schedule(case_id)
        return {'case_id': case_id, 'document_id': document_id, 'status': status, 'reused': bool(retained), 'new_model_calls': 0}

    def _schedule(self, case_id):
        with self.lock:
            if self.closed or case_id in self.pending:
                return
            self.pending.add(case_id)
        future = self.pool.submit(self._run, case_id)
        def done(_):
            with self.lock:
                self.pending.discard(case_id)
        future.add_done_callback(done)

    def _status(self, case_id, status, error=None):
        with self.connect() as db:
            db.execute('UPDATE wb_documents SET status=?,error=?,updated_at=? WHERE case_id=?', (status, error, now(), case_id))
            row = db.execute('SELECT patient_id FROM wb_documents WHERE case_id=?', (case_id,)).fetchone()
            self._event(db, row['patient_id'], 'extraction_status', {'case_id': case_id, 'status': status, 'error': error})

    @staticmethod
    def _packet_status(packet):
        if packet.extraction_metadata.get('delivery_status') == 'uncertain':
            return 'uncertain'
        return {'valid': 'succeeded', 'partial': 'partial'}.get(packet.extraction_status, 'failed')

    def _run(self, case_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM wb_documents WHERE case_id=?', (case_id,)).fetchone()
            if row['status'] != 'queued':
                return
            db.execute("UPDATE wb_documents SET status='processing',updated_at=? WHERE case_id=?", (now(), case_id))
            self._event(db, row['patient_id'], 'extraction_started', {'case_id': case_id})
        try:
            source = Source.create(row['document_id'], row['source_text'], row['input_kind'], encounter_time=row['encounter_time'])
            packet = self.extractor(case_id, row['patient_id'], source, self.ledger)
            self.store.save(packet, expected_version=0)
            error = packet.extraction_metadata.get('extraction_error')
            if self._packet_status(packet) in {'failed', 'uncertain', 'partial'}:
                attempt = self.ledger.get(packet.extraction_metadata.get('request_key'))
                error = attempt['error'] if attempt else error
            self._status(case_id, self._packet_status(packet), error)
        except Exception as exc:
            # The extraction layer has durable raw/reservations. Never infer a
            # failed remote request from an application exception.
            with self.ledger.connect() as db:
                attempts = db.execute('SELECT status FROM requests WHERE source_hash=?', (row['source_hash'],)).fetchall()
            status = 'uncertain' if any(r['status'] in {'reserved', 'uncertain'} for r in attempts) else 'failed'
            self._status(case_id, status, f'{type(exc).__name__}: {exc}')

    def packets(self, patient_id):
        self.patient(patient_id)
        with self.connect() as db:
            rows = db.execute('SELECT case_id FROM wb_documents WHERE patient_id=?', (patient_id,)).fetchall()
        packets = []
        for row in rows:
            try:
                packets.append(self.store.get(row['case_id']))
            except KeyError:
                pass
        return packets

    def workspace(self, patient_id):
        workspace, _ = self._workspace_with_packets(patient_id)
        return workspace

    def _workspace_with_packets(self, patient_id):
        patient = self.patient(patient_id)
        with self.connect() as db:
            docs = [dict(r) for r in db.execute('SELECT * FROM wb_documents WHERE patient_id=? ORDER BY created_at,case_id', (patient_id,))]
            encounters = [dict(r) for r in db.execute('SELECT * FROM wb_encounters WHERE patient_id=? ORDER BY encounter_time IS NULL,encounter_time,encounter_id', (patient_id,))]
        packets = {p.case_id: p for p in self.packets(patient_id)}
        for doc in docs:
            doc.pop('source_text')
            packet = packets.get(doc['case_id'])
            doc.update(packet_version=packet.version if packet else None,
                       content_hash=packet.content_hash if packet else None,
                       fact_count=len(packet.facts) if packet else 0,
                       association_basis='explicit_user_metadata')
        evidence_version = digest([[d['case_id'], d['content_hash'], d['encounter_id'], d['encounter_time']] for d in docs])
        for encounter in encounters:
            bound = [d for d in docs if d['encounter_id'] == encounter['encounter_id']]
            encounter.update(document_ids=[d['document_id'] for d in bound],
                             case_ids=[d['case_id'] for d in bound],
                             document_count=len(bound), fact_count=sum(d['fact_count'] for d in bound),
                             association_basis='explicit_user_metadata')
        return {'contract_version': VERSION, 'patient': patient, 'encounters': encounters, 'documents': docs,
                'extraction_jobs': docs, 'active_encounter_id': encounters[0]['encounter_id'] if encounters else None,
                'evidence_version': evidence_version,
                'capabilities': {'batch_extraction': self.live, 'max_files': MAX_FILES, 'max_source_characters': MAX_SOURCE_CHARS,
                    'deterministic_queries': True, 'natural_language_query': self.live, 'polish': self.live,
                    'careflow_shared_evidence': bool(self.careflow_url), 'automatic_retries': 0,
                    'runtime_model': 'gpt-6-luna', 'provider': os.environ.get('CLINICAL_PRODUCT_PROVIDER', 'codex_cli'),
                    'accepted_file_types': ['text/plain'],
                    'encounter_identity': 'explicit_user_metadata'}}, packets

    def evidence(self, patient_id, case_id, version=None):
        self._document(patient_id, case_id)
        packet = self.store.get(case_id, version)
        return {'packet': packet.model_dump(mode='json'), 'presentation': _draft_presentation_verified(packet),
                'history': self.store.history(case_id)}

    def soap(self, patient_id, encounter_id):
        workspace, packets = self._workspace_with_packets(patient_id)
        if not any(e['encounter_id'] == encounter_id for e in workspace['encounters']):
            raise KeyError('Unknown encounter')
        docs = [d for d in workspace['documents'] if d['encounter_id'] == encounter_id]
        sections = {s: [] for s in 'SOAP'}
        links, versions, missing = {}, [], []
        for doc in docs:
            if doc['packet_version'] is None:
                missing.append({'document_id': doc['document_id'], 'status': doc['status'], 'error': doc['error']})
                continue
            packet = packets[doc['case_id']]
            if packet.version != doc['packet_version']:
                raise ValueError('Workspace packet version changed during SOAP projection')
            presentation = _draft_presentation_verified(packet)
            evidence = {e.evidence_id: e for e in packet.evidence}
            versions.append({'case_id': packet.case_id, 'version': packet.version, 'content_hash': packet.content_hash})
            for section, rows in presentation['sections'].items():
                for row in rows:
                    refs = [{'case_id': packet.case_id, 'packet_version': packet.version, 'document_id': packet.source.document_id,
                             'fact_id': row['fact_id'], **evidence[e].model_dump(mode='json')} for e in row['evidence_ids']]
                    identity = packet.case_id + ':' + row['fact_id']
                    sections[section].append({**row, 'statement_id': identity, 'case_id': packet.case_id,
                        'document_id': packet.source.document_id, 'packet_version': packet.version, 'source_refs': refs})
                    links[identity] = refs
        return {'contract_version': VERSION, 'patient_id': patient_id, 'encounter_id': encounter_id,
                'scope': 'selected_encounter', 'sections': sections, 'sentence_evidence_links': links,
                'saved_version': versions, 'evidence_version': workspace['evidence_version'], 'editable': True,
                'missing_documents': missing, 'polishing_capability': {'enabled': self.live, 'model': 'gpt-6-luna',
                    'extra_model_call': True, 'proposal_only': True, 'changes_facts': False}}

    def correct(self, patient_id, case_id, fact_id, body):
        self._document(patient_id, case_id)
        old = self.store.get(case_id)
        data = dict(body)
        kind = data.pop('kind', 'fact')
        if data.get('fact_id', fact_id) != fact_id:
            raise ValueError('Body and route fact identity differ')
        data['fact_id'] = fact_id
        from .reviewer import validate_product_review_request
        if kind == 'semantics':
            from .semantics import review_semantics
            request = SemanticsReviewRequest.model_validate(data)
            function = review_semantics
        elif kind == 'fact':
            from .service import review_packet
            request = ReviewRequest.model_validate(data)
            function = review_packet
        else:
            raise ValueError('Unknown correction kind')
        if request.base_version != old.version:
            raise VersionConflict('Fact changed since this editor was opened')
        validate_product_review_request(old, request)
        packet = function(old, request)
        self.store.save(packet, expected_version=old.version)
        with self.connect() as db:
            self._event(db, patient_id, 'source_fact_revision', {'case_id': case_id, 'version': packet.version,
                'parent_hash': old.content_hash, 'content_hash': packet.content_hash, 'fact_id': fact_id})
        synchronized = self.sync_dependents(patient_id, case_id)
        return {'packet': packet.model_dump(mode='json'), 'presentation': draft_presentation(packet),
                'workspace': self.workspace(patient_id), 'careflow_sync': synchronized, 'model_calls': 0}

    def query(self, patient_id, body):
        from .patient_queries import _query_verified_patient_packets
        workspace, packets = self._workspace_with_packets(patient_id)
        if 'question' in body:
            if not self.live or body.get('allow_model') is not True:
                raise ValueError('Interpreting a new question requires explicit allow_model=true and live mode')
            from .workbench_calls import interpret_question
            interpreted, receipt = interpret_question(self.store.path, patient_id, body)
            if interpreted.get('status') != 'ready':
                return {**interpreted, 'model_used_for_interpretation': True, 'model_calls': receipt['new_model_calls'],
                        'call_receipt': receipt, 'evidence_version': workspace['evidence_version']}
            query = interpreted['query_spec']
            if self.workspace(patient_id)['evidence_version'] != workspace['evidence_version']:
                raise VersionConflict('Evidence changed while interpreting the question; reload the patient workspace')
        else:
            query, receipt = body, None
        result = _query_verified_patient_packets(workspace, packets.values(), query)
        if receipt:
            result.update(model_used_for_interpretation=True, model_calls=receipt['new_model_calls'], call_receipt=receipt)
        with self.connect() as db:
            self._event(db, patient_id, 'query_executed', {'query_spec': result.get('query_spec'),
                'evidence_version': workspace['evidence_version'], 'model_calls': result.get('model_calls', 0)})
        return result

    def _cf(self, path, body=None):
        if not self.careflow_url:
            raise ValueError('CareFlow is not connected; start the shared launcher')
        headers = {'Content-Type': 'application/json'}
        try:
            if body is not None:
                with urlopen(self.careflow_url + '/v1/config', timeout=10) as response:
                    headers['X-CareFlow-Token'] = json.load(response)['csrf_token']
            request = Request(self.careflow_url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            content = exc.read(16000).decode('utf-8', errors='replace')
            raise ValueError(f'CareFlow rejected the request ({exc.code}): {content}') from exc
        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise ValueError('CareFlow connection unavailable; saved clinical facts remain intact') from exc

    def _refs(self, patient_id, case_ids=None):
        packets = self.packets(patient_id)
        if case_ids is not None:
            if not isinstance(case_ids, list) or len(case_ids) != len(set(case_ids)):
                raise ValueError('case_ids must be a unique list')
            if not set(case_ids) <= {p.case_id for p in packets}:
                raise ValueError('Clinical sources must be saved in this patient workspace')
            packets = [p for p in packets if p.case_id in case_ids]
        if not packets:
            raise ValueError('No saved clinical source is available')
        return [{'case_id': p.case_id, 'version': p.version, 'content_hash': p.content_hash} for p in packets]

    def cf_requests(self, patient_id):
        self.patient(patient_id)
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM wb_careflow WHERE patient_id=? ORDER BY created_at', (patient_id,))]
        latest = {p.case_id: p.version for p in self.packets(patient_id)}
        for row in rows:
            row['source_case_ids'] = json.loads(row['source_case_ids'])
            row['source_versions'] = json.loads(row['source_versions'])
            row['stale'] = any(latest.get(cid) != v for cid, v in row['source_versions'].items())
        return {'requests': rows}

    def cf_create(self, patient_id, body):
        self.patient(patient_id)
        data = dict(body)
        if data.get('request', {}).get('patient_id') != patient_id:
            raise ValueError('CareFlow request patient must match selected patient')
        refs = self._refs(patient_id, data.pop('case_ids', None))
        if 'sources' in data:
            raise ValueError('Select case_ids; the server binds current source hashes')
        data['sources'] = refs
        case_id = identifier(data.get('case_id'), 'case_id')
        request_hash = digest(data)
        existing = False
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM wb_careflow WHERE case_id=?', (case_id,)).fetchone()
            if row:
                if row['patient_id'] != patient_id or row['request_hash'] != request_hash:
                    raise VersionConflict('Request ID already belongs to different immutable intake data')
                existing = True
            else:
                # Reserve ownership before the remote mutation. A lost response
                # cannot leave an unowned request or authorize duplicate creation.
                db.execute('INSERT INTO wb_careflow(case_id,patient_id,source_case_ids,source_versions,status,error,created_at,updated_at,request_hash) VALUES(?,?,?,?,?,?,?,?,?)',
                    (case_id, patient_id, json.dumps([r['case_id'] for r in refs]),
                     json.dumps({r['case_id']: r['version'] for r in refs}), 'creating', None, now(), now(), request_hash))
                self._event(db, patient_id, 'careflow_intake_reserved', {'case_id': case_id, 'sources': refs,
                    'request_hash': request_hash, 'request': data['request'], 'model_calls': 0})
        try:
            if existing:
                # Recovery reads the committed request and audit; it never retries
                # a remote create whose outcome is unknown.
                detail = self.cf_detail(patient_id, case_id)
                audit = self._cf('/v1/cases/' + quote(case_id, safe='') + '/audit')
                events = audit.get('events', [])
                imported = next((e['payload'] for e in events if e.get('event_type') == 'SHARED_EVIDENCE_IMPORTED'), None)
                identities = [{k: r[k] for k in ('case_id', 'version', 'content_hash')} for r in (imported or {}).get('sources', [])]
                if not imported or identities != refs or detail['packet']['request'] != data['request']:
                    raise ValueError('Remote request recovery could not confirm original identity/source bindings')
                result = {'packet': detail['packet'], 'shared_evidence_receipt': imported, 'recovered': True, 'model_calls': 0}
            else:
                result = self._cf('/v1/shared-intake', data)
        except ValueError as exc:
            self._cf_stale(patient_id, case_id, str(exc), status='uncertain')
            raise
        with self.connect() as db:
            db.execute("UPDATE wb_careflow SET status='current',error=NULL,updated_at=? WHERE case_id=?", (now(), case_id))
            self._event(db, patient_id, 'careflow_shared_intake', {'case_id': case_id, 'sources': refs, 'model_calls': 0, 'recovered': existing})
        self._cf_summary(case_id, result['packet'])
        return result

    def cf_detail(self, patient_id, case_id):
        binding = next((r for r in self.cf_requests(patient_id)['requests'] if r['case_id'] == case_id), None)
        if binding is None:
            raise KeyError('CareFlow case does not belong to this workspace')
        result = self._cf('/v1/cases/' + quote(case_id, safe=''))
        if result.get('request', {}).get('patient_id') != patient_id:
            raise ValueError('CareFlow response patient identity differs from saved workspace binding')
        self._cf_summary(case_id, result)
        return {'packet': result, 'shared_binding': binding}

    def cf_action(self, patient_id, case_id, action, body):
        detail = self.cf_detail(patient_id, case_id)
        if action == 'sync-shared':
            try:
                return self._sync(patient_id, case_id, detail, body.get('reason', 'Refresh from saved patient evidence'))
            except ValueError as exc:
                self._cf_stale(patient_id, case_id, str(exc))
                raise
        paths = {'documents': 'documents', 'recalculate': 'recalculate', 'reviews': 'reviews'}
        if action not in paths:
            raise ValueError('Unsupported CareFlow operation')
        result = self._cf('/v1/cases/' + quote(case_id, safe='') + '/' + paths[action], body)
        self._cf_summary(case_id, result.get('packet', result))
        return result

    def _cf_summary(self, case_id, packet):
        with self.connect() as db:
            db.execute('UPDATE wb_careflow SET revision=?,readiness=? WHERE case_id=?',
                       (packet.get('revision'), packet.get('readiness'), case_id))

    def _sync(self, patient_id, case_id, detail, reason):
        refs = self._refs(patient_id, detail['shared_binding']['source_case_ids'])
        packet = detail['packet']
        refreshed_at = now()
        result = self._cf('/v1/cases/' + quote(case_id, safe='') + '/sync-shared', {
            'expected_revision': packet['revision'], 'basis_packet_sha256': packet['packet_sha256'],
            'sources': refs, 'received_at': refreshed_at[:10], 'review_as_of': refreshed_at[:10],
            'actor_id': 'patient-workbench', 'reason': reason})
        with self.connect() as db:
            db.execute("UPDATE wb_careflow SET source_versions=?,status='current',error=NULL,updated_at=? WHERE case_id=?",
                       (json.dumps({r['case_id']: r['version'] for r in refs}), now(), case_id))
            self._event(db, patient_id, 'careflow_evidence_synchronized', {'case_id': case_id, 'sources': refs, 'model_calls': 0})
        self._cf_summary(case_id, result['packet'])
        return result

    def _cf_stale(self, patient_id, case_id, error, status='stale'):
        with self.connect() as db:
            db.execute('UPDATE wb_careflow SET status=?,error=?,updated_at=? WHERE case_id=?', (status, error, now(), case_id))
            self._event(db, patient_id, 'careflow_sync_failed', {'case_id': case_id, 'error': error, 'status': status})

    def sync_dependents(self, patient_id, source_case_id):
        results = []
        for binding in self.cf_requests(patient_id)['requests']:
            if source_case_id not in binding['source_case_ids']:
                continue
            case_id = binding['case_id']
            try:
                result = self._sync(patient_id, case_id, self.cf_detail(patient_id, case_id), 'Source fact correction saved')
                results.append({'case_id': case_id, 'status': 'current', 'result': result})
            except (ValueError, KeyError) as exc:
                self._cf_stale(patient_id, case_id, str(exc))
                results.append({'case_id': case_id, 'status': 'stale', 'error': str(exc)})
        return results

    def audit(self, patient_id):
        self.patient(patient_id)
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM wb_events WHERE patient_id=? ORDER BY sequence', (patient_id,))]
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return {'events': rows}
