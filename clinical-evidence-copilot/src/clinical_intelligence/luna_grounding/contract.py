"""Only the source-reference transport changes; the universal semantic fields do not."""
import json

from ..clinical_notes.prompt import INSTRUCTION_V2, citation_catalogue
from ..clinical_notes.schema import StrictModel, ClinicalFact, validate_extraction

CONFIG = {"model": "gpt-6-luna", "reasoning_effort": "high", "timeout_seconds": 300,
          "max_concurrency": 10, "comparison_cap": 100, "final_cap": 300,
          "new_round_cap": 400, "transport_retries": 0, "structural_retries": 0}
INSTRUCTION = INSTRUCTION_V2[:INSTRUCTION_V2.index("Evidence must be")] + """Evidence contains only source_id, selected from the source_catalogue.
The program copies that entire original passage and calculates exact character offsets.
Do not generate evidence quotations or character offsets. The source catalogue is a
mechanical index, not labels or clinical interpretations. Pick the passage that supports
the individual fact. Multiple independent facts may share the same source_id, including
different positive/negative findings in a coordinated list. Keep semantic assertions
separate without rewriting the source. Read the complete note for all context.
document_id must match input. Return facts=[] when no clinical facts are documented.
"""
PROMOTION_RULE = {
    "version": "grounding-promotion-v1",
    "primary": "all-selected original-silver end-to-end overlap mention F1",
    "comparator": "cached historical Single-pass v2 effective predictions (including historical permitted repairs)",
    "requirements": ["strictly greater operational silver F1",
                     "no lower all-selected structural success",
                     "no lower fixed source-audited concept/span/polarity/experiencer F1",
                     "no lower fixed source-audited complete-case rate",
                     "no additional confirmed semantic contradiction in flagged-case source review"],
    "missing_outputs_in_denominator": True, "review_cap_per_phase": 20,
    "no_prompt_or_evaluation_tuning": True,
    "clinical_expert_gold_available": False,
}


class SourceReference(StrictModel):
    source_id: str


class GroundedFact(ClinicalFact):
    evidence: SourceReference


class GroundedExtraction(StrictModel):
    document_id: str
    facts: list[GroundedFact]


def catalogue(doc):
    doc.verify()
    return [{"source_id": f"s{i:04d}", **s}
            for i, s in enumerate(citation_catalogue(doc.text))]


def schema(doc):
    value = GroundedExtraction.model_json_schema()
    value["$defs"]["SourceReference"]["properties"]["source_id"]["enum"] = [s["source_id"] for s in catalogue(doc)]
    return value


def prompt(doc):
    return INSTRUCTION + "\n" + json.dumps({"document_id": doc.document_id, "note": doc.text,
        "source_catalogue": [{"source_id": s["source_id"], "quote": s["quote"]}
                             for s in catalogue(doc)]}, ensure_ascii=False)


def resolve(raw, doc):
    parsed = GroundedExtraction.model_validate_json(raw)
    if parsed.document_id != doc.document_id:
        raise ValueError("Document identity mismatch")
    sources = {s["source_id"]: s for s in catalogue(doc)}
    facts, provenance = [], []
    for i, f in enumerate(parsed.facts):
        s = sources.get(f.evidence.source_id)
        if s is None:
            raise ValueError(f"facts[{i}]: unknown source ID")
        value = f.model_dump()
        value["evidence"] = {k: s[k] for k in ("quote", "start", "end")}
        facts.append(value)
        provenance.append({"fact_index": i, "source_id": s["source_id"],
                           "method": "exact full source passage; no model-generated quotation"})
    value = {"document_id": doc.document_id, "facts": facts}
    validate_extraction(json.dumps(value, ensure_ascii=False), doc)
    return value, provenance
