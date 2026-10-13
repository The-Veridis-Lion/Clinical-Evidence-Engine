"""Backward-compatible ClinicalFact projection plus explicit dialogue provenance."""
import json
from typing import Literal
from pydantic import Field
from ..clinical_notes.schema import ClinicalFact, Evidence, StrictModel, validate_extraction
from .dataset import source_index


class References(StrictModel):
    source_ids: list[str] = Field(min_length=1)


class ProposedFact(StrictModel):
    category: ClinicalFact.model_fields["category"].annotation
    concept: str | None
    polarity: ClinicalFact.model_fields["polarity"].annotation
    temporality: ClinicalFact.model_fields["temporality"].annotation
    experiencer: ClinicalFact.model_fields["experiencer"].annotation
    attributes: ClinicalFact.model_fields["attributes"].annotation
    assertion_basis: Literal["patient_report", "clinician_assessment", "clinician_observation",
        "documented_history", "discussion", "unknown"]
    attribution_confidence: Literal["context_supported", "uncertain"]
    clinical_status: str | None
    evidence: References


class ProposedRelationship(StrictModel):
    from_fact_index: int = Field(ge=0)
    to_fact_index: int = Field(ge=0)
    relation: str = Field(min_length=1)
    evidence: References


class Proposal(StrictModel):
    document_id: str
    facts: list[ProposedFact]
    relationships: list[ProposedRelationship]


class Provenance(Evidence):
    source_id: str
    document_id: str
    turn_id: str
    speaker_label: str | None


class DialogueFact(ClinicalFact):
    # Optional extensions permit ordinary legacy ClinicalFact values. Frozen V2 is untouched.
    assertion_basis: str | None = None
    attribution_confidence: str | None = None
    clinical_status: str | None = None
    supporting_evidence: list[Evidence] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)


class Relationship(StrictModel):
    from_fact_index: int
    to_fact_index: int
    relation: str
    provenance: list[Provenance]


class Extraction(StrictModel):
    document_id: str
    facts: list[DialogueFact]
    relationships: list[Relationship] = Field(default_factory=list)


def schema(doc):
    shape = Proposal.model_json_schema()
    shape["$defs"]["References"]["properties"]["source_ids"]["items"]["enum"] = [
        p["source_id"] for p in source_index(doc)["source_catalogue"]]
    shape["properties"]["document_id"]["enum"] = [doc.document_id]
    return shape


def resolve_references(refs, doc, catalogue):
    ids = refs.source_ids
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate identical source ID")
    if any(identity not in catalogue for identity in ids):
        raise ValueError("Unknown source ID")
    spans = []
    for identity in ids:
        s = catalogue[identity]
        if not 0 <= s["start"] < s["end"] <= len(doc.text) or doc.text[s["start"]:s["end"]] != s["quote"]:
            raise ValueError("Evidence offset/quotation mismatch")
        spans.append({**s, "document_id": doc.document_id})
    return spans


def primary_projection(value):
    return {"document_id": value["document_id"], "facts": [
        {k: f[k] for k in ClinicalFact.model_fields} for f in value["facts"]]}


def resolve_relationship(item, doc, catalogue, mapping):
    r = ProposedRelationship.model_validate(item)
    if r.from_fact_index not in mapping or r.to_fact_index not in mapping:
        raise ValueError("Relationship references absent/rejected fact")
    return {"from_fact_index": mapping[r.from_fact_index],
        "to_fact_index": mapping[r.to_fact_index], "relation": r.relation,
        "provenance": resolve_references(r.evidence, doc, catalogue)}


