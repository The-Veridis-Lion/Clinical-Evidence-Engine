"""Views select original fact indices; they never manufacture a fact or a negative."""
from dataclasses import dataclass
from .schema import ClinicalNoteExtraction
from .normalization import concept_group, NORMALIZATION_VERSION


@dataclass(frozen=True)
class SpecialtyView:
    name: str
    concepts: frozenset[str]
    include_diagnoses: bool = False

    def project(self, result: ClinicalNoteExtraction, *, grouped=False):
        return {"document_id": result.document_id, "specialty": self.name,
                **({"normalization_version": NORMALIZATION_VERSION} if grouped else {}),
                "facts": [{"fact_index": i, **f.model_dump(),
                           **({"concept_group": concept_group(f.concept)} if grouped else {})}
                          for i, f in enumerate(result.facts)
                          if ((concept_group(f.concept) if grouped else None) or (f.concept or "").casefold()) in {c.casefold() for c in self.concepts}
                          or self.include_diagnoses and f.category == "diagnosis"]}


RESPIRATORY = SpecialtyView("respiratory", frozenset({"dyspnea", "cough", "respiratory pain",
    "fever", "nasal symptoms", "asthma", "COPD", "hay fever", "smoking history", "antibiotics"}), True)
VIEWS = {"respiratory": RESPIRATORY}
