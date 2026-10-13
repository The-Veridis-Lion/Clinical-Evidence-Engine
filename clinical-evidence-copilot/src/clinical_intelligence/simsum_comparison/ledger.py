"""Append-only stage/document ledger; atomic global and per-batch budget reservation."""
import json
import sqlite3
from datetime import datetime, timezone
from .contract import CONFIG

def now():
    return datetime.now(timezone.utc).isoformat()

class Ledger:
    def __init__(self, path, identity, *, total_cap=2000, batch_cap=600):
        self.path, self.total_cap, self.batch_cap = path, total_cap, batch_cap
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS identity (id INTEGER PRIMARY KEY CHECK(id=1), content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    stage TEXT NOT NULL, document_id TEXT NOT NULL, attempt INTEGER NOT NULL CHECK(attempt IN (1,2)),
                    batch TEXT NOT NULL, input_hash TEXT NOT NULL, status TEXT NOT NULL,
                    reserved_at TEXT NOT NULL, ended_at TEXT, latency REAL, usage TEXT, error TEXT, raw_hash TEXT,
                    PRIMARY KEY(stage,document_id,attempt));
                CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON requests BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS terminal BEFORE UPDATE ON requests WHEN OLD.status!='reserved'
                    BEGIN SELECT RAISE(ABORT,'terminal immutable'); END;
                CREATE TRIGGER IF NOT EXISTS fixed_identity BEFORE UPDATE ON requests
                    WHEN NEW.stage!=OLD.stage OR NEW.document_id!=OLD.document_id OR NEW.attempt!=OLD.attempt
                    OR NEW.input_hash!=OLD.input_hash OR NEW.batch!=OLD.batch OR NEW.reserved_at!=OLD.reserved_at
                    BEGIN SELECT RAISE(ABORT,'identity immutable'); END;
                CREATE TRIGGER IF NOT EXISTS identity_update BEFORE UPDATE ON identity BEGIN SELECT RAISE(ABORT,'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS identity_delete BEFORE DELETE ON identity BEGIN SELECT RAISE(ABORT,'immutable'); END;
            """)
            content = json.dumps({"identity": identity, "total_cap": total_cap, "batch_cap": batch_cap}, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO identity VALUES (1,?)", (content,))
            if db.execute("SELECT content FROM identity").fetchone()[0] != content:
                raise ValueError("Frozen ledger configuration changed")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=60)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def rows(self):
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM requests ORDER BY reserved_at,stage,document_id,attempt")]

    def reserve(self, stage, doc, attempt, batch, input_hash):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM requests WHERE stage=? AND document_id=? AND attempt=?",
                                  (stage, doc, attempt)).fetchone()
            if existing:
                if existing["input_hash"] != input_hash or existing["batch"] != batch:
                    raise ValueError("Previously dispatched input changed")
                return False
            if stage.startswith("extract_") and db.execute(
                    "SELECT 1 FROM requests WHERE document_id=? AND input_hash=? AND stage!=? AND stage LIKE 'extract_%'",
                    (doc,input_hash,stage)).fetchone():
                raise ValueError("Identical Extract input already dispatched in another stage; reuse its outcome, including failure")
            if attempt == 2:
                previous = db.execute("SELECT status,input_hash FROM requests WHERE stage=? AND document_id=? AND attempt=1",
                                      (stage, doc)).fetchone()
                if not previous or previous["status"] != "invalid" or previous["input_hash"] != input_hash:
                    raise ValueError("Only genuine structural failure permits one identical-input retry")
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= self.total_cap:
                raise RuntimeError("Global dispatch budget exhausted")
            if db.execute("SELECT COUNT(*) FROM requests WHERE batch=?", (batch,)).fetchone()[0] >= self.batch_cap:
                raise RuntimeError("Batch dispatch budget exhausted")
            db.execute("INSERT INTO requests(stage,document_id,attempt,batch,input_hash,status,reserved_at) VALUES (?,?,?,?,?,'reserved',?)",
                       (stage,doc,attempt,batch,input_hash,now()))
            return True

    def finish(self, stage, doc, attempt, status, latency, usage, error, raw_hash):
        if status not in {"valid", "invalid", "failed"}:
            raise ValueError("Unknown completion status")
        with self.connect() as db:
            updated = db.execute("UPDATE requests SET status=?,ended_at=?,latency=?,usage=?,error=?,raw_hash=? "
                "WHERE stage=? AND document_id=? AND attempt=? AND status='reserved'",
                (status,now(),latency,json.dumps(usage),error,raw_hash,stage,doc,attempt)).rowcount
            if updated != 1:
                raise ValueError("Request is not reserved")
