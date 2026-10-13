"""Cross-process Luna slots. Uncertain reservations never expire silently."""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from ..models import now


class ConcurrencyBlocked(RuntimeError):
    pass


class LunaSlots:
    def __init__(self,path,*,app='copilot',global_limit=50,app_limit=25):
        if not 1<=global_limit<=50 or not 1<=app_limit<=25:
            raise ValueError('Until joint adoption, limits must be global <=50 and app <=25')
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.app=app; self.global_limit=global_limit; self.app_limit=app_limit
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS slots (request_key TEXT PRIMARY KEY,app TEXT NOT NULL,started_at TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.path,timeout=30)

    def acquire(self,key):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM slots WHERE request_key=?',(key,)).fetchone():
                raise ConcurrencyBlocked('Request has an existing active/uncertain slot')
            all_count=db.execute('SELECT COUNT(*) FROM slots').fetchone()[0]
            app_count=db.execute('SELECT COUNT(*) FROM slots WHERE app=?',(self.app,)).fetchone()[0]
            if all_count>=self.global_limit or app_count>=self.app_limit: return False
            db.execute('INSERT INTO slots VALUES (?,?,?)',(key,self.app,now()))
            return True

    def release(self,key):
        with self.connect() as db:
            db.execute('DELETE FROM slots WHERE request_key=? AND app=?',(key,self.app))

    def active(self):
        with self.connect() as db:
            return [dict(zip(('request_key','app','started_at'),r)) for r in db.execute('SELECT * FROM slots')]

    @contextmanager
    def hold(self,key,timeout=60):
        start=time.monotonic()
        while not self.acquire(key):
            if time.monotonic()-start>timeout: raise ConcurrencyBlocked('Luna slots unavailable; inspect active request owners before recovery')
            time.sleep(.1)
        try: yield
        finally: self.release(key)
