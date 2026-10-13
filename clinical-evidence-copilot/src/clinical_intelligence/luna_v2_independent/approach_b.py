"""Source-only single-pass refinement. No NLP, baseline or evaluator dependency."""
import json
from ..clinical_notes.prompt import INSTRUCTION_V2, citation_catalogue
from ..clinical_notes.schema import ClinicalNoteExtraction, validate_extraction

REFINEMENT = """
Atomic source-assertion guidelines:
1. Review each source passage for each independently documented assertion. A symptom
mentioned again later, including in examination or an accompanying complaint, needs its
own fact at that later source location. An observation about sputum or an exposure does
not replace a separately stated cough assertion in that same passage. Equivalent wording
in a parenthetical expansion is one assertion, not two independent clinical events.
2. Identify exactly what is negated. No change/increase/exacerbation of a symptom negates
that change, not the symptom. Preserve the change statement as its own observation;
retain symptom presence only where the passage actually establishes it. A currently
ongoing complaint lasting days/weeks is current even if described as a history of it.
3. Not reported/not documented describes reporting status, not definite symptom absence.
Preserve that proposition as a reporting-status observation; do not manufacture a
definite negative symptom. Explicit patient denials remain negative symptom assertions.
4. Normalize only to a clearly equivalent concept supported by the passage. Never change
a medication's named class or infer its indication, administration or effectiveness.
Use the documented class/name or null if normalization is unclear; canonical examples
elsewhere in this instruction are not a restricted vocabulary or preferred drug class.
5. Decompose a documented vital-sign list into separate typed observations (temperature,
blood pressure, pulse/heart rate, respiratory rate, oxygen saturation) with each stated
value and unit when available. Do not collapse them into one Vitals value string or infer
a fever symptom solely from an unqualified temperature. Shared exact evidence is allowed.
6. original_term must be one contiguous, verbatim substring of its own evidence quote.
Never join separated words, shorten a coordinated negative into new wording, expand an
abbreviation in that field, or insert ellipses. Concepts may be normalized; source fields
must remain literal. Re-read the source for these checks within this single extraction.
"""


def prompt(doc):
    doc.verify()
    return INSTRUCTION_V2 + REFINEMENT + "\n" + json.dumps({
        "document_id": doc.document_id, "note": doc.text,
        "citation_catalogue": citation_catalogue(doc.text)}, ensure_ascii=False)


def schema():
    return ClinicalNoteExtraction.model_json_schema()


def resolve(raw, doc):
    # Unchanged V2 structural contract. Literal-term compliance is separately measured,
    # not silently repaired or retroactively added to the historical validity contract.
    return validate_extraction(raw, doc).model_dump()
