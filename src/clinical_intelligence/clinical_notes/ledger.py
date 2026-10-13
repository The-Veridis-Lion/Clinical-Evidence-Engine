"""Durable at-most-once dispatch reservations; ambiguous interrupted rows never replay."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path: Path, identity: dict, documents, *, ceiling=600):
        self.path, self.ceiling = path, ceiling
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS selected (document_id TEXT PRIMARY KEY, note_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    document_id TEXT REFERENCES selected(document_id), attempt INTEGER NOT NULL CHECK(attempt IN (1,2)),
                    status TEXT NOT NULL, reserved_at TEXT NOT NULL, ended_at TEXT,
                    latency_seconds REAL, usage TEXT, error TEXT, raw_sha256 TEXT,
                    PRIMARY KEY(document_id, attempt));
                CREATE TRIGGER IF NOT EXISTS no_delete_requests BEFORE DELETE ON requests
                    BEGIN SELECT RAISE(ABORT, 'request history cannot be deleted'); END;
                CREATE TRIGGER IF NOT EXISTS no_repeat_completion BEFORE UPDATE ON requests
                    WHEN OLD.status != 'reserved'
                    BEGIN SELECT RAISE(ABORT, 'terminal request is immutable'); END;
            """)
            db.execute("BEGIN IMMEDIATE")
            encoded = json.dumps({**identity, "ceiling": ceiling}, sort_keys=True)
            stored = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if stored and stored[0] != encoded:
                raise ValueError("Ledger identity/config changed")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('identity', ?)", (encoded,))
            expected = {d.document_id: d.note_sha256 for d in documents}
            existing = dict(db.execute("SELECT * FROM selected"))
            if existing and existing != expected:
                raise ValueError("Ledger selection changed")
            if len(expected) != len(documents) or len(expected) > ceiling:
                raise ValueError("Duplicate documents or selection exceeds ceiling")
            db.executemany("INSERT OR IGNORE INTO selected VALUES (?,?)", expected.items())

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def reserve(self, document, attempt=1):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT note_sha256 FROM selected WHERE document_id=?", (document.document_id,)).fetchone()
            if not row or row[0] != document.note_sha256:
                raise ValueError("Document is not in frozen ledger selection")
            if attempt not in (1, 2):
                raise ValueError("At most one structural retry")
            if attempt == 2:
                previous = db.execute("SELECT status FROM requests WHERE document_id=? AND attempt=1",
                                      (document.document_id,)).fetchone()
                if not previous or previous[0] != "invalid":
                    raise ValueError("Only a structurally invalid first response may be retried")
            if db.execute("SELECT 1 FROM requests WHERE document_id=? AND attempt=?", (document.document_id, attempt)).fetchone():
                return False
            if db.execute("SELECT count(*) FROM requests").fetchone()[0] >= self.ceiling:
                raise ValueError("Dispatch ceiling reached")
            db.execute("INSERT INTO requests(document_id,attempt,status,reserved_at) VALUES (?,?,'reserved',?)",
                       (document.document_id, attempt, now()))
        return True

    def finish(self, document_id, status, *, attempt=1, latency, usage=None, error=None, raw_sha256=None):
        if status not in {"valid", "invalid", "failed"}:
            raise ValueError("Invalid terminal status")
        with self.connect() as db:
            cursor = db.execute("UPDATE requests SET status=?,ended_at=?,latency_seconds=?,usage=?,error=?,raw_sha256=? "
                       "WHERE document_id=? AND attempt=? AND status='reserved'", (status, now(), latency,
                        json.dumps(usage) if usage is not None else None, error, raw_sha256, document_id, attempt))
            if cursor.rowcount != 1:
                raise ValueError("Missing reservation or request already terminal")

    def rows(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY document_id,attempt")]
