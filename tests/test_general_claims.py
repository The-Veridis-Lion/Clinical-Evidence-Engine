"""Small offline edge fixtures; the real archive remains the coverage benchmark."""
import csv
import gzip
import io
import json
import zipfile

import pytest

from clinical_intelligence.claims_engine.archive import ArchiveIndex
from clinical_intelligence.claims_engine.cli import main
from clinical_intelligence.claims_engine.engine import build_packet, expanded_packet
from clinical_intelligence.claims_engine.split import create_split, load_split
from clinical_intelligence.claims_engine.verification import verify_saved
from clinical_intelligence.claims_engine.workflow import inventory, process


def archive(tmp_path, *, extra_procedures=(), transactions=None, claims=None):
    tables = {
        "patients.csv": [{"Id": "P1"}, {"Id": "P2"}],
        "claims.csv": claims or [{"Id": "C1", "PATIENTID": "P1", "APPOINTMENTID": "E1", "SERVICEDATE": "2020-01-01T10:00:00Z", "DIAGNOSIS1": "D1"},
                                 {"Id": "C2", "PATIENTID": "P2", "APPOINTMENTID": "E2", "SERVICEDATE": "2020-01-01T10:00:00Z", "DIAGNOSIS1": ""}],
        "encounters.csv": [{"Id": "E1", "PATIENT": "P1", "START": "2020-01-01T10:00:00Z", "STOP": "2020-01-01T11:00:00Z", "CODE": "ENC"},
                           {"Id": "E2", "PATIENT": "P2", "START": "2020-01-01T10:00:00Z", "STOP": "2020-01-01T11:00:00Z", "CODE": "ENC"}],
        "claims_transactions.csv": transactions or [charge(), charge(ID="T2", CHARGEID="8", TYPE="PAYMENT"),
            charge(ID="T3", CHARGEID="9", TYPE="TRANSFEROUT"), charge(ID="T4", CHARGEID="10", TYPE="TRANSFERIN", TRANSFEROUTID="9")],
        "procedures.csv": [procedure(), procedure(PATIENT="P2", ENCOUNTER="E2", DESCRIPTION="OTHER PATIENT")] + list(extra_procedures),
        "observations.csv": [{"PATIENT": "P1", "ENCOUNTER": "E1", "DATE": "2020-01-01T10:00:00Z", "CODE": "4548-4", "VALUE": "0", "CATEGORY": "laboratory", "DESCRIPTION": "HbA1c"}],
        "conditions.csv": [{"PATIENT": "P1", "ENCOUNTER": "E1", "START": "2019-01-01", "STOP": "", "SYSTEM": "http://snomed.info/sct", "CODE": "D1", "DESCRIPTION": "original diagnosis"}],
    }
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, rows in tables.items():
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
            writer.writeheader()
            writer.writerows(rows)
            z.writestr(name, stream.getvalue())
    return path


def charge(**changes):
    row = dict(ID="T1", CLAIMID="C1", CHARGEID="7", PATIENTID="P1", TYPE="CHARGE",
        PROCEDURECODE="PROC", APPOINTMENTID="E1", FROMDATE="2020-01-01T10:00:00Z", TODATE="2020-01-01T10:30:00Z",
        DIAGNOSISREF1="1", NOTES="Original\nservice display", UNITS="1", TRANSFEROUTID="", PAYMENTS="0.00")
    row.update(changes)
    return row


def procedure(**changes):
    row = dict(PATIENT="P1", ENCOUNTER="E1", START="2020-01-01T10:00:00Z", STOP="2020-01-01T10:30:00Z",
               SYSTEM="http://snomed.info/sct", CODE="PROC", DESCRIPTION="Original service", REASONCODE="D1")
    row.update(changes)
    return row


def packet(path):
    idx = ArchiveIndex(path)
    return idx, build_packet(idx, idx.claim("C1"))


