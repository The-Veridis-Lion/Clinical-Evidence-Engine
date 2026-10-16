"""Append-only SQLite snapshots with optimistic concurrency and hash chaining."""
import sqlite3
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from .models import Packet


class VersionConflict(ValueError):
    pass


def validate_verified_revision(old, packet, record):
    """Permit an audited source correction while retaining original extraction bytes."""
    projection=old.extraction_metadata.get('soap_projection_version')
    if projection not in {'soap/v5','soap/v6'} or packet.extraction_metadata.get('soap_projection_version') != projection:
        raise ValueError('Cannot change the projection contract during a review')
    original_ids = [f.fact_id for f in old.facts]
    if [f.fact_id for f in packet.facts[:len(old.facts)]] != original_ids:
        raise ValueError('Original fact order and identities cannot change')
    if [f.original_fact for f in packet.facts[:len(old.facts)]] != [f.original_fact for f in old.facts]:
        raise ValueError('Original fact proposals cannot be overwritten')
    before = next((f for f in old.facts if f.fact_id == record.fact_id), None)
    after = next((f for f in packet.facts if f.fact_id == record.fact_id), None)
    if (after is None or record.base_version != old.version or record.applied_version != packet.version
            or record.after != after.assertion.model_dump()):
        raise ValueError('Review record does not describe the saved revision')
    if before is None:
        if (len(packet.facts) != len(old.facts)+1 or packet.facts[-1].fact_id != record.fact_id
                or record.before != {} or record.action != 'correct'):
            raise ValueError('An omission adds exactly one independently audited fact')
        previous = old.extraction_metadata.get('omission_corrections', [])
        events = packet.extraction_metadata.get('omission_corrections', [])
        if events[:len(previous)] != previous or len(events) != len(previous)+1:
            raise ValueError('Omission history must be append-only')
        candidate_id = events[-1]['candidate_claim_id']
        from .augmentation import candidates, candidate_fact_identity
        candidate = next((c for c in candidates(old) if c['assertion']['claim_id'] == candidate_id), None)
        if (events[-1]['added_fact_id'] != record.fact_id or events[-1]['version'] != packet.version
                or candidate is None or events[-1].get('source_hash') != old.source.sha256
                or events[-1].get('original_model_output_unchanged') is not True):
            raise ValueError('Omission must name a current original-source candidate')
        from .evidence import ground_fact
        assertion, spans = ground_fact(after.assertion.model_dump(), old.source)
        if (after.fact_id != candidate_fact_identity(old,candidate,assertion,spans)
                or after.original_fact != assertion.model_dump()
                or record.evidence_ids != after.evidence_ids
                or record.replacement != assertion.model_dump()):
            raise ValueError('Omission audit and appended fact must have the same source identity')
        proof = next(r for r in packet.extraction_metadata['evidence_verification']['assertions']
                     if r['fact_id'] == record.fact_id)
        if proof['result']['status'] != 'SUPPORTED_BY_SOURCE':
            raise ValueError('Added omission needs full source support')
    elif len(packet.facts) != len(old.facts) or record.before != before.assertion.model_dump():
        raise ValueError('Existing fact correction cannot add unlogged assertions')
    if [f.model_dump() for f in old.facts if f.fact_id != record.fact_id] != [
            f.model_dump() for f in packet.facts if f.fact_id != record.fact_id]:
        raise ValueError('Unlogged change outside the correction target')
    if record.action != 'correct' and record.before != record.after:
        raise ValueError('Only a correction can change an assertion')
    derived = {'evidence_verification','semantic_detector_candidates'}
    if record.correction_contract_version is not None:
        from .semantics import citation_preservation_review
        if not citation_preservation_review(old, record):
            raise ValueError('Citation preservation only applies to an exact citation-only correction')
    if packet.extraction_metadata.get('review_workflow') != old.extraction_metadata.get('review_workflow'):
        from .reviewer import workflow_marker, validate_review_workflow
        if (old.extraction_metadata.get('review_workflow') is not None
                or record.action != 'accept' or record.reviewer.reviewer_type != 'human'
                or packet.extraction_metadata.get('review_workflow') != workflow_marker(record)):
            raise ValueError('Human review workflow may only begin with its explicit new acceptance')
        validate_review_workflow(packet)
        derived.add('review_workflow')
    old_semantic_events=old.extraction_metadata.get('semantic_corrections',[])
    semantic_events=packet.extraction_metadata.get('semantic_corrections',[])
    if semantic_events != old_semantic_events:
        from .semantics import checked_records
        if (projection != 'soap/v6' or before is None or record.action != 'correct'
                or record.before != record.after or record.replacement != record.before
                or semantic_events[:len(old_semantic_events)] != old_semantic_events
                or len(semantic_events) != len(old_semantic_events)+1):
            raise ValueError('Typed semantic correction requires one append-only audit event')
        event=semantic_events[-1]
        previous=checked_records(old);current=checked_records(packet)
        if (event.get('review_id') != record.review_id or event.get('version') != packet.version
                or event.get('fact_id') != record.fact_id or event.get('source_sha256') != old.source.sha256
                or event.get('original_clinical_fact_unchanged') is not True
                or event.get('before') != previous.get(record.fact_id)
                or event.get('after') != current.get(record.fact_id)
                or {k:v for k,v in previous.items() if k!=record.fact_id} != {k:v for k,v in current.items() if k!=record.fact_id}):
            raise ValueError('Typed semantic audit must bind the exact target/source/version')
        derived |= {'clinical_semantics_v2','semantic_corrections','atomic_source_checklist'}
    if before is None:
        derived |= {'atomic_source_checklist','action_state_checklist','omission_corrections'}
    if {k:v for k,v in old.extraction_metadata.items() if k not in derived} != {
            k:v for k,v in packet.extraction_metadata.items() if k not in derived}:
        raise ValueError('Original extraction metadata cannot change during correction')
    if (packet.extraction_metadata['evidence_verification']['configuration'] !=
            old.extraction_metadata['evidence_verification']['configuration']):
        raise ValueError('A correction cannot silently replace the frozen verification configuration')


