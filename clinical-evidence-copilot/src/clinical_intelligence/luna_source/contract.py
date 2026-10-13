"""One source selection request, with the Single-pass v2 clinical fields."""
import json
from pydantic import Field
from ..clinical_notes.prompt import INSTRUCTION_V2
from ..clinical_notes.schema import StrictModel, ClinicalFact, Evidence, validate_extraction
from ..luna_grounding.contract import catalogue

CONFIG = {"model": "gpt-6-luna", "timeout_seconds": 300, "max_concurrency": 10,
          "comparison_cap_per_configuration": 100, "final_cap": 300, "total_cap": 500,
          "transport_retries": 0, "structural_retries": 0}
EFFORTS = {"A": "high", "B": "xhigh"}
INSTRUCTION = INSTRUCTION_V2[:INSTRUCTION_V2.index("Evidence must be")] + """Evidence contains only source_ids, an ordered nonempty list selected from source_catalogue.
The first ID is the passage containing this assertion's actual mention. Additional IDs
are supporting context only when needed for its meaning, subject, uncertainty or time.
Python retrieves each exact original passage and offsets; never generate quotes or coordinates.
Multiple atomic facts may share IDs. Separate repeated mentions use their own mention IDs,
including mentions in both History and Physical Examination. Read the unchanged whole note
for context; section context alone does not make a current denial historical.
Every clinical assertion and qualifier must be directly supported by the selected passages.
original_term must be a literal contiguous substring of a selected passage, without paraphrase,
invented ellipses, or reconstructed lists. Normalization belongs in concept, not original_term.
Negation scopes its actual proposition: 'no cough' is symptom cough absent; 'no change in
cough', 'no improvement', and 'no worsening' deny change, improvement, or worsening, not
the symptom itself. Preserve these as observation facts about the stated change with its
own polarity; do not manufacture a symptom absence or infer worsening from no improvement.
Undocumented information creates no fact. Preserve hedging, subject, and temporal scope.
Do not infer symptoms from generic distress, normal observations, or another clinical concept.
Do not infer diagnoses or treatments from symptoms. A source ID proves location only:
the fact's meaning must also be supported. Do not invent a fact to fill a schema slot.
document_id must match input. Return facts=[] when no clinical facts are documented.
"""
PROMOTION_RULE = {"minimum_f1_gain": 0.01, "minimum_complete_case_gain": 1,
    "requirements": ["corrected mention F1 gain >= 1 percentage point", "more complete mention cases",
                     "no lower structural success or fixed source-audit F1/complete cases",
                     "no important source-confirmed clinical regression in flagged review"],
    "review_cap": 20, "reference_scope": "original silver and previously corrected silver separate",
    "final": "fresh 300 including pilot 100; same gates versus full historical baseline",
    "data_role": "reused development cohort; no independent clinical gold or causal claim"}


class SourceReferences(StrictModel):
    source_ids: list[str] = Field(min_length=1)


class SelectedFact(ClinicalFact):
    evidence: SourceReferences


class SelectedExtraction(StrictModel):
    document_id: str
    facts: list[SelectedFact]


class ResolvedFact(ClinicalFact):
    supporting_evidence: list[Evidence]


class ResolvedExtraction(StrictModel):
    document_id: str
    facts: list[ResolvedFact]


def schema(doc):
    value = SelectedExtraction.model_json_schema()
    ids = value["$defs"]["SourceReferences"]["properties"]["source_ids"]
    ids["items"]["enum"] = [s["source_id"] for s in catalogue(doc)]
    return value


def prompt(doc):
    doc.verify()
    return INSTRUCTION + "\n" + json.dumps({"document_id": doc.document_id, "note": doc.text,
        "source_catalogue": [{"source_id": s["source_id"], "quote": s["quote"]}
                             for s in catalogue(doc)]}, ensure_ascii=False)


def primary_projection(value):
    """Explicit scoring projection: context spans never become extra symptom mentions."""
    return {"document_id": value["document_id"], "facts": [
        {k: v for k, v in f.items() if k != "supporting_evidence"} for f in value["facts"]]}


def validate_resolved(value, doc):
    parsed = ResolvedExtraction.model_validate(value)
    validate_extraction(json.dumps(primary_projection(value)), doc)
    for i, f in enumerate(parsed.facts):
        for e in f.supporting_evidence:
            if not 0 <= e.start < e.end <= len(doc.text) or doc.text[e.start:e.end] != e.quote:
                raise ValueError(f"facts[{i}]: supporting evidence mismatch")
        if not any(f.original_term in e.quote for e in [f.evidence, *f.supporting_evidence]):
            raise ValueError(f"facts[{i}]: original_term is not literal selected source text")
    return parsed.model_dump()


def resolve(raw, doc):
    parsed = SelectedExtraction.model_validate_json(raw)
    if parsed.document_id != doc.document_id:
        raise ValueError("Document identity mismatch")
    sources = {s["source_id"]: s for s in catalogue(doc)}
    facts, provenance = [], []
    for i, fact in enumerate(parsed.facts):
        ids = fact.evidence.source_ids
        if len(ids) != len(set(ids)):
            raise ValueError(f"facts[{i}]: duplicate source ID")
        if any(s not in sources for s in ids):
            raise ValueError(f"facts[{i}]: unknown source ID")
        spans = [{k: sources[s][k] for k in ("quote", "start", "end")} for s in ids]
        value = fact.model_dump()
        value["evidence"], value["supporting_evidence"] = spans[0], spans[1:]
        facts.append(value)
        provenance.append({"fact_index": i, "source_ids": ids, "spans": spans,
                           "note_sha256": doc.note_sha256, "method": "exact source lookup; no repair"})
    result = validate_resolved({"document_id": doc.document_id, "facts": facts}, doc)
    return result, provenance
