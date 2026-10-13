"""One immutable in-memory CSV index per run; no database or model provider."""
import csv
import io
from collections import Counter, defaultdict
from pathlib import Path

from ..claims_review.retrieval import records, sha
from ..archive_bounds import BoundedArchive
from .contracts import SourceRow

SNOMED = "http://snomed.info/sct"
DOCUMENTATION = "https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary"
PRIMARY_SERVICES = {
    "encounters.csv": "encounter",
    "procedures.csv": "procedure",
    "medications.csv": "medication",
    "immunizations.csv": "immunization",
    "devices.csv": "device",
    "supplies.csv": "supply",
}
DOCUMENTED_SYSTEMS = {
    "encounters.csv": SNOMED, "medications.csv": "RxNorm",
    "immunizations.csv": "CVX", "devices.csv": SNOMED,
    "supplies.csv": SNOMED, "careplans.csv": SNOMED,
    "observations.csv": "LOINC", "imaging_studies.csv": SNOMED,
}
REQUIRED = {"patients.csv": {"Id"}, "claims.csv": {"Id", "PATIENTID", "APPOINTMENTID"},
            "claims_transactions.csv": {"ID", "CLAIMID", "PATIENTID", "TYPE", "PROCEDURECODE", "APPOINTMENTID"},
            "encounters.csv": {"Id", "PATIENT", "CODE", "START"}}


def patient_key(table, row):
    return row.get("Id") if table == "patients.csv" else row.get("PATIENT", row.get("PATIENTID"))


def encounter_key(table, row):
    return row.get("Id") if table == "encounters.csv" else row.get("ENCOUNTER", row.get("APPOINTMENTID"))


def event_start(row):
    return row.get("START", row.get("DATE", ""))


def code_system(source):
    printed = source.fields.get("SYSTEM")
    if printed:
        return printed, "source SYSTEM field"
    system = DOCUMENTED_SYSTEMS.get(source.table, "UNKNOWN")
    return system, "Synthea CSV data dictionary; not printed in row" if system != "UNKNOWN" else "not present or established"


class ArchiveIndex:
    def __init__(self, path, *, allowed_patients=None):
        self.path = Path(path)
        snapshot = BoundedArchive(self.path)
        self.archive_sha256 = snapshot.snapshot_sha256
        self.sources = {}
        self.tables = defaultdict(list)
        self.ids = defaultdict(lambda: defaultdict(list))
        self.transactions = defaultdict(list)
        self.services = defaultdict(list)
        self.by_encounter = defaultdict(list)
        self.conditions = defaultdict(list)
        self.imaging = defaultdict(list)
        self.observations = defaultdict(list)
        self.members = []
        self.allowed_patients = allowed_patients
        with snapshot as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("DUPLICATE_ARCHIVE_MEMBER")
            if not set(REQUIRED) <= set(names):
                raise ValueError("MISSING_REQUIRED_TABLE")
            for table in names:
                raw = archive.read(table)
                member = {"path": table, "bytes": len(raw), "sha256": sha(raw), "rows": 0}
                self.members.append(member)
                if not table.endswith(".csv"):
                    continue
                columns = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))).fieldnames or []
                member["columns"] = columns
                if not REQUIRED.get(table, set()) <= set(columns):
                    raise ValueError(f"MISSING_REQUIRED_COLUMN:{table}")
                member["nonempty_fields"] = dict.fromkeys(columns, 0)
                systems = Counter()
                for number, row, start, end, row_sha in records(raw):
                    member["rows"] += 1
                    pid = patient_key(table, row)
                    # During development keep only the frozen development patient's rows.
                    if allowed_patients is not None and pid is not None and pid not in allowed_patients:
                        continue
                    for key, value in row.items():
                        member["nonempty_fields"][key] += bool(value)
                    if row.get("SYSTEM"):
                        systems[row["SYSTEM"]] += 1
                    enc = encounter_key(table, row)
                    sid = f"{table}:{number}"
                    source = SourceRow(source_id=sid, table=table, data_record_number=number,
                        physical_line_start=start, physical_line_end=end, original_row_sha256=row_sha,
                        source_file_sha256=member["sha256"], archive_sha256=self.archive_sha256,
                        original_id=row.get("Id", row.get("ID")), patient_id=pid,
                        encounter_id=enc, fields=row)
                    self.sources[sid] = source
                    self.tables[table].append(source)
                    if source.original_id:
                        self.ids[table][source.original_id].append(source)
                    if table == "claims_transactions.csv":
                        self.transactions[row["CLAIMID"]].append(source)
                    if pid and enc:
                        self.by_encounter[(table, pid, enc)].append(source)
                    if table in PRIMARY_SERVICES:
                        self.services[(pid, enc, row.get("CODE", ""), event_start(row))].append(source)
                    if table == "conditions.csv":
                        self.conditions[(pid, row.get("CODE", ""))].append(source)
                    if table == "imaging_studies.csv":
                        self.imaging[(pid, enc, row.get("PROCEDURE_CODE", ""), row.get("DATE", ""))].append(source)
                    if table == "observations.csv":
                        self.observations[(pid, enc, row.get("DATE", ""))].append(source)
                member["printed_systems"] = dict(systems)

    def unique(self, table, identifier, patient_id=None):
        candidates = self.ids[table].get(identifier, [])
        if len(candidates) != 1:
            return None, "UNKNOWN" if not candidates else "AMBIGUOUS"
        source = candidates[0]
        if patient_id is not None and source.patient_id != patient_id:
            return None, "PATIENT_MISMATCH"
        return source, "LINKED"

    def claim(self, claim_id):
        source, status = self.unique("claims.csv", claim_id)
        if source is None:
            raise ValueError(f"CLAIM_{status}:{claim_id}")
        return source
