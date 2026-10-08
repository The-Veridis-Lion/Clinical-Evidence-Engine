"""Fixed inference response verifies integration, not model semantic accuracy."""
import json

from langextract.core.base_model import BaseLanguageModel
from langextract.core.types import ScoredOutput

from clinical_intelligence.audit import render_audit
from clinical_intelligence.extraction import LangExtractExtractor
from clinical_intelligence.pipeline import load_patient, process
from clinical_intelligence.provider import CodexCLIProvider, ProviderConfig
from clinical_intelligence.query import QuerySpec, query_patient
from clinical_intelligence.storage import SQLiteStore


def test_fixed_response_through_real_adapter_storage_query_audit(tmp_path, monkeypatch):
    patient_line = "Patient: Morgan Example | MRN: OFFLINE-P1 | Document ID: OFFLINE-D1"
    service_line = "Signed individual visit OFFLINE-E1 on 2026-02-02. Patient contact 14:00 to 14:35; 35 minutes."
    source = tmp_path / "offline_note.txt"
    source.write_text(patient_line + "\n" + service_line, encoding="utf-8")
    fixed_response = json.dumps({"extractions": [
        {"patient": patient_line, "patient_attributes": {"data": json.dumps({"patient_id": "OFFLINE-P1", "name": "Morgan Example", "declared_id": "OFFLINE-D1"})}},
        {"service": service_line, "service_attributes": {"data": json.dumps({
            "statement": "Delivered patient-present individual psychotherapy", "encounter_ref": "OFFLINE-E1",
            "service_date": "2026-02-02", "service_type": "individual", "evidence_kind": "clinical",
            "signed": True, "patient_present": True, "delivered": True, "reported_minutes": 35,
            "actual_intervals": [{"start": "14:00", "end": "14:35"}]})}},
    ]})
    inference_requests = []

    class FixedModel(BaseLanguageModel):
        def __init__(self):
            super().__init__()
            self.set_fence_output(False)

        def infer(self, batch_prompts, **kwargs):
            for prompt in batch_prompts:
                inference_requests.append(prompt)
                yield [ScoredOutput(score=1.0, output=fixed_response)]

    # Bypass account probing; only infer() is replaced, not LangExtract or validation.
    provider = object.__new__(CodexCLIProvider)
    provider.config = ProviderConfig()
    provider.cli_version = "offline-fixture"
    provider.reset_usage()
    monkeypatch.setattr(provider, "language_model", lambda examples, source_text: FixedModel())
    extractor = LangExtractExtractor(provider)
    database = tmp_path / "clinical.sqlite"
    with SQLiteStore(database) as store:
        report = process(store, [source], extractor)
        assert report["extracted"] == 1 and report["failed"] == report["model_calls"] == 0
        assert len(inference_requests) == 1
        document = store.documents()[0]
        extraction = store.extraction(document.document_id, extractor.key)
        assert len(extraction.claims) == 1
        claim = extraction.claims[0]
        assert claim.reported_minutes == 35
        assert document.text[claim.passages[0].start:claim.passages[0].end] == service_line
    with SQLiteStore(database) as store:
        answer = query_patient(load_patient(store, "OFFLINE-P1"), QuerySpec(family="utilization"), documents=store.documents())
        totals = answer["result"]["totals"]
        assert totals["sessions"]["value"] == totals["distinct_service_days"]["value"] == 1
        assert totals["minutes"]["value"] == 35
        assert answer["provenance_completeness"] == "complete"
        displayed = render_audit(answer)
        assert "minutes=35" in displayed and "OFFLINE-D1" in displayed and "offline_note.txt" in displayed
        assert service_line in displayed and "chars [" in displayed
