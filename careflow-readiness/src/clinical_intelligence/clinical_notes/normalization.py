"""Versioned view/evaluation grouping; never alters extracted clinical assertions."""
NORMALIZATION_VERSION = "clinical-concept-groups-v2"
CONCEPT_GROUPS = {
    "dyspnea": "dyspnea", "cough": "cough", "respiratory pain": "respiratory pain",
    "fever": "fever", "nasal symptoms": "nasal symptoms",
    "nasal congestion": "nasal symptoms", "rhinorrhea": "nasal symptoms",
    "sneezing": "nasal symptoms", "nasal discharge": "nasal symptoms",
    "nasal stuffiness": "nasal symptoms", "runny nose": "nasal symptoms",
}


def concept_group(concept):
    # Exact concept lookup only. No reading source text, polarity or latent labels.
    return CONCEPT_GROUPS.get(concept.strip().casefold()) if concept is not None else None
