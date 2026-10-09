from clinical_intelligence.domain import DocumentExtraction, ExtractionUsage, Patient, RegisteredDocument
from clinical_intelligence.extraction_validation import validate_source_contract
from clinical_intelligence.extraction_validation import explicit_ids
import pytest


@pytest.mark.parametrize("omission", ["patient", "document", "encounter", "service"])
def test_omission_is_not_certified_as_successful_zero(omission):
    text = "Patient: Test Person | MRN: P-1 | Document ID: D-1\n"
    if omission == "encounter":
        text += "Encounter E-1.\n"
    if omission == "service":
        text += "Patient contact: 14:00 to 14:30.\n"
    document = RegisteredDocument(document_id="hash", fingerprint="hash", source_names=["test"], text=text)
    value = DocumentExtraction(document_id="hash", extraction_key="test", declared_id=None if omission == "document" else "D-1",
        patient=Patient(patient_id=None if omission == "patient" else "P-1", name="Test Person"), claims=[],
        usage=ExtractionUsage(provider="fixed", model="none", settings={}, latency_seconds=0, model_calls=0))
    with pytest.raises(ValueError):
        validate_source_contract(document, value)


def test_patient_identified_is_not_patient_id_declaration():
    assert explicit_ids('MRN: P-1. The patient identified anxiety.',r'(?:MRN|Patient ID)')=={'P-1'}


def test_encounter_reference_cannot_satisfy_explicit_appointment_role(evidence,service):
    value=evidence('hash',[service(encounter_ref='E-1')],declared_id='D-1')
    text='MRN: SYN-P1 | Document ID: D-1\nEncounter E-1. Appointment E-1.'
    document=RegisteredDocument(document_id='hash',fingerprint='hash',source_names=['test'],text=text)
    with pytest.raises(ValueError,match='appointment ID omitted'):
        validate_source_contract(document,value)
    value.claims[0].appointment_ref='E-1'
    validate_source_contract(document,value)


def test_explicit_id_suffix_is_checked(evidence,service):
    value=evidence('hash',[service(encounter_ref='WRONG')],declared_id='D-1')
    document=RegisteredDocument(document_id='hash',fingerprint='hash',source_names=['test'],
        text='MRN: SYN-P1 | Document ID: D-1\nEncounter ID: E-1\n')
    with pytest.raises(ValueError,match='encounter ID omitted'):
        validate_source_contract(document,value)


def test_negated_clerical_contact_does_not_require_a_fabricated_encounter(evidence):
    value=evidence('hash',[],declared_id='D-1')
    text='MRN: SYN-P1 | Document ID: D-1\nNo patient contact occurred. Address formatting only.'
    document=RegisteredDocument(document_id='hash',fingerprint='hash',source_names=['test'],text=text)
    validate_source_contract(document,value)
    document.text+='\nLater patient contact: 14:00 to 14:30.'
    with pytest.raises(ValueError,match='no service claim'):
        validate_source_contract(document,value)
