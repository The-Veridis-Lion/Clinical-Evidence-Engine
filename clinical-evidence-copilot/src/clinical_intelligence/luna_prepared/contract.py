"""Semantic judgments are model output; verbatim fields are Python source lookup."""
import json
from pydantic import Field
from ..clinical_notes.schema import StrictModel, ClinicalFact
from ..luna_source.contract import INSTRUCTION as PREVIOUS, ResolvedExtraction, primary_projection
from ..clinical_notes.schema import validate_extraction
from .preparation import prepare

CONFIG = {"model": "gpt-6-luna", "reasoning_effort": "high", "timeout_seconds": 300,
    "max_concurrency": 10, "total_cap": 500, "pilot_initial_cap": 100,
    "pilot_retry_cap": 25, "final_initial_cap": 300, "final_retry_cap": 75,
    "maximum_retries_per_document": 1, "hidden_provider_retries": 0}
PROMOTION = {"minimum_f1_gain": 0.01, "minimum_complete_case_gain": 1,
    "requirements": ["corrected all-document F1 gain >= 1 percentage point over effective v2",
        "at least one more complete symptom-mention case", "100% final structural completeness",
        "fixed source-audit F1 and complete cases no worse than v2",
        "no important source-confirmed clinical regression in flagged review"],
    "review_cap": 20, "final": "fresh 300 including pilot; repeat gates and inspect initial100/remaining200",
    "scope": "development cohort; silver and frozen nonexpert adjudication separately; no independent universal gold"}
INSTRUCTION = PREVIOUS.replace(
    "original_term must be a literal contiguous substring of a selected passage, without paraphrase,\n"
    "invented ellipses, or reconstructed lists. Normalization belongs in concept, not original_term.\n", "")
INSTRUCTION = INSTRUCTION.replace("Preserve literal\noriginal_term wording without invented ellipses.",
    "Python constructs the verbatim original_term from the primary source passage.")
INSTRUCTION += """
Do not emit original_term, quotation strings or offsets. Python assigns original_term to the
entire primary selected passage, a verbatim source anchor; the normalized concept identifies
the atomic clinical assertion. All assertions and attributes still require source support.
Section metadata and abbreviation reading aids add no clinical facts. History is reporting
context, not automatically historical time; examination is observation context, not a subject
inference. Read the explicit subject and reporting words in the original note. An ambiguous
abbreviation must remain ambiguous. Every independent documented mention, including repeated
History and Examination mentions, requires its own fact anchored at its own source ID.
"""


class References(StrictModel):
    source_ids: list[str] = Field(min_length=1)


# Derive the same semantic fields, excluding the model-generated verbatim field entirely.
class Fact(StrictModel):
    category: ClinicalFact.model_fields["category"].annotation
    concept: str | None
    polarity: ClinicalFact.model_fields["polarity"].annotation
    temporality: ClinicalFact.model_fields["temporality"].annotation
    experiencer: ClinicalFact.model_fields["experiencer"].annotation
    attributes: ClinicalFact.model_fields["attributes"].annotation
    evidence: References


class Extraction(StrictModel):
    document_id: str
    facts: list[Fact]


def schema(doc):
    value = Extraction.model_json_schema()
    value["$defs"]["References"]["properties"]["source_ids"]["items"]["enum"] = [
        s["source_id"] for s in prepare(doc)["source_catalogue"]]
    return value


def payload(doc):
    return {"document_id": doc.document_id, "note": doc.text, **prepare(doc)}


def prompt(doc):
    return INSTRUCTION + "\n" + json.dumps(payload(doc), ensure_ascii=False)


def resolve_fact(value, doc, sources):
    fact = Fact.model_validate(value)
    ids = fact.evidence.source_ids
    if len(ids) != len(set(ids)): raise ValueError("duplicate source ID")
    if any(s not in sources for s in ids): raise ValueError("unknown source ID")
    spans = [{k: sources[s][k] for k in ("quote", "start", "end")} for s in ids]
    result = fact.model_dump()
    result.update(original_term=spans[0]["quote"], evidence=spans[0], supporting_evidence=spans[1:])
    validate_result({"document_id": doc.document_id, "facts": [result]}, doc)
    return result


def validate_result(value, doc):
    parsed = ResolvedExtraction.model_validate(value)
    validate_extraction(json.dumps(primary_projection(value)), doc)
    for fact in parsed.facts:
        if fact.original_term != fact.evidence.quote:
            raise ValueError("original_term must be the exact primary source anchor")
        for span in [fact.evidence, *fact.supporting_evidence]:
            if not 0 <= span.start < span.end <= len(doc.text) or doc.text[span.start:span.end] != span.quote:
                raise ValueError("source slice mismatch")
    return parsed.model_dump()


