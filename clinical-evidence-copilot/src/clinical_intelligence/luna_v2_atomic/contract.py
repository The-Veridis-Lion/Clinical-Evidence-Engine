"""Only original source enters inference; refine B's first guideline only."""
import json
from ..clinical_notes.prompt import INSTRUCTION_V2, citation_catalogue
from ..clinical_notes.schema import ClinicalNoteExtraction, validate_extraction
from ..luna_v2_independent.approach_b import REFINEMENT as ORIGINAL_B_REFINEMENT

ORIGINAL_ATOMIC_RULE = ORIGINAL_B_REFINEMENT.split("1. ", 1)[1].split("2. ", 1)[0]
ATOMIC_RULE = """Treat each explicitly documented clinical assertion as a separate fact, not each
sentence or citation as a fact. For every source passage you cite, include each assertion
it actually establishes, including an actual symptom embedded in a trigger, accompanying
complaint, sputum description, attribution, or examination observation. Retaining that
symptom only inside another fact's quote, original_term, or attributes does not produce
its independent symptom fact. Keep its own supported concept, polarity, temporality and
experiencer; different facts may share the same exact evidence. A later independent
mention needs a fact at that later source location even if that symptom was extracted
earlier. Preserve the core symptom concept; put its documented modifiers in attributes.
Do not add hypothetical, generic or merely possible symptoms, infer a symptom from an
unrelated finding, or duplicate synonymous wording of one assertion in one passage.
Before returning within this same call, check that your cited passages' explicit symptom
assertions are represented by their own facts, rather than only by retained quotations.
"""
REFINEMENT = ORIGINAL_B_REFINEMENT.replace(ORIGINAL_ATOMIC_RULE, ATOMIC_RULE, 1)


def prompt(doc):
    doc.verify()
    return INSTRUCTION_V2 + REFINEMENT + "\n" + json.dumps({"document_id": doc.document_id,
        "note": doc.text, "citation_catalogue": citation_catalogue(doc.text)}, ensure_ascii=False)


def schema():
    return ClinicalNoteExtraction.model_json_schema()


def resolve(raw, doc):
    return validate_extraction(raw, doc).model_dump()
