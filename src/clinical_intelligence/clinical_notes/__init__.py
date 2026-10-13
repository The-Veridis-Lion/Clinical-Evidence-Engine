"""Universal documented-fact extraction, independent of claims and HbA1c."""
from .schema import ClinicalNoteExtraction, validate_extraction

__all__ = ["ClinicalNoteExtraction", "validate_extraction"]