class CaseStore:
    def __init__(self, path):
        self.path = Path(path)
        # Exact SQLite rows are immutable snapshots. Keep only a few previously
        # verified reads; callers always receive independent packet objects.
        self._verified_reads = OrderedDict()
        self._verified_lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS versions (
                    case_id TEXT NOT NULL, version INTEGER NOT NULL,
                    patient_id TEXT NOT NULL, source_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL, parent_hash TEXT,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (case_id, version));
                CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON versions
                    BEGIN SELECT RAISE(ABORT, 'Versions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON versions
                    BEGIN SELECT RAISE(ABORT, 'Versions are immutable'); END;
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, packet, *, expected_version):
        packet.verify()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            last = db.execute('SELECT version, content_hash, source_hash, patient_id, payload FROM versions WHERE case_id=? ORDER BY version DESC LIMIT 1', (packet.case_id,)).fetchone()
            actual = last[0] if last else 0
            if actual != expected_version or packet.version != expected_version + 1:
                raise VersionConflict(f'Case version changed: expected {expected_version}, current {actual}')
            if last:
                old = Packet.model_validate_json(last[4]).verify()
                if packet.parent_hash != last[1] or packet.source != old.source or packet.patient_id != last[3]:
                    raise ValueError('Source/patient identity and parent hash must remain unchanged')
                verified_revision = old.extraction_metadata.get('soap_projection_version') in {'soap/v5','soap/v6'}
                from .reprocessing import EVENTS, validate_program_revision
                program_revision = packet.extraction_metadata.get(EVENTS, []) != old.extraction_metadata.get(EVENTS, [])
                if program_revision:
                    validate_program_revision(old, packet)
                elif verified_revision:
                    if packet.reviews[:len(old.reviews)] != old.reviews or len(packet.reviews) != len(old.reviews)+1:
                        raise ValueError('Review history cannot be overwritten')
                    validate_verified_revision(old, packet, packet.reviews[-1])
                    if packet.relationships != old.relationships or packet.rejected_facts != old.rejected_facts:
                        raise ValueError('Original relationship and rejection history cannot change')
                    if any(e not in packet.evidence for e in old.evidence):
                        raise ValueError('Original evidence cannot be removed')
                else:
                    self.validate_legacy_revision(old, packet)
            elif packet.parent_hash is not None:
                raise ValueError('First version cannot have a parent')
            elif packet.reviews:
                raise ValueError('First version cannot contain unlinked review history')
            elif packet.extraction_metadata.get('program_reprocessing_events'):
                raise ValueError('First version cannot contain unlinked program history')
            db.execute('INSERT INTO versions VALUES (?,?,?,?,?,?,?,?)',
                (packet.case_id, packet.version, packet.patient_id, packet.source.sha256, packet.content_hash,
                 packet.parent_hash, packet.created_at, packet.model_dump_json()))
        return packet

    @staticmethod
    def validate_legacy_revision(old, packet):
                if [f.original_fact for f in old.facts] != [f.original_fact for f in packet.facts]:
                    raise ValueError('Original fact proposals cannot be overwritten')
                if packet.reviews[:len(old.reviews)] != old.reviews or len(packet.reviews) != len(old.reviews)+1:
                    raise ValueError('Review history cannot be overwritten')
                record = packet.reviews[-1]
                before = next((f for f in old.facts if f.fact_id == record.fact_id), None)
                after = next((f for f in packet.facts if f.fact_id == record.fact_id), None)
                if before is None or after is None or record.base_version != old.version or record.applied_version != packet.version or record.before != before.assertion.model_dump() or record.after != after.assertion.model_dump():
                    raise ValueError('Version must match its review before/after record')
                if [f.model_dump() for f in old.facts if f.fact_id != record.fact_id] != [f.model_dump() for f in packet.facts if f.fact_id != record.fact_id]:
                    raise ValueError('Unlogged fact change outside the review target')
                if record.action != 'correct' and record.before != record.after:
                    raise ValueError('Only a correction review can change an assertion')
                if packet.extraction_metadata != old.extraction_metadata or packet.relationships != old.relationships or packet.rejected_facts != old.rejected_facts:
                    raise ValueError('Extraction history cannot change during review')
                if any(e not in packet.evidence for e in old.evidence):
                    raise ValueError('Original evidence cannot be removed during review')

    def get(self, case_id, version=None):
        with self.connect() as db:
            rows = db.execute('SELECT version, content_hash, parent_hash, payload FROM versions WHERE case_id=? AND (? IS NULL OR version<=?) ORDER BY version', (case_id, version, version)).fetchall()
        if not rows or (version is not None and rows[-1][0] != version):
            raise KeyError('Case/version not found')
        # Read the database on every request. The complete original row values,
        # including payload text and chain headers, form the cache identity.
        previous = None
        for i, row in enumerate(rows, 1):
            if row[0] != i or row[2] != previous:
                raise ValueError('Version chain integrity mismatch')
            previous = row[1]
        key = (str(self.path.resolve()), case_id, tuple(rows))
        with self._verified_lock:
            cached = self._verified_reads.get(key)
            if cached is not None:
                self._verified_reads.move_to_end(key)
                return cached.model_copy(deep=True)
        previous = None
        for i, row in enumerate(rows, 1):
            p = Packet.model_validate_json(row[3]).verify()
            if row[0] != i or p.version != i or p.content_hash != row[1] or p.parent_hash != row[2] or p.parent_hash != previous:
                raise ValueError('Version chain integrity mismatch')
            previous = p.content_hash
        with self._verified_lock:
            self._verified_reads[key] = p
            self._verified_reads.move_to_end(key)
            if len(self._verified_reads) > 8:
                self._verified_reads.popitem(last=False)
        return p.model_copy(deep=True)

    def history(self, case_id):
        with self.connect() as db:
            rows = db.execute('SELECT version, content_hash, parent_hash, created_at FROM versions WHERE case_id=? ORDER BY version', (case_id,)).fetchall()
        return [dict(zip(('version', 'content_hash', 'parent_hash', 'created_at'), r)) for r in rows]

    def list_cases(self):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM versions v WHERE version=(SELECT MAX(version) FROM versions WHERE case_id=v.case_id) ORDER BY created_at DESC').fetchall()
        result = []
        for row in rows:
            p = Packet.model_validate_json(row[0]).verify()
            result.append({'case_id': p.case_id, 'patient_id': p.patient_id, 'version': p.version,
                'encounter_time': p.source.encounter_time, 'facts': len(p.facts),
                'review_required': len(p.review_required_fact_ids), 'extraction_status': p.extraction_status})
        return result