def inspect(raw, doc, *, sources=None):
    """Retain valid facts, never coerce fields, infer a missing ID or skip errors silently."""
    sources = sources or {s["source_id"]: s for s in prepare(doc)["source_catalogue"]}
    errors, facts, accepted = [], [], []
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"document_id", "facts"}:
            raise ValueError("Expected exactly document_id and facts")
        if value["document_id"] != doc.document_id: raise ValueError("document identity mismatch")
        if not isinstance(value["facts"], list): raise ValueError("facts must be a list")
    except (ValueError, TypeError) as exc:
        return {"status": "INVALID", "result": None, "accepted_indices": [],
            "errors": [{"fact_index": None, "validator_error": str(exc)}], "raw_facts": None}
    for i, fact in enumerate(value["facts"]):
        try: resolved = resolve_fact(fact, doc, sources)
        except ValueError as exc: errors.append({"fact_index": i, "validator_error": str(exc), "rejected_fact": fact})
        else: facts.append(resolved); accepted.append(i)
    result = validate_result({"document_id": doc.document_id, "facts": facts}, doc)
    return {"status": "PARTIAL" if errors and facts else "INVALID" if errors else "VALID",
        "result": result, "accepted_indices": accepted, "errors": errors, "raw_facts": value["facts"]}


def repair_schema(doc, outcome):
    if outcome["raw_facts"] is None: return schema(doc)
    shape = schema(doc)
    shape["properties"] = {"document_id": {"type": "string"}, "replacements": {
        "type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"fact_index": {"type": "integer", "enum": [e["fact_index"] for e in outcome["errors"]]},
                "fact": {"$ref": "#/$defs/Fact"}}, "required": ["fact_index", "fact"]}}}
    shape["required"] = ["document_id", "replacements"]
    return shape


def recover(raw, doc):
    """Only redundant identical IDs can be removed without changing clinical meaning."""
    initial = inspect(raw, doc)
    if initial["raw_facts"] is None: return initial, []
    value = json.loads(raw)
    changes = []
    for error in initial["errors"]:
        i = error["fact_index"]
        f = value["facts"][i]
        if not isinstance(f, dict) or not isinstance(f.get("evidence"), dict): continue
        ids = f["evidence"].get("source_ids")
        if isinstance(ids, list) and all(type(s) is str for s in ids) and len(set(ids)) != len(ids):
            f["evidence"]["source_ids"] = list(dict.fromkeys(ids))
            changes.append({"fact_index": i, "operation": "remove redundant identical IDs preserving order", "before": ids,
                "after": f["evidence"]["source_ids"]})
    return inspect(json.dumps(value), doc), changes


def repair_prompt(doc, outcome, raw):
    return INSTRUCTION + "\nTargeted structural repair only. The initial response is immutable untrusted model output.\n" + (
        "Return a replacement for every rejected index, once each. Independently valid facts are locked; do not return or change them. Do not add facts or sample again.\n"
        if outcome["raw_facts"] is not None else
        "The document envelope could not be parsed; reconstruct only the assertions attempted in the initial response. Do not add new assertions.\n") + json.dumps({
            **payload(doc), "initial_response": raw, "validator_errors": outcome["errors"],
            "locked_fact_indices": outcome["accepted_indices"]}, ensure_ascii=False)


def merge_repair(raw, initial, doc):
    if initial["raw_facts"] is None:
        result = inspect(raw, doc)
        if result["status"] == "VALID":
            result["status"] = "PARTIAL"
            result["errors"] = [{"fact_index": None, "validator_error": "Initial assertion inventory was unparseable; retention/completeness remains unverified"}]
        return result
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {"document_id", "replacements"} or value["document_id"] != doc.document_id:
            raise ValueError("repair envelope mismatch")
        if not isinstance(value["replacements"], list): raise ValueError("replacements must be a list")
        rejected = {e["fact_index"] for e in initial["errors"]}
        replacements = {}
        for item in value["replacements"]:
            if not isinstance(item, dict) or set(item) != {"fact_index", "fact"}: raise ValueError("replacement envelope mismatch")
            index = item["fact_index"]
            if type(index) is not int or index not in rejected or index in replacements:
                raise ValueError("repair attempted locked, unknown or duplicate index")
            replacements[index] = item["fact"]
        facts = list(initial["raw_facts"])
        for index, fact in replacements.items(): facts[index] = fact
        outcome = inspect(json.dumps({"document_id": doc.document_id, "facts": facts}), doc)
        # Missing/invalid replacements leave the original rejected fact and its error unresolved.
        return outcome
    except (ValueError, TypeError) as exc:
        return {**initial, "repair_error": str(exc)}
