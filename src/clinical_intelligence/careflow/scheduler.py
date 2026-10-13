"""Cross-process shared reservations with conservative project caps and no replay."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .evaluation.corpus import canonical

RETRYABLE = {'UPSTREAM_FAILURE', 'PARSE_FAILURE', 'MECHANICAL_FAILURE'}
TERMINAL = RETRYABLE | {'SUCCESS', 'SEMANTIC_DISAGREEMENT', 'UNRESOLVED_DISPATCH'}


class SlotBusy(RuntimeError):
    pass


class CallLedger:
    def __init__(self, path, *, global_limit=None, project_limit=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS configuration (singleton INTEGER PRIMARY KEY CHECK(singleton=1), content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (
                    uid TEXT PRIMARY KEY, run_id TEXT NOT NULL, project TEXT NOT NULL, document_id TEXT NOT NULL,
                    model TEXT NOT NULL, purpose TEXT NOT NULL, attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 3),
                    payload_sha256 TEXT NOT NULL, status TEXT NOT NULL, reserved_at TEXT NOT NULL,
                    ended_at TEXT, usage TEXT, error TEXT,
                    UNIQUE(run_id,project,document_id,model,purpose,attempt)
                );
                CREATE TRIGGER IF NOT EXISTS calls_no_delete BEFORE DELETE ON calls
                    BEGIN SELECT RAISE(ABORT,'immutable call attempts'); END;
                CREATE TRIGGER IF NOT EXISTS calls_terminal BEFORE UPDATE ON calls WHEN OLD.status!='RESERVED'
                    BEGIN SELECT RAISE(ABORT,'immutable terminal call'); END;
                CREATE TRIGGER IF NOT EXISTS calls_identity BEFORE UPDATE ON calls WHEN
                    NEW.uid!=OLD.uid OR NEW.run_id!=OLD.run_id OR NEW.project!=OLD.project
                    OR NEW.document_id!=OLD.document_id OR NEW.model!=OLD.model OR NEW.purpose!=OLD.purpose
                    OR NEW.attempt!=OLD.attempt OR NEW.payload_sha256!=OLD.payload_sha256 OR NEW.reserved_at!=OLD.reserved_at
                    BEGIN SELECT RAISE(ABORT,'immutable call identity'); END;
                CREATE TRIGGER IF NOT EXISTS configuration_no_update BEFORE UPDATE ON configuration
                    BEGIN SELECT RAISE(ABORT,'immutable call limits'); END;
                CREATE TRIGGER IF NOT EXISTS configuration_no_delete BEFORE DELETE ON configuration
                    BEGIN SELECT RAISE(ABORT,'immutable call limits'); END;
            ''')
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT content FROM configuration WHERE singleton=1').fetchone()
            requested = {'global_limit': global_limit or 50, 'project_limit': project_limit or 25, 'research_attempt_cap': 100}
            if not 1 <= requested['project_limit'] <= 25 or not 1 <= requested['global_limit'] <= 50:
                raise ValueError('Global cap <=50 and per-project cap <=25 required')
            if old:
                settings = json.loads(old['content'])
                if ((global_limit is not None and global_limit != settings['global_limit'])
                        or (project_limit is not None and project_limit != settings['project_limit'])):
                    raise ValueError('Shared scheduler limits differ from frozen configuration')
            else:
                settings = requested
                db.execute('INSERT INTO configuration VALUES (1,?)', (canonical(settings),))
            self.settings = settings

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(self, run_id, project, document_id, model, purpose, *, payload_sha256):
        if purpose not in {'product_extraction', 'product_review', 'research'}:
            raise ValueError('Explicit call purpose required')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT * FROM calls WHERE run_id=? AND project=? AND document_id=? AND model=? AND purpose=? ORDER BY attempt',
                              (run_id, project, document_id, model, purpose)).fetchall()
            if rows and rows[-1]['status'] not in RETRYABLE:
                raise ValueError('No retry for success, semantic disagreement or uncertain/reserved dispatch')
            if len(rows) >= 3:
                raise ValueError('Two-extra-retry cap exhausted; retain all failed attempts')
            active = db.execute("SELECT project,COUNT(*) n FROM calls WHERE status='RESERVED' GROUP BY project").fetchall()
            if (sum(row['n'] for row in active) >= self.settings['global_limit']
                    or next((row['n'] for row in active if row['project'] == project), 0) >= self.settings['project_limit']):
                raise SlotBusy('Shared/project model slots are occupied; no call reserved')
            if purpose == 'research' and db.execute("SELECT COUNT(*) FROM calls WHERE project=? AND purpose='research'", (project,)).fetchone()[0] >= 100:
                raise ValueError('Research attempt budget exhausted')
            token = {'uid': str(uuid.uuid4()), 'run_id': run_id, 'project': project, 'document_id': document_id,
                     'model': model, 'purpose': purpose, 'attempt': len(rows) + 1, 'payload_sha256': payload_sha256,
                     'status': 'RESERVED', 'reserved_at': datetime.now(timezone.utc).isoformat()}
            db.execute('INSERT INTO calls(uid,run_id,project,document_id,model,purpose,attempt,payload_sha256,status,reserved_at) '
                       'VALUES (:uid,:run_id,:project,:document_id,:model,:purpose,:attempt,:payload_sha256,:status,:reserved_at)', token)
        return token

    def finish(self, token, status, *, usage=None, error=None):
        if status not in TERMINAL:
            raise ValueError('Unknown terminal model-call status')
        with self.connection() as db:
            count = db.execute("UPDATE calls SET status=?,ended_at=?,usage=?,error=? WHERE uid=? AND status='RESERVED'",
                               (status, datetime.now(timezone.utc).isoformat(), canonical(usage), error, token['uid'])).rowcount
            if count != 1:
                raise ValueError('Attempt is terminal or absent; cannot overwrite/replay')

    def attempts(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM calls ORDER BY reserved_at,uid')]

    def stats(self):
        rows = self.attempts()
        return {'attempts': len(rows), 'reserved': sum(r['status'] == 'RESERVED' for r in rows),
                'success': sum(r['status'] == 'SUCCESS' for r in rows),
                'failures': sum(r['status'] in RETRYABLE for r in rows), 'retries': sum(r['attempt'] > 1 for r in rows),
                'research_attempts': sum(r['purpose'] == 'research' for r in rows),
                'product_extraction_attempts': sum(r['purpose'] == 'product_extraction' for r in rows),
                'product_review_attempts': sum(r['purpose'] == 'product_review' for r in rows),
                'unknown_usage': sum(r['usage'] in {None, 'null'} for r in rows), 'limits': self.settings,
                'participation_limit': 'Global accounting covers participating callers only; per-project cap stays 25 until both projects adopt.'}