def test_original_identity_codes_multiple_transactions_and_no_policy(tmp_path):
    idx, p = packet(archive(tmp_path))
    assert len(p.items) == 1 and len(p.transaction_source_ids) == 4
    assert p.items[0].transaction_id == "T1" and p.items[0].charge_id == "7"
    assert p.items[0].code.value == "PROC" and p.items[0].category == "procedure"
    assert p.items[0].diagnosis_fields == ["DIAGNOSIS1"]
    assert p.policy["status"] == "POLICY_NOT_EVALUATED"
    assert p.live_model_calls == 0
    assert p.transaction_relationships[0].source_id == "claims_transactions.csv:3"
    value = expanded_packet(idx, p)
    assert "OTHER PATIENT" not in json.dumps(value)
    assert value["sources"]["claims_transactions.csv:1"]["fields"]["NOTES"] == "Original\nservice display"
    assert value["sources"]["claims_transactions.csv:1"]["physical_line_end"] > value["sources"]["claims_transactions.csv:1"]["physical_line_start"]


def test_loinc_result_never_changes_claim_code_or_proves_service(tmp_path):
    _, p = packet(archive(tmp_path))
    observations = [e for e in p.items[0].evidence if e.role == "coincident_observation_context"]
    assert observations and all(not e.proof_of_service for e in observations)
    assert p.items[0].code.value != "4548-4"
    assert "UNRESOLVED" in observations[0].relationship


def test_duplicate_clinical_rows_remain_ambiguous(tmp_path):
    _, p = packet(archive(tmp_path, extra_procedures=[procedure()]))
    assert p.items[0].identity_status == "AMBIGUOUS"
    assert sum(e.role == "service_candidate" for e in p.items[0].evidence) == 2
    assert not any(e.proof_of_service for e in p.items[0].evidence)


def test_exact_stop_disambiguates_without_merging_events(tmp_path):
    _, p = packet(archive(tmp_path, extra_procedures=[procedure(STOP="2020-01-01T10:45:00Z")]))
    assert p.items[0].identity_status == "COMPOSITE_MATCH_UNIQUE"
    assert [e.source_id for e in p.items[0].evidence if e.proof_of_service] == ["procedures.csv:1"]


def test_same_patient_date_different_encounter_cannot_link(tmp_path):
    _, p = packet(archive(tmp_path, transactions=[charge(APPOINTMENTID="E2")]))
    assert p.items[0].identity_status == "UNRESOLVED"
    assert not p.items[0].evidence
    assert p.items[0].code.system == "UNKNOWN"


def test_missing_code_keeps_original_claim_and_item(tmp_path):
    _, p = packet(archive(tmp_path, transactions=[charge(PROCEDURECODE="")]))
    assert p.claim_id == "C1" and len(p.items) == 1
    assert p.items[0].identity_status == "UNRESOLVED"
    assert p.items[0].code.value == ""


def test_repeated_same_code_charge_items_stay_separate(tmp_path):
    _, p = packet(archive(tmp_path, transactions=[charge(), charge(ID="T2", CHARGEID="11")]))
    assert len(p.items) == 2
    assert p.items[0].item_id != p.items[1].item_id
    assert all(i.identity_status == "AMBIGUOUS" for i in p.items)
    assert all(not e.proof_of_service for i in p.items for e in i.evidence)


def test_bad_diagnosis_reference_stays_explicit(tmp_path):
    _, p = packet(archive(tmp_path, transactions=[charge(DIAGNOSISREF1="9")]))
    assert p.items[0].diagnosis_fields == []
    assert "invalid_diagnosis_reference:DIAGNOSISREF1:9" in p.items[0].issues


def test_foreign_patient_transaction_is_flagged_without_contamination(tmp_path):
    _, p = packet(archive(tmp_path, transactions=[charge(PATIENTID="P2", NOTES="OTHER PATIENT SECRET")]))
    assert not p.items and not p.transaction_source_ids
    assert any("transaction_patient_mismatch" in issue for issue in p.issues)


def test_no_patient_history_scan_when_code_or_timestamp_missing(tmp_path):
    _, p = packet(archive(tmp_path, transactions=[charge(FROMDATE="")]))
    assert p.items[0].identity_status == "UNRESOLVED" and not p.items[0].evidence


