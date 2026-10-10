"""Independent saved-output verification against original CSV fields and bytes."""
import csv
import gzip
import json
import zipfile
from collections import Counter
from pathlib import Path
from time import perf_counter

from ..claims_review.retrieval import records, sha
from .contracts import ClaimPacket, SourceRow
from .split import partition_map


def verify_saved(archive_path, batch_path, split, *, partition=None):
    started = perf_counter()
    archive_path, batch_path = Path(archive_path), Path(batch_path)
    archive_sha = sha(archive_path.read_bytes())
    if split["archive_sha256"] != archive_sha:
        raise ValueError("VERIFICATION_ARCHIVE_MISMATCH")
    manifest = json.loads((batch_path / "output-manifest.json").read_text())
    if manifest["archive_sha256"] != archive_sha:
        raise ValueError("OUTPUT_ARCHIVE_MISMATCH")
    for name, value in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("INVALID_OUTPUT_MEMBER")
        raw = (batch_path / name).read_bytes()
        if sha(raw) != value["sha256"] or len(raw) != value["bytes"]:
            raise ValueError(f"OUTPUT_DIGEST_MISMATCH:{name}")
    partitions = partition_map(split)
    expected_ids = {cid for key, entries in split["partitions"].items() if not partition or key == partition
                    for e in entries for cid in e["claim_ids"]}
    with gzip.open(batch_path / "packets.jsonl.gz", "rt", encoding="utf-8") as f:
        packets = [ClaimPacket.model_validate_json(line) for line in f]
    packets = [p for p in packets if not partition or partitions.get(p.patient_id) == partition]
    failures = json.loads((batch_path / "failures.json").read_text())
    failures = [v for v in failures if not partition or partitions.get(v["patient_id"]) == partition]
    seen = Counter([p.claim_id for p in packets] + [v["claim_id"] for v in failures])
    if set(seen) != expected_ids or any(count != 1 for count in seen.values()):
        raise ValueError("CLAIM_COVERAGE_MISMATCH")
    needed = set().union(*(p.referenced_sources() for p in packets))
    saved = {}
    with gzip.open(batch_path / "sources.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            row = SourceRow.model_validate_json(line)
            if row.source_id in needed:
                if row.source_id in saved:
                    raise ValueError("DUPLICATE_SAVED_SOURCE")
                saved[row.source_id] = row
    if set(saved) != needed:
        raise ValueError("MISSING_SAVED_SOURCE")
    # Reparse original records independently from ingestion indexes.
    original = {}
    source_fields_checked = 0
    original_patient_ids = set()
    original_claims = {}
    original_transactions = {}
    with zipfile.ZipFile(archive_path) as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue
            raw = z.read(name)
            member_sha = sha(raw)
            for number, fields, start, end, row_sha in records(raw):
                sid = f"{name}:{number}"
                if name == "patients.csv":
                    original_patient_ids.add(fields["Id"])
                if name == "claims.csv":
                    original_claims[fields["Id"]] = fields["PATIENTID"]
                if name == "claims_transactions.csv" and fields["CLAIMID"] in expected_ids:
                    original_transactions.setdefault(fields["CLAIMID"], []).append((sid, fields))
                if sid not in needed:
                    continue
                source = saved[sid]
                expected_patient = fields.get("Id") if name == "patients.csv" else fields.get("PATIENT", fields.get("PATIENTID"))
                expected_encounter = fields.get("Id") if name == "encounters.csv" else fields.get("ENCOUNTER", fields.get("APPOINTMENTID"))
                if (source.fields != fields or source.table != name or source.data_record_number != number
                    or source.physical_line_start != start or source.physical_line_end != end
                    or source.original_row_sha256 != row_sha or source.source_file_sha256 != member_sha
                    or source.archive_sha256 != archive_sha
                    or source.patient_id != expected_patient or source.encounter_id != expected_encounter
                    or source.original_id != fields.get("Id", fields.get("ID"))):
                    raise ValueError(f"ORIGINAL_SOURCE_MISMATCH:{sid}")
                original[sid] = fields
                source_fields_checked += len(fields)
    if set(original) != needed:
        raise ValueError("ORIGINAL_SOURCE_MISSING")
    split_claims = {cid: e["patient_id"] for entries in split["partitions"].values() for e in entries for cid in e["claim_ids"]}
    eligible_original_claims = {cid: pid for cid, pid in original_claims.items() if pid in original_patient_ids}
    if split_claims != eligible_original_claims:
        raise ValueError("SPLIT_SOURCE_IDENTITIES_MISMATCH")
    items_checked = 0
    for packet in packets:
        claim = original[packet.claim_source_id]
        if (packet.claim_id != claim["Id"] or packet.patient_id != claim["PATIENTID"]
            or packet.original_encounter_id != claim["APPOINTMENTID"] or packet.service_date != claim.get("SERVICEDATE", "")
            or packet.partition != partitions.get(packet.patient_id)):
            raise ValueError("CLAIM_FIELD_MISMATCH")
        for sid in packet.referenced_sources():
            if saved[sid].patient_id is not None and saved[sid].patient_id != packet.patient_id:
                raise ValueError("CROSS_PATIENT_EVIDENCE")
        if packet.patient_source_id and original[packet.patient_source_id]["Id"] != packet.patient_id:
            raise ValueError("PATIENT_JOIN_MISMATCH")
        if packet.encounter_source_id and original[packet.encounter_source_id]["Id"] != packet.original_encounter_id:
            raise ValueError("ENCOUNTER_JOIN_MISMATCH")
        source_charges = {sid for sid in packet.transaction_source_ids if original[sid]["TYPE"] == "CHARGE"}
        expected_transactions = {sid for sid, row in original_transactions.get(packet.claim_id, []) if row["PATIENTID"] == packet.patient_id}
        if set(packet.transaction_source_ids) != expected_transactions or len(packet.transaction_source_ids) != len(expected_transactions):
            raise ValueError("TRANSACTION_COVERAGE_MISMATCH")
        if source_charges != {i.source_id for i in packet.items} or len(source_charges) != len(packet.items):
            raise ValueError("SERVICE_ITEM_COVERAGE_MISMATCH")
        for sid in packet.transaction_source_ids:
            if original[sid]["CLAIMID"] != packet.claim_id:
                raise ValueError("TRANSACTION_CLAIM_JOIN_MISMATCH")
        for diagnosis in packet.diagnoses:
            if diagnosis.code.value != claim[diagnosis.field] or diagnosis.code.source_id != packet.claim_source_id or diagnosis.code.field != diagnosis.field:
                raise ValueError("DIAGNOSIS_FIELD_MISMATCH")
        for item in packet.items:
            t = original[item.source_id]
            values = [item.transaction_id, item.charge_id, item.code.value, item.from_date, item.to_date, item.units, item.description]
            if values != [t["ID"], t["CHARGEID"], t.get("PROCEDURECODE", ""), t.get("FROMDATE", ""), t.get("TODATE", ""), t.get("UNITS", ""), t.get("NOTES", "")]:
                raise ValueError("SERVICE_FIELD_MISMATCH")
            if item.item_id != item.source_id or item.code.source_id != item.source_id or item.code.field != "PROCEDURECODE":
                raise ValueError("ITEM_IDENTITY_MISMATCH")
            expected_diagnoses = ["DIAGNOSIS" + t[f"DIAGNOSISREF{i}"] for i in range(1,5)
                if t.get(f"DIAGNOSISREF{i}") in {str(j) for j in range(1,9)} and claim.get("DIAGNOSIS" + t[f"DIAGNOSISREF{i}"])]
            if item.diagnosis_fields != expected_diagnoses:
                raise ValueError("ITEM_DIAGNOSIS_REF_MISMATCH")
            for evidence in item.evidence:
                row = original[evidence.source_id]
                if evidence.role in {"service_record", "service_candidate"}:
                    enc = row.get("ENCOUNTER", row.get("Id"))
                    if row.get("CODE") != item.code.value or enc != t["APPOINTMENTID"] or row.get("START", row.get("DATE", "")) != item.from_date:
                        raise ValueError("COMPOSITE_SERVICE_JOIN_MISMATCH")
                if evidence.proof_of_service and (evidence.role != "service_record" or item.identity_status != "COMPOSITE_MATCH_UNIQUE"):
                    raise ValueError("CONTEXT_PROMOTED_TO_SERVICE_PROOF")
            documented = {"encounters.csv": "http://snomed.info/sct", "medications.csv": "RxNorm",
                          "immunizations.csv": "CVX", "devices.csv": "http://snomed.info/sct", "supplies.csv": "http://snomed.info/sct"}
            candidate_systems = {original[e.source_id].get("SYSTEM") or documented.get(saved[e.source_id].table, "UNKNOWN")
                for e in item.evidence if e.role in {"service_record", "service_candidate"}}
            expected_system = next(iter(candidate_systems)) if len(candidate_systems) == 1 else "UNKNOWN"
            if item.code.system != expected_system:
                raise ValueError("UNSUPPORTED_BILLING_CROSSWALK")
            items_checked += 1
        if packet.policy["status"] != "POLICY_NOT_EVALUATED" or packet.policy["payment_decision"] != "NOT_MADE":
            raise ValueError("UNSUPPORTED_POLICY_DECISION")
    return {"status": "PASS", "partition": partition or "all", "archive_sha256": archive_sha,
        "split_sha256": sha(json.dumps(split, sort_keys=True, separators=(",", ":")).encode()),
        "accounted_claims": len(seen), "verified_packets": len(packets), "processing_failures": failures,
        "verified_service_items": items_checked, "verified_original_sources": len(original),
        "verified_original_fields": source_fields_checked, "cross_patient_evidence": 0,
        "unsupported_billing_mappings": 0, "verification_seconds": perf_counter()-started,
        "live_model_calls": 0, "scope": "Deterministic source identity, fields, byte provenance, patient partitions and selected joins; no clinical accuracy labels."}
