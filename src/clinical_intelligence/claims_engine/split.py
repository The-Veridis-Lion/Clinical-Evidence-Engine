"""Identity-only partition selection; existing manifests are never overwritten."""
import json
from collections import defaultdict
from pathlib import Path

from ..claims_review.retrieval import sha

SPLIT_VERSION = "claim-patient-split/1"


def create_split(index, path, seed=20261010):
    if index.allowed_patients is not None:
        raise ValueError("Split requires full original identity inventory")
    groups = defaultdict(list)
    for claim in index.tables["claims.csv"]:
        patient, status = index.unique("patients.csv", claim.patient_id)
        if status == "LINKED":
            groups[patient.original_id].append(claim.original_id)
    ordered = sorted(groups, key=lambda pid: (sha(f"{seed}:{pid}".encode()), pid))
    dev_size = 50 if len(ordered) >= 100 else len(ordered) // 2
    test_size = 50 if len(ordered) >= 100 else len(ordered) - dev_size
    value = {"schema_version": SPLIT_VERSION, "archive_sha256": index.archive_sha256,
        "seed": seed, "algorithm": "sort by SHA256 of UTF-8 seed:original_patient_id; then patient_id",
        "eligible_patients": len(ordered), "selection_scope": "patient and claim identity only; no service balancing or outcomes",
        "partitions": {key: [{"patient_id": pid, "claim_ids": sorted(groups[pid])} for pid in ids]
            for key, ids in [("development", ordered[:dev_size]), ("holdout", ordered[dev_size:dev_size+test_size]),
                             ("reserve", ordered[dev_size+test_size:])]},
        "holdout_use": "final deterministic source verification once after offline development; no tuning",
        "clinical_partition_rule": "every patient-owned row belongs to that original patient partition; provider/payer/organization tables are shared reference data"}
    path = Path(path)
    payload = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("IMMUTABLE_SPLIT_ALREADY_EXISTS")
        load_split(path, index.archive_sha256)
        return value
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents changing selection accidentally on reruns.
    with path.open("xb") as output:
        output.write(payload)
    with path.with_suffix(".sha256").open("x", encoding="ascii") as output:
        output.write(sha(payload) + "\n")
    return value


def load_split(path, archive_sha256=None):
    path = Path(path)
    raw = path.read_bytes()
    if sha(raw) != path.with_suffix(".sha256").read_text().strip():
        raise ValueError("SPLIT_DIGEST_MISMATCH")
    value = json.loads(raw)
    if value["schema_version"] != SPLIT_VERSION:
        raise ValueError("SPLIT_VERSION_MISMATCH")
    if archive_sha256 is not None and value["archive_sha256"] != archive_sha256:
        raise ValueError("SPLIT_ARCHIVE_MISMATCH")
    patients, claims = set(), set()
    for partition, entries in value["partitions"].items():
        if partition not in {"development", "holdout", "reserve"}:
            raise ValueError("UNKNOWN_PARTITION")
        for entry in entries:
            pid = entry["patient_id"]
            ids = entry["claim_ids"]
            if pid in patients or len(ids) != len(set(ids)) or claims.intersection(ids):
                raise ValueError("PARTITION_IDENTITY_OVERLAP")
            patients.add(pid)
            claims.update(ids)
    if len(patients) != value["eligible_patients"]:
        raise ValueError("PARTITION_PATIENT_COUNT_MISMATCH")
    ordered = sorted(patients, key=lambda pid: (sha(f"{value['seed']}:{pid}".encode()), pid))
    expected_sizes = (50, 50) if len(ordered) >= 100 else (len(ordered)//2, len(ordered)-len(ordered)//2)
    actual = [[e["patient_id"] for e in value["partitions"][key]] for key in ["development", "holdout", "reserve"]]
    d, h = expected_sizes
    if actual != [ordered[:d], ordered[d:d+h], ordered[d+h:]]:
        raise ValueError("PARTITION_SELECTION_CHANGED")
    return value


def partition_map(split):
    return {entry["patient_id"]: key for key, entries in split["partitions"].items() for entry in entries}


def verify_split_identities(index, split):
    expected = {e["patient_id"]: sorted(e["claim_ids"]) for entries in split["partitions"].values() for e in entries}
    actual = defaultdict(list)
    for claim in index.tables["claims.csv"]:
        if index.unique("patients.csv", claim.patient_id)[1] == "LINKED":
            actual[claim.patient_id].append(claim.original_id)
    if {pid: sorted(ids) for pid, ids in actual.items()} != expected:
        raise ValueError("SPLIT_ORIGINAL_IDENTITY_MISMATCH")
