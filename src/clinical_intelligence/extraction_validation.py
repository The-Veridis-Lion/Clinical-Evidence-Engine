"""Syntactic source-contract checks, independent of candidates and evaluation gold.

These checks establish necessary coverage, not semantic correctness. Identifiers
are checked, never inferred or filled into model output. Unlabelled clinical
meaning remains the extractor's responsibility and is measured separately.
"""
import re
from .domain import DocumentExtraction, RegisteredDocument

VERSION = "source-contract-7"
IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_-]*"


def explicit_ids(text, label):
    return set(re.findall(r"\b" + label + r"\b\s*[:=]?\s*(" + IDENTIFIER + r")", text, re.I))


def validate_source_contract(document: RegisteredDocument, extraction: DocumentExtraction):
    text = document.text
    errors = []
    for label, actual, description in [
        (r"(?:MRN|Patient ID)", extraction.patient.patient_id, "patient ID"),
        (r"Document ID", extraction.declared_id, "document ID"),
    ]:
        identifiers = explicit_ids(text, label)
        if identifiers and identifiers != {actual}:
            errors.append(f"Explicit {description} omitted or changed")
    if extraction.patient.patient_id is not None and extraction.patient.patient_id not in text:
        errors.append("Patient identity is not supported by source")
    # Require coverage of syntactically declared identities. A source may mention
    # an encounter only as a correction target, which is why relationship refs count.
    for label in (r"encounter", r"appointment"):
        refs = {getattr(c, field, None) for c in extraction.claims for field in
                (("encounter_ref", "target_encounter") if label=='encounter' else ("appointment_ref",))}
        identifiers = {v for v in explicit_ids(text, label+r'(?:\s+ID)?') if re.search(r"\d", v)}
        if not identifiers.issubset(refs):
            errors.append(f"Explicit {label} ID omitted: {sorted(identifiers - refs)}")
    for claim in extraction.claims:
        for field in ("encounter_ref", "appointment_ref", "form_ref", "plan_ref", "target_encounter", "target_document_ref", "target_plan_ref"):
            ref = getattr(claim, field, None)
            if ref and not re.search(r"(?<![\w-])" + re.escape(ref) + r"(?![\w-])", text):
                errors.append(f"Invented source identifier in {field}: {ref!r}")
    # A patient-only response must not certify zero care when actual service
    # evidence is explicit. This is a conservative syntactic trigger, not a
    # replacement for clinical extraction or evaluation of omitted observations.
    # These are literal affirmative cues. Explicit absence of contact in a
    # clerical document does not establish an encounter requiring a service row.
    affirmative = re.sub(r"\b(?:no|without)\s+patient\s+(?:contact|arrival|departure)\b", "", text, flags=re.I)
    service_signal = re.search(r"\b(?:patient contact|patient arrival|patient departure|care was delivered|therapy duration|psychotherapy duration)\b", affirmative, re.I)
    if service_signal and not any(c.kind in {"service", "relationship"} for c in extraction.claims):
        errors.append("Source contains explicit service evidence but no service claim")

    for claim in extraction.claims:
        source=getattr(claim, 'source', None)
        if source is None:continue
        support='\n'.join(p.quote for p in claim.passages)
        if source.source_disposition is not None and source.source_disposition not in support:
            errors.append(f"Literal source disposition lacks linked evidence for {claim.encounter_ref!r}: "
                          f"{source.source_disposition!r}. Use an exact source substring and cite its applicable context.")
        if source.transmission_status=='retransmitted':
            linked=any(r.kind=='relationship' and r.relation=='retransmits'
                and r.target_encounter==claim.encounter_ref and r.target_encounter is not None
                and (r.service_date is None or r.service_date==claim.service_date) for r in extraction.claims)
            if not linked:
                errors.append(f"Retransmitted service needs an explicitly linked retransmits relationship: {claim.encounter_ref!r}")
    # The single runtime repair must see all independently observable violations.
    # Fail-fast used to hide later errors until after that repair was exhausted.
    if errors:
        raise ValueError('\n'.join(errors))
