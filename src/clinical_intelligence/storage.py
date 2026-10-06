"""SQLite implementation of the narrow storage boundary.

The evidence is immutable by extraction version. Derived abstractions are replaceable
and invalidated by a digest of all active extraction snapshots for that patient.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Protocol
from .domain import DocumentExtraction, PatientAbstraction, RegisteredDocument


# Clinical logic depends on this interface, not SQLite queries or connection objects.
class Store(Protocol):
    def register(self, name: str, text: str) -> tuple[RegisteredDocument, bool]: ...
    def document(self, document_id: str) -> RegisteredDocument: ...
    def documents(self) -> list[RegisteredDocument]: ...
    def extraction(self, document_id: str, key: str) -> DocumentExtraction | None: ...
    def save_extraction(self, extraction: DocumentExtraction) -> None: ...
    def activate_extraction(self, document_id: str, key: str) -> None: ...
    def save_attempt(self, document_id: str, key: str, status: str, usage: dict | None, error: str | None) -> None: ...
    def mark_failed(self, document_id: str, message: str) -> None: ...
    def patient_ids(self) -> list[str]: ...
    def patient_extractions(self, patient_id: str) -> list[DocumentExtraction]: ...
    def abstraction(self, patient_id: str, input_key: str) -> PatientAbstraction | None: ...
    def save_abstraction(self, abstraction: PatientAbstraction, input_key: str) -> None: ...
    def close(self) -> None: ...


def input_digest(extractions: list[DocumentExtraction], version: str) -> str:
    # A new active extraction or policy version invalidates this patient's derived cache.
    payload = version + "\n" + "\n".join(sorted(x.document_id + ":" + x.extraction_key for x in extractions))
    return hashlib.sha256(payload.encode()).hexdigest()


class SQLiteStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys=ON")
        # Keep originals, versioned claims, replaceable abstractions and attempt logs apart.
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
          names TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL,
          extraction_key TEXT, declared_id TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS extractions (
          document_id TEXT NOT NULL REFERENCES documents(id),
          extraction_key TEXT NOT NULL, patient_id TEXT NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(document_id, extraction_key)
        );
        CREATE INDEX IF NOT EXISTS extractions_patient ON extractions(patient_id);
        CREATE TABLE IF NOT EXISTS abstractions (
          patient_id TEXT PRIMARY KEY, input_key TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attempts (
          attempt_id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
          extraction_key TEXT NOT NULL, status TEXT NOT NULL, usage TEXT, error TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        self.connection.commit()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def register(self, name: str, text: str) -> tuple[RegisteredDocument, bool]:
        # Filenames are aliases; identical text has one registry identity.
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row = self.connection.execute("SELECT id FROM documents WHERE fingerprint=?", (fingerprint,)).fetchone()
        if row:
            document = self.document(row[0])
            if name not in document.source_names:
                document.source_names.append(name)
                with self.connection:
                    self.connection.execute("UPDATE documents SET names=? WHERE id=?",
                                            (json.dumps(sorted(document.source_names)), document.document_id))
            return self.document(row[0]), False
        document = RegisteredDocument(document_id=fingerprint, fingerprint=fingerprint,
                                      source_names=[name], text=text)
        with self.connection:
            self.connection.execute("INSERT INTO documents(id,fingerprint,names,text,status) VALUES(?,?,?,?,?)",
                                    (fingerprint, fingerprint, json.dumps([name]), text, "registered"))
        return document, True

    def document(self, document_id: str) -> RegisteredDocument:
        row = self.connection.execute("SELECT id,fingerprint,names,text,status,extraction_key,declared_id,error FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            raise KeyError(document_id)
        return RegisteredDocument(document_id=row[0], fingerprint=row[1], source_names=json.loads(row[2]),
                                  text=row[3], status=row[4], extraction_key=row[5], declared_id=row[6], error=row[7])

    def documents(self) -> list[RegisteredDocument]:
        return [self.document(row[0]) for row in self.connection.execute("SELECT id FROM documents ORDER BY id").fetchall()]

    def extraction(self, document_id: str, key: str) -> DocumentExtraction | None:
        row = self.connection.execute("SELECT payload FROM extractions WHERE document_id=? AND extraction_key=?", (document_id, key)).fetchone()
        return DocumentExtraction.model_validate_json(row[0]) if row else None

    def save_extraction(self, extraction: DocumentExtraction):
        document = self.document(extraction.document_id)
        # Recheck grounding at the persistence boundary, regardless of extractor behavior.
        for claim in extraction.claims:
            for passage in claim.passages:
                if document.text[passage.start:passage.end] != passage.quote:
                    raise ValueError("Ungrounded claim cannot be persisted")
        # Save the snapshot and activate it in one transaction.
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO extractions VALUES(?,?,?,?)",
                                    (extraction.document_id, extraction.extraction_key, extraction.patient.patient_id,
                                     extraction.model_dump_json()))
            self.connection.execute("UPDATE documents SET status='extracted',extraction_key=?,declared_id=?,error=NULL WHERE id=?",
                                    (extraction.extraction_key, extraction.declared_id, extraction.document_id))

    def activate_extraction(self, document_id: str, key: str):
        extraction = self.extraction(document_id, key)
        if extraction is None:
            raise KeyError((document_id, key))
        with self.connection:
            self.connection.execute("UPDATE documents SET status='extracted',extraction_key=?,declared_id=?,error=NULL WHERE id=?",
                                    (key, extraction.declared_id, document_id))

    def mark_failed(self, document_id: str, message: str):
        # Retain older snapshots for audit, but exclude this failed document from answers.
        with self.connection:
            self.connection.execute("UPDATE documents SET status='failed',error=? WHERE id=?", (message, document_id))

    def save_attempt(self, document_id, key, status, usage, error):
        with self.connection:
            self.connection.execute("INSERT INTO attempts(document_id,extraction_key,status,usage,error) VALUES(?,?,?,?,?)",
                                    (document_id, key, status, json.dumps(usage) if usage else None, error))

    def attempts(self) -> list[dict]:
        rows = self.connection.execute("SELECT document_id,extraction_key,status,usage,error,created_at FROM attempts ORDER BY attempt_id").fetchall()
        return [dict(document_id=r[0], extraction_key=r[1], status=r[2], usage=json.loads(r[3]) if r[3] else None,
                     error=r[4], created_at=r[5]) for r in rows]

    def patient_ids(self) -> list[str]:
        return [row[0] for row in self.connection.execute("""SELECT DISTINCT e.patient_id FROM extractions e
          JOIN documents d ON e.document_id=d.id AND e.extraction_key=d.extraction_key
          WHERE d.status='extracted' ORDER BY e.patient_id""")]

    def patient_extractions(self, patient_id: str) -> list[DocumentExtraction]:
        # Joining on the active key prevents older extraction versions from double counting.
        rows = self.connection.execute("""SELECT e.payload FROM extractions e JOIN documents d
          ON e.document_id=d.id AND e.extraction_key=d.extraction_key
          WHERE e.patient_id=? AND d.status='extracted' ORDER BY e.document_id""", (patient_id,)).fetchall()
        return [DocumentExtraction.model_validate_json(row[0]) for row in rows]

    def abstraction(self, patient_id: str, input_key: str) -> PatientAbstraction | None:
        row = self.connection.execute("SELECT payload FROM abstractions WHERE patient_id=? AND input_key=?", (patient_id, input_key)).fetchone()
        return PatientAbstraction.model_validate_json(row[0]) if row else None

    def save_abstraction(self, abstraction: PatientAbstraction, input_key: str):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO abstractions VALUES(?,?,?)",
                                    (abstraction.patient.patient_id, input_key, abstraction.model_dump_json()))
