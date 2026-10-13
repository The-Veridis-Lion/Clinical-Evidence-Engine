"""Claim-scoped deterministic joins, with contextual records kept distinct."""
from .archive import PRIMARY_SERVICES, SNOMED, code_system
from .contracts import ClaimPacket, Diagnosis, EvidenceLink, OriginalCode, ServiceItem
from .policy import policy_status

MISSING = ["clinical_notes_not_in_archive", "provider_intent_not_established",
           "separate_orders_not_in_archive", "original_ehr_availability_time_unknown",
           "independent_medical_necessity_or_coverage_labels_not_in_archive"]


def link(source, role, relationship, proof=False):
    return EvidenceLink(source_id=source.source_id, role=role, relationship=relationship, proof_of_service=proof)


def condition_context(index, pid, code, timestamp):
    day = timestamp[:10]
    if not day:
        return []
    return [s for s in index.conditions.get((pid, code), [])
            if s.fields.get("START") and s.fields["START"][:10] <= day
            and (not s.fields.get("STOP") or s.fields["STOP"][:10] >= day)]


def build_packet(index, claim, *, partition="unassigned"):
    c = claim.fields
    cid, pid, enc = c["Id"], c["PATIENTID"], c["APPOINTMENTID"]
    if len(index.ids["claims.csv"][cid]) != 1:
        raise ValueError("DUPLICATE_CLAIM_ID")
    patient, patient_status = index.unique("patients.csv", pid)
    encounter, encounter_status = index.unique("encounters.csv", enc, pid)
    issues = []
    if patient_status != "LINKED":
        issues.append(f"patient:{patient_status}")
    if encounter_status != "LINKED":
        issues.append(f"encounter:{encounter_status}")
    diagnoses = []
    for i in range(1, 9):
        field = f"DIAGNOSIS{i}"
        if c.get(field):
            candidates = condition_context(index, pid, c[field], c.get("SERVICEDATE", ""))
            diagnoses.append(Diagnosis(field=field, code=OriginalCode(value=c[field], system=SNOMED,
                system_basis="Synthea CSV data dictionary; not printed in claim", source_id=claim.source_id, field=field),
                evidence=[link(s, "diagnosis_context", "patient + original diagnosis code + active date interval; not an item/event FK") for s in candidates]))
            if not candidates:
                issues.append(f"diagnosis_clinical_context_unresolved:{field}")
    transactions = index.transactions.get(cid, [])
    items, relations, context = [], [], []
    valid_transactions = []
    charge_keys = {}
    for transaction in transactions:
        t = transaction.fields
        if t["PATIENTID"] != pid:
            issues.append(f"transaction_patient_mismatch:{transaction.source_id}")
            continue
        valid_transactions.append(transaction)
        if t.get("APPOINTMENTID") != enc:
            issues.append(f"transaction_encounter_disagreement:{transaction.source_id}")
        if t["TYPE"] != "CHARGE":
            continue
        item_issues = []
        if len(index.ids["claims_transactions.csv"].get(t["ID"], [])) != 1:
            item_issues.append("duplicate_transaction_id")
        code, item_enc = t.get("PROCEDURECODE", ""), t.get("APPOINTMENTID", "")
        item_encounter, item_enc_status = index.unique("encounters.csv", item_enc, pid)
        candidates = index.services.get((pid, item_enc, code, t.get("FROMDATE", "")), []) if code and t.get("FROMDATE") and item_encounter else []
        # STOP is a disambiguator, never borrowed as an original service timestamp.
        if len(candidates) > 1:
            exact = [s for s in candidates if "STOP" in s.fields and s.fields["STOP"] == t.get("TODATE")]
            if len(exact) == 1:
                candidates = exact
        status = "COMPOSITE_MATCH_UNIQUE" if len(candidates) == 1 else "AMBIGUOUS" if candidates else "UNRESOLVED"
        if item_enc_status != "LINKED":
            item_issues.append(f"item_encounter:{item_enc_status}")
        if status != "COMPOSITE_MATCH_UNIQUE":
            item_issues.append("clinical_service_identity:" + status)
        if t.get("APPOINTMENTID") != enc:
            item_issues.append("claim_item_encounter_disagreement")
        systems = {code_system(s) for s in candidates}
        system_values = {x[0] for x in systems}
        system = next(iter(system_values)) if len(system_values) == 1 else "UNKNOWN"
        basis = "; ".join(sorted({x[1] for x in systems})) if len(system_values) == 1 else "No unambiguous source-backed system"
        evidence = [link(s, "service_record" if status == "COMPOSITE_MATCH_UNIQUE" else "service_candidate",
            "patient + verified encounter + exact original code + exact start timestamp; composite match, no clinical-event FK",
            status == "COMPOSITE_MATCH_UNIQUE") for s in candidates]
        categories = {PRIMARY_SERVICES[s.table] for s in candidates}
        category = next(iter(categories)) if len(categories) == 1 else "UNKNOWN"
        if len(candidates) == 1:
            source = candidates[0]
            if "STOP" in source.fields and source.fields["STOP"] != t.get("TODATE"):
                item_issues.append("source_stop_and_transaction_to_date_differ")
            images = index.imaging.get((pid, item_enc, code, t.get("FROMDATE", "")), [])
            if source.table == "procedures.csv" and images:
                category = "imaging"
                evidence.extend(link(s, "imaging_metadata", "patient + encounter + original PROCEDURE_CODE + exact DATE; images remain separate rows") for s in images)
            reason = source.fields.get("REASONCODE")
            if reason:
                evidence.extend(link(s, "documented_indication_context", "original service REASONCODE + patient + active condition interval; not provider intent")
                                for s in condition_context(index, pid, reason, t.get("FROMDATE", "")))
            # No LOINC crosswalk. Co-timed observations are context, not service proof.
            if source.table in {"procedures.csv", "encounters.csv"}:
                evidence.extend(link(s, "coincident_observation_context", "patient + encounter + exact DATE; association to this service remains UNRESOLVED")
                                for s in index.observations.get((pid, item_enc, t.get("FROMDATE", "")), []))
        dx_fields = []
        for i in range(1, 5):
            ref = t.get(f"DIAGNOSISREF{i}", "")
            if ref:
                if ref in {str(j) for j in range(1, 9)} and c.get("DIAGNOSIS" + ref):
                    dx_fields.append("DIAGNOSIS" + ref)
                else:
                    item_issues.append(f"invalid_diagnosis_reference:DIAGNOSISREF{i}:{ref}")
        key = t.get("CHARGEID", "")
        if key in charge_keys:
            item_issues.append("duplicate_charge_id")
            charge_keys[key].issues.append("duplicate_charge_id")
        item = ServiceItem(item_id=transaction.source_id, transaction_id=t["ID"], charge_id=key,
            source_id=transaction.source_id, code=OriginalCode(value=code, system=system, system_basis=basis,
            source_id=transaction.source_id, field="PROCEDURECODE"), description=t.get("NOTES", ""),
            from_date=t.get("FROMDATE", ""), to_date=t.get("TODATE", ""), units=t.get("UNITS", ""),
            category=category, identity_status=status, evidence=evidence, diagnosis_fields=dx_fields, issues=item_issues)
        charge_keys[key] = item
        items.append(item)
    # Separate charge rows may point to one clinical row. Do not count it as
    # independently verified performance of multiple billed events.
    service_owners = {}
    for item in items:
        for evidence in item.evidence:
            if evidence.proof_of_service:
                service_owners.setdefault(evidence.source_id, []).append(item)
    for owners in service_owners.values():
        if len(owners) > 1:
            for item in owners:
                item.identity_status = "AMBIGUOUS"
                item.issues.append("multiple_charge_items_share_clinical_candidate")
                for evidence in item.evidence:
                    if evidence.proof_of_service:
                        evidence.proof_of_service = False
                        evidence.role = "service_candidate"
    # CHARGEID is not assumed to repeat across financial rows. Only printed transfer references join.
    transfers = {}
    for s in valid_transactions:
        if s.fields["TYPE"] == "TRANSFEROUT":
            transfers.setdefault(s.fields.get("CHARGEID", ""), []).append(s)
    for s in valid_transactions:
        if s.fields["TYPE"] == "TRANSFERIN":
            ref = s.fields.get("TRANSFEROUTID", "")
            targets = transfers.get(ref, []) if ref else []
            if len(targets) == 1:
                relations.append(link(targets[0], "financial_transfer_reference", f"{s.source_id}.TRANSFEROUTID = same-claim TRANSFEROUT.CHARGEID"))
            else:
                issues.append(f"unresolved_transfer_reference:{s.source_id}")
        elif s.fields["TYPE"] not in {"CHARGE", "PAYMENT", "ADJUSTMENT", "TRANSFEROUT"}:
            issues.append(f"unknown_transaction_type:{s.source_id}:{s.fields['TYPE']}")
    if encounter:
        # Structured encounter context is bounded to this actual encounter, not patient history.
        for table in ["conditions.csv", "careplans.csv", "devices.csv", "supplies.csv"]:
            context.extend(link(s, "encounter_context", "patient + encounter FK; not proof of a billed item")
                           for s in index.by_encounter.get((table, pid, enc), []))
    if not items:
        issues.append("no_original_charge_items")
    all_linked = bool(items) and patient_status == encounter_status == "LINKED" and all(
        s.identity_status == "COMPOSITE_MATCH_UNIQUE" and not s.issues for s in items) and not issues
    return ClaimPacket(archive_sha256=index.archive_sha256, claim_id=cid, claim_source_id=claim.source_id,
        patient_id=pid, patient_source_id=patient.source_id if patient else None, patient_status=patient_status,
        original_encounter_id=enc, encounter_source_id=encounter.source_id if encounter else None,
        encounter_status=encounter_status, service_date=c.get("SERVICEDATE", ""), items=items, diagnoses=diagnoses,
        transaction_source_ids=[s.source_id for s in valid_transactions], transaction_relationships=relations,
        context=context, issues=issues, missing_information=list(MISSING),
        linkage_status="SOURCE_LINKED" if all_linked else "NEEDS_LINKAGE_REVIEW",
        review_readiness="STRUCTURED_EVIDENCE_ONLY" if all_linked else "NEEDS_LINKAGE_REVIEW",
        policy=policy_status(), partition=partition)


def expanded_packet(index, packet):
    value = packet.model_dump(mode="json")
    value["sources"] = {sid: index.sources[sid].model_dump(mode="json") for sid in sorted(packet.referenced_sources())}
    return value
