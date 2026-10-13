"""v1: structural validation only; never infer or suppress clinical assertions."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "clinical-note-extraction-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Attributes(StrictModel):
    severity: str | None
    duration: str | None
    value: str | None
    unit: str | None


class Evidence(StrictModel):
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ClinicalFact(StrictModel):
    category: Literal["symptom", "condition", "diagnosis", "medication", "treatment",
                      "procedure", "laboratory_result", "observation", "other"]
    concept: str | None
    original_term: str = Field(min_length=1)
    polarity: Literal["present", "absent", "uncertain"]
    temporality: Literal["current", "historical", "planned", "unknown"]
    experiencer: Literal["patient", "family", "other", "unknown"]
    attributes: Attributes | None
    evidence: Evidence


class ClinicalNoteExtraction(StrictModel):
    document_id: str
    facts: list[ClinicalFact]


def validate_extraction(raw: str, document) -> ClinicalNoteExtraction:
    result = ClinicalNoteExtraction.model_validate_json(raw)
    if result.document_id != document.document_id:
        raise ValueError("document_id differs from frozen source")
    document.verify()
    for i, fact in enumerate(result.facts):
        e = fact.evidence
        if not 0 <= e.start < e.end <= len(document.text) or document.text[e.start:e.end] != e.quote:
            raise ValueError(f"facts[{i}]: evidence quote/offset mismatch")
    return result
