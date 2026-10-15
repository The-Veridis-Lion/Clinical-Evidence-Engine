"""Transactional append-only revisions and separately retained review events."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from ..claims_review.prepare import digest


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS revisions (
                    case_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    case_json TEXT NOT NULL, packet_json TEXT NOT NULL,
                    PRIMARY KEY (case_id, revision)
                );
                CREATE TABLE IF NOT EXISTS events (
                    case_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL, event_sha256 TEXT NOT NULL,
                    PRIMARY KEY (case_id, sequence)
                );
                CREATE TRIGGER IF NOT EXISTS revisions_no_update BEFORE UPDATE ON revisions
                    BEGIN SELECT RAISE(ABORT, 'immutable revisions'); END;
                CREATE TRIGGER IF NOT EXISTS revisions_no_delete BEFORE DELETE ON revisions
                    BEGIN SELECT RAISE(ABORT, 'immutable revisions'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
            ''')

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load(self, conn, case_id, revision=None):
        if revision is None:
            row = conn.execute('SELECT * FROM revisions WHERE case_id=? ORDER BY revision DESC LIMIT 1',
                               (case_id,)).fetchone()
        else:
            row = conn.execute('SELECT * FROM revisions WHERE case_id=? AND revision=?',
                               (case_id, revision)).fetchone()
        if row is None:
            raise KeyError('Case/revision not found')
        return json.loads(row['case_json']), json.loads(row['packet_json'])

    def append_revision(self, conn, case, packet):
        conn.execute('INSERT INTO revisions VALUES (?, ?, ?, ?)',
                     (case.case_id, packet['revision'], encoded(case.model_dump(mode='json')), encoded(packet)))

    def append_event(self, conn, case_id, event_type, payload):
        last = conn.execute('SELECT sequence,event_sha256 FROM events WHERE case_id=? ORDER BY sequence DESC LIMIT 1',
                            (case_id,)).fetchone()
        event = {'case_id': case_id, 'sequence': last['sequence'] + 1 if last else 1,
                 'event_type': event_type, 'timestamp': datetime.now(timezone.utc).isoformat(),
                 'previous_sha256': last['event_sha256'] if last else None, 'payload': payload}
        event_hash = digest(event)
        conn.execute('INSERT INTO events VALUES (?, ?, ?, ?)',
                     (case_id, event['sequence'], encoded(event), event_hash))
        return {**event, 'event_sha256': event_hash}

    def audit(self, case_id):
        with self.connect() as conn:
            self.load(conn, case_id)
            rows = conn.execute('SELECT * FROM events WHERE case_id=? ORDER BY sequence', (case_id,)).fetchall()
            revisions = conn.execute('SELECT * FROM revisions WHERE case_id=? ORDER BY revision', (case_id,)).fetchall()
        events, errors, previous = [], [], None
        recorded_revisions = {}
        for sequence, row in enumerate(rows, 1):
            event = json.loads(row['event_json'])
            if (event['previous_sha256'] != previous or digest(event) != row['event_sha256']
                    or event['sequence'] != sequence or row['sequence'] != sequence or event['case_id'] != case_id):
                errors.append(f'Invalid event chain at sequence {sequence}')
            previous = row['event_sha256']
            events.append({**event, 'event_sha256': previous})
            if event['event_type'] in {'CASE_CREATED', 'EVIDENCE_ADDED', 'FACT_CORRECTED', 'PROGRAM_RECALCULATED'}:
                recorded_revisions[event['payload']['revision']] = event['payload']
        if set(recorded_revisions) != {r['revision'] for r in revisions}:
            errors.append('Revision/event coverage mismatch')
        for expected, row in enumerate(revisions, 1):
            case, packet = json.loads(row['case_json']), json.loads(row['packet_json'])
            saved = recorded_revisions.get(row['revision'], {})
            packet_body = {k: v for k, v in packet.items() if k != 'packet_sha256'}
            if (row['revision'] != expected or packet['revision'] != expected
                    or packet['case_id'] != case_id or case['case_id'] != case_id
                    or digest(case) != packet['input_sha256']
                    or digest(packet_body) != packet['packet_sha256']
                    or saved.get('packet_sha256') != packet['packet_sha256']
                    or saved.get('input_sha256') != packet['input_sha256']):
                errors.append(f'Revision integrity mismatch: {row["revision"]}')
        return {'case_id': case_id, 'verified': not errors, 'errors': errors, 'events': events,
                'head_sha256': previous, 'revision_count': len(revisions),
                'integrity_limit': 'Local hash-chain verification, not an external signature or tamper-proof ledger.'}
