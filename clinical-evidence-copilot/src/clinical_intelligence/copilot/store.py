"""Append-only SQLite snapshots with optimistic concurrency and hash chaining."""
import sqlite3
from pathlib import Path

from .models import Packet


class VersionConflict(ValueError):
    pass


def validate_verified_revision(old, packet, record):
    """Permit an audited source correction while retaining original extraction bytes."""
    if packet.extraction_metadata.get('soap_projection_version') != 'soap/v5':
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
                verified_revision = old.extraction_metadata.get('soap_projection_version') == 'soap/v5'
                if verified_revision:
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
        previous = None
        for i, row in enumerate(rows, 1):
            p = Packet.model_validate_json(row[3]).verify()
            if row[0] != i or p.version != i or p.content_hash != row[1] or p.parent_hash != row[2] or p.parent_hash != previous:
                raise ValueError('Version chain integrity mismatch')
            previous = p.content_hash
        return p

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