def test_stop_disagreement_does_not_replace_original_dates(tmp_path):
    _, p = packet(archive(tmp_path, transactions=[charge(TODATE="2020-01-01T12:00:00Z")]))
    assert p.items[0].to_date == "2020-01-01T12:00:00Z"
    assert p.items[0].identity_status == "COMPOSITE_MATCH_UNIQUE"
    assert "source_stop_and_transaction_to_date_differ" in p.items[0].issues


def test_patient_split_is_immutable_and_filters_all_owned_rows(tmp_path):
    path = archive(tmp_path)
    idx = ArchiveIndex(path)
    split_path = tmp_path / "split.json"
    split = create_split(idx, split_path)
    assert create_split(idx, split_path) == split
    assert load_split(split_path, idx.archive_sha256) == split
    assert len(split["partitions"]["development"]) == len(split["partitions"]["holdout"]) == 1
    dev = {e["patient_id"] for e in split["partitions"]["development"]}
    scoped = ArchiveIndex(path, allowed_patients=dev)
    assert all(s.patient_id in dev for s in scoped.sources.values() if s.patient_id is not None)
    with pytest.raises(ValueError, match="IMMUTABLE"):
        create_split(idx, split_path, seed=1)
    split_path.write_text("{}")
    with pytest.raises(ValueError, match="DIGEST"):
        load_split(split_path)


def test_inventory_accounts_for_duplicate_claim_failures(tmp_path):
    claims = [{"Id": "C1", "PATIENTID": "P1", "APPOINTMENTID": "E1"}]*2
    idx = ArchiveIndex(archive(tmp_path, claims=claims))
    summary, ledger = inventory(idx)
    assert summary["metrics"]["accounted_claim_rows"] == 2
    assert summary["metrics"]["processing_failures"] == 2
    assert all(r["failure_category"] == "DUPLICATE_CLAIM_ID" for r in ledger)
    assert len({r["claim_source_id"] for r in ledger}) == 2


def test_batch_roundtrip_independent_original_verification(tmp_path):
    path = archive(tmp_path)
    idx = ArchiveIndex(path)
    split = create_split(idx, tmp_path / "split.json")
    summary, _ = process(idx, split, output=tmp_path / "batch")
    assert summary["metrics"]["accounted_claim_rows"] == 2
    report = verify_saved(path, tmp_path / "batch", split)
    assert report["status"] == "PASS" and report["verified_packets"] == 2
    assert report["verified_service_items"] == 1
    with pytest.raises(FileExistsError):
        process(idx, split, output=tmp_path / "batch")


def test_cli_never_overwrites_source_and_has_no_live_mode(tmp_path):
    path = archive(tmp_path)
    before = path.read_bytes()
    assert main(["packet", "--archive", str(path), "--claim-id", "C1", "--output", str(path)]) == 1
    assert path.read_bytes() == before
    with pytest.raises(SystemExit):
        main(["batch", "--archive", str(path), "--mode", "live"])


def test_root_cli_routes_original_claim_workflow(tmp_path, capsys):
    from clinical_intelligence.cli import main as root_main
    path = archive(tmp_path)
    assert root_main(["claims", "inspect-claim", "--archive", str(path), "--claim-id", "C1"]) == 0
    assert json.loads(capsys.readouterr().out)["claim"]["fields"]["Id"] == "C1"


def test_holdout_receipt_prevents_second_final_verification(tmp_path):
    path = archive(tmp_path)
    idx = ArchiveIndex(path)
    create_split(idx, tmp_path / "split.json")
    process(idx, load_split(tmp_path / "split.json"), output=tmp_path / "batch")
    args = ["verify-holdout", "--archive", str(path), "--batch", str(tmp_path / "batch"),
        "--split", str(tmp_path / "split.json"), "--output", str(tmp_path / "verification.json")]
    assert main(args) == 0
    args[-1] = str(tmp_path / "second.json")
    assert main(args) == 1
    assert not (tmp_path / "second.json").exists()