def identical(left, right):
    """JSON identity also distinguishes bool/int and int/float values."""
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def inspect(raw, doc):
    doc.verify()
    catalogue = {p["source_id"]: p for p in source_index(doc)["source_catalogue"]}
    errors, facts, accepted, relationships = [], [], [], []
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"document_id", "facts", "relationships"}:
            raise ValueError("Expected exactly document_id, facts, relationships")
        if value["document_id"] != doc.document_id:
            raise ValueError("Document identity mismatch")
        if not isinstance(value["facts"], list) or not isinstance(value["relationships"], list):
            raise ValueError("facts and relationships must be lists")
    except (ValueError, TypeError) as exc:
        return {"status": "INVALID", "result": None, "accepted_indices": [], "errors": [str(exc)]}
    for index, item in enumerate(value["facts"]):
        try:
            proposed = ProposedFact.model_validate(item)
            spans = resolve_references(proposed.evidence, doc, catalogue)
            resolved = proposed.model_dump(exclude={"evidence"})
            resolved.update(original_term=spans[0]["quote"], evidence={k: spans[0][k] for k in Evidence.model_fields},
                supporting_evidence=[{k: s[k] for k in Evidence.model_fields} for s in spans[1:]], provenance=spans)
            facts.append(DialogueFact.model_validate(resolved).model_dump())
            accepted.append(index)
        except ValueError as exc:
            errors.append(f"facts[{index}]: {exc}")
    mapping = {raw_index: i for i, raw_index in enumerate(accepted)}
    for index, item in enumerate(value["relationships"]):
        try:
            relationships.append(resolve_relationship(item, doc, catalogue, mapping))
        except ValueError as exc:
            errors.append(f"relationships[{index}]: {exc}")
    result = Extraction(document_id=doc.document_id, facts=facts, relationships=relationships).model_dump()
    validate_extraction(json.dumps(primary_projection(result)), doc)
    return {"status": "PARTIAL" if errors and facts else "INVALID" if errors else "VALID",
            "result": result, "accepted_indices": accepted, "errors": errors}


def inspect_repair(raw, initial_raw, initial, doc):
    repaired = inspect(raw, doc)
    if repaired["result"] is None:
        return repaired
    try:
        original = json.loads(initial_raw)
        replacement = json.loads(raw)
        if not isinstance(original, dict) or not isinstance(original.get("facts"), list):
            # Malformed JSON/envelope cannot be compared. Keep this uncertainty explicit.
            raise ValueError("Cannot establish assertion-preserving repair of malformed initial output")
        if len(original["facts"]) != len(replacement["facts"]):
            raise ValueError("Repair changed assertion count")
        # Derive validity from the original response, never trust caller-supplied indices.
        initial = inspect(initial_raw, doc)
        for index in initial["accepted_indices"]:
            if not identical(original["facts"][index], replacement["facts"][index]):
                raise ValueError("Repair changed an accepted fact")
        for index, item in enumerate(original["facts"]):
            if index not in initial["accepted_indices"] and isinstance(item, dict):
                for key in ProposedFact.model_fields.keys() - {"evidence"}:
                    if key in item and item[key] != replacement["facts"][index].get(key):
                        raise ValueError("Repair changed clinical fields")
        before_relations, after_relations = original.get("relationships"), replacement.get("relationships")
        if not isinstance(before_relations, list) or len(before_relations) != len(after_relations):
            raise ValueError("Repair changed relationship count")
        catalogue = {p["source_id"]: p for p in source_index(doc)["source_catalogue"]}
        mapping = {raw_index: i for i, raw_index in enumerate(initial["accepted_indices"])}
        endpoints = {"from_fact_index", "to_fact_index"}
        for index, (before, after) in enumerate(zip(before_relations, after_relations)):
            if identical(before, after):
                continue  # Unresolved invalid items remain explicitly PARTIAL.
            try:
                resolve_relationship(before, doc, catalogue, mapping)
            except ValueError:
                # A changed relationship must be an index-only repair. Text, evidence,
                # order/count and all originally valid endpoints stay identical.
                if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after):
                    raise ValueError(f"relationships[{index}]: repair changed relationship fields")
                if any(not identical(before[k], after[k]) for k in before.keys() - endpoints):
                    raise ValueError(f"relationships[{index}]: repair changed relationship text/evidence")
                resolve_references(References.model_validate(before["evidence"]), doc, catalogue)
                invalid = {k for k in endpoints if type(before[k]) is not int or before[k] not in mapping}
                if not invalid:
                    raise ValueError(f"relationships[{index}]: not an invalid-index repair")
                if any(not identical(before[k], after[k]) for k in endpoints - invalid):
                    raise ValueError(f"relationships[{index}]: repair changed a valid endpoint")
                resolve_relationship(after, doc, catalogue, mapping)
            else:
                raise ValueError(f"relationships[{index}]: repair changed an accepted relationship")
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "INVALID", "result": None, "accepted_indices": [], "errors": [str(exc)]}
    return repaired
