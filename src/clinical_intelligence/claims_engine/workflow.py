"""Compact inventory and batch outputs, each original claim row accounted for."""
import csv
import gzip
import json
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
from pathlib import Path
from time import perf_counter

from ..claims_review.retrieval import sha
from . import VERSION
from .archive import DOCUMENTATION, DOCUMENTED_SYSTEMS, SNOMED
from .engine import build_packet
from .split import partition_map, verify_split_identities


def json_line(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


@contextmanager
def gzip_writer(path):
    # Stable compressed bytes: no filename or wall-clock timestamp in the header.
    with Path(path).open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as output:
            yield output


def claim_summary(packet):
    return {"claim_source_id": packet.claim_source_id, "claim_id": packet.claim_id, "patient_id": packet.patient_id,
        "encounter_id": packet.original_encounter_id, "patient_status": packet.patient_status,
        "encounter_status": packet.encounter_status, "partition": packet.partition,
        "categories": "|".join(sorted({i.category for i in packet.items})), "items": len(packet.items),
        "identified_items": sum(i.identity_status == "COMPOSITE_MATCH_UNIQUE" for i in packet.items),
        "ambiguous_items": sum(i.identity_status == "AMBIGUOUS" for i in packet.items),
        "unresolved_items": sum(i.identity_status == "UNRESOLVED" for i in packet.items),
        "supporting_records": len({e.source_id for i in packet.items for e in i.evidence if e.proof_of_service}),
        "linkage_status": packet.linkage_status,
        "issue_count": len(packet.issues) + sum(len(i.issues) for i in packet.items),
        "missing_information_count": len(packet.missing_information), "policy_status": packet.policy["status"],
        "processing_status": "PROCESSED", "failure_category": ""}


def process(index, split=None, *, output=None, partition=None):
    started = perf_counter()
    if split and index.allowed_patients is None:
        verify_split_identities(index, split)
    partitions = partition_map(split) if split else {}
    if partition and not split:
        raise ValueError("Partition selection requires frozen split")
    destination = Path(output) if output else None
    if destination:
        # All outputs are new runs. Never overwrite original data or an evaluation.
        destination.mkdir(parents=True, exist_ok=False)
    totals = Counter()
    categories, claim_categories, policies = Counter(), Counter(), Counter()
    per_partition = defaultdict(lambda: {"patients": set(), "claims": 0, "service_items": Counter(), "claims_by_category": Counter()})
    failures, ledger, refs = [], [], set()
    outputs = ExitStack()
    packet_file = outputs.enter_context(gzip_writer(destination / "packets.jsonl.gz")) if destination else None
    try:
        for claim in index.tables["claims.csv"]:
            part = partitions.get(claim.patient_id, "unassigned")
            if partition and part != partition:
                continue
            totals["original_claim_rows"] += 1
            per_partition[part]["claims"] += 1
            per_partition[part]["patients"].add(claim.patient_id)
            try:
                packet = build_packet(index, claim, partition=part)
                row = claim_summary(packet)
                totals["processed_claims"] += 1
                totals["claims_linked_to_patient"] += packet.patient_status == "LINKED"
                totals["claims_linked_to_encounter"] += packet.encounter_status == "LINKED"
                totals["claims_with_charge_items"] += bool(packet.items)
                totals["claims_with_identifiable_items"] += row["identified_items"] > 0
                totals["claims_with_all_items_identifiable"] += bool(packet.items) and row["identified_items"] == len(packet.items)
                totals["claims_with_supporting_service_records"] += row["supporting_records"] > 0
                totals["claims_with_linkage_issues"] += row["issue_count"] > 0
                totals["claims_with_ambiguous_items"] += row["ambiguous_items"] > 0
                totals["claims_with_unresolved_items"] += row["unresolved_items"] > 0
                totals["claims_with_missing_or_ambiguous_information"] += bool(row["issue_count"] or packet.missing_information)
                totals["claims_with_unresolved_observation_association"] += any(e.role == "coincident_observation_context" for i in packet.items for e in i.evidence)
                for key in ["items", "identified_items", "ambiguous_items", "unresolved_items"]:
                    totals[key] += row[key]
                totals["source_linked_claims"] += packet.linkage_status == "SOURCE_LINKED"
                policies[packet.policy["status"]] += 1
                categories.update(i.category for i in packet.items)
                claim_categories.update({i.category for i in packet.items})
                per_partition[part]["service_items"].update(i.category for i in packet.items)
                per_partition[part]["claims_by_category"].update({i.category for i in packet.items})
                refs.update(packet.referenced_sources())
                if packet_file:
                    packet_file.write(json_line(packet.model_dump(mode="json")).encode())
            except Exception as error:
                failure = {"claim_id": claim.original_id, "claim_source_id": claim.source_id,
                           "patient_id": claim.patient_id, "failure_category": str(error), "processing_status": "PROCESSING_FAILED"}
                failures.append(failure)
                row = failure
            ledger.append(row)
    finally:
        outputs.close()
    totals["processing_failures"] = len(failures)
    totals["distinct_claim_bearing_patients"] = len({c.patient_id for c in index.tables["claims.csv"]
        if not partition or partitions.get(c.patient_id) == partition})
    totals["accounted_claim_rows"] = len(ledger)
    totals["duplicate_claim_ids"] = sum(len(v)-1 for v in index.ids["claims.csv"].values())
    selected_ids = {row["claim_id"] for row in ledger}
    totals["orphan_transaction_rows"] = sum(s.fields["CLAIMID"] not in index.ids["claims.csv"] for s in index.tables["claims_transactions.csv"])
    transaction_types = Counter(s.fields["TYPE"] for s in index.tables["claims_transactions.csv"] if s.fields["CLAIMID"] in selected_ids)
    elapsed = perf_counter() - started
    summary = {"schema_version": VERSION, "archive_sha256": index.archive_sha256, "metrics": dict(totals),
        "service_categories_items": dict(categories), "service_categories_claims_nonexclusive": dict(claim_categories),
        "transaction_types": dict(transaction_types), "policy_status": dict(policies), "failures": failures,
        "partitions": {key: {"patients": len(v["patients"]), "claims": v["claims"],
            "service_items": dict(v["service_items"]), "claims_by_category_nonexclusive": dict(v["claims_by_category"])} for key, v in per_partition.items()},
        "live_model_calls": 0, "processing_seconds": elapsed, "claims_per_second": len(ledger)/elapsed if elapsed else 0,
        "metric_scope": "Source linkage and structured review readiness only; no independent medical or payment accuracy labels.",
        "documentation": DOCUMENTATION}
    if destination:
        with gzip_writer(destination / "sources.jsonl.gz") as source_file:
            for sid in sorted(refs):
                source_file.write(json_line(index.sources[sid].model_dump(mode="json")).encode())
        with (destination / "claim-index.csv").open("x", encoding="utf-8", newline="") as output_file:
            fields = list(dict.fromkeys(key for row in ledger for key in row))
            writer = csv.DictWriter(output_file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(ledger)
        (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (destination / "failures.json").write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
        artifacts = {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size} for p in sorted(destination.iterdir())}
        (destination / "output-manifest.json").write_text(json.dumps({"archive_sha256": index.archive_sha256, "files": artifacts}, indent=2) + "\n", encoding="utf-8")
    return summary, ledger


def inventory(index, split=None):
    summary, ledger = process(index, split)
    summary["tables"] = index.members
    summary["documented_unprinted_systems"] = {**DOCUMENTED_SYSTEMS, "claims.csv:DIAGNOSIS1..8": SNOMED}
    summary["transaction_code_system"] = "Not printed; retain UNKNOWN unless clinical composite candidates establish one system. No CPT/HCPCS conversion."
    summary["direct_joins"] = ["claims.PATIENTID = patients.Id", "claims.APPOINTMENTID = encounters.Id (patient checked)",
        "claims_transactions.CLAIMID = claims.Id (patient checked)",
        "clinical.PATIENT = patients.Id; clinical.ENCOUNTER = encounters.Id (patient checked)",
        "transaction.DIAGNOSISREF1..4 = claim.DIAGNOSIS1..8 ordinal", "TRANSFERIN.TRANSFEROUTID = same-claim TRANSFEROUT.CHARGEID"]
    summary["composite_candidate_joins"] = ["patient + encounter + original code + exact start timestamp; STOP only disambiguates",
        "imaging PROCEDURE_CODE + patient + encounter + exact DATE", "condition code + patient + active interval (context)"]
    summary["unavailable_or_ambiguous"] = ["No per-item clinical-event FK or code-system column in transactions",
        "No printed CPT/HCPCS crosswalk; LOINC observations are not transaction billing codes",
        "Financial transactions do not consistently share CHARGEID with original CHARGE; no guessed payment-to-item grouping",
        "No standalone notes/orders/provider intent or independent coverage labels; NOTES is a service display label",
        "Same timestamp/encounter does not prove observation-to-service identity; no panel-to-result crosswalk",
        "Repeated clinical rows retain distinct CSV row identities; imaging Id may span series/instances"]
    return summary, ledger
