from datetime import date
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
import pytest
from clinical_intelligence.domain import DocumentExtraction, ExtractionUsage, Patient, ServiceClaim, SourcePassage
@pytest.fixture
def patient():
    return Patient(patient_id="SYN-P1", name="Taylor Example", dob=date(1980, 2, 3))


@pytest.fixture
def evidence(patient):
    def make(document_id, claims, declared_id=None, key="fixture-v1"):
        validated = []
        for position, item in enumerate(claims):
            item = dict(item)
            statement = item.setdefault("statement", f"Synthetic statement {position}")
            quote = item.pop("quote", statement)
            passage = SourcePassage(document_id=document_id, start=0, end=len(quote),
                                    quote=quote, line_start=1, line_end=1)
            factory = item.pop("factory", ServiceClaim)
            validated.append(factory(claim_id=item.pop("claim_id", f"{document_id}:{position}"),
                                     document_id=document_id, patient_id=patient.patient_id,
                                     passages=[passage], **item))
        return DocumentExtraction(
            document_id=document_id, extraction_key=key, declared_id=declared_id,
            patient=patient, claims=validated,
            usage=ExtractionUsage(provider="fixture", model="none", settings={},
                                  latency_seconds=0, model_calls=0),
        )
    return make


@pytest.fixture
def service():
    def make(**changes):
        value = {
            "encounter_ref": "SYN-E1", "service_date": date(2026, 2, 2),
            "service_type": "individual", "evidence_kind": "clinical", "signed": True,
            "patient_present": True, "delivered": True,
            "actual_intervals": [{"start": 540, "end": 585}],
        }
        value.update(changes)
        return value
    return make
