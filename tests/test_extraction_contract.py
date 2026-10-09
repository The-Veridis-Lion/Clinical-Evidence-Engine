"""Adapter boundaries: literal clock conversion, exact grounding, configuration keys."""
import re
from types import SimpleNamespace

import pytest

from clinical_intelligence.domain import RegisteredDocument
from clinical_intelligence.extraction import LangExtractExtractor, clock_minutes, locate_passage, normalize_clock_fields
from clinical_intelligence.provider import ProviderConfig


def document(text):
    return RegisteredDocument(document_id="fixture", fingerprint="fixture", source_names=["fixture.txt"], text=text)


def test_literal_clock_conversion_is_deterministic_in_adapter():
    original = {"actual_intervals": [{"start": "13:00", "end": "13:20"},
                                      {"start": "13:30", "end": "13:55"}],
                "breaks": [{"start": "13:20", "end": "13:30"}]}
    value = normalize_clock_fields("service", original)
    assert value["actual_intervals"] == [{"start": 780, "end": 800}, {"start": 810, "end": 835}]
    assert value["breaks"] == [{"start": 800, "end": 810}]
    assert original["actual_intervals"][0]["start"] == "13:00"
    assert normalize_clock_fields("relationship", {"replacement_time": "11:15"})["replacement_time"] == 675


@pytest.mark.parametrize("value", ["25:00", "13:60", "1:30", 810, None, "13:30–13:55"])
def test_clock_adapter_rejects_nonliteral_or_invalid_times(value):
    with pytest.raises(ValueError, match="HH:MM"):
        clock_minutes(value)


def test_unique_exact_source_quote_retains_true_offsets_and_lines():
    source = document("Header\nPatient was present.\nSigned\n")
    passage = locate_passage(source, "Patient was present.", None, None)
    assert source.text[passage.start:passage.end] == passage.quote
    assert (passage.line_start, passage.line_end) == (2, 2)
    assert passage.locator == "unique_exact_substring"


def test_missing_and_ambiguous_quotes_fail_grounding():
    source = document("same quote\nsame quote")
    with pytest.raises(ValueError, match="absent or ambiguously"):
        locate_passage(source, "same quote", None, None)
    with pytest.raises(ValueError, match="absent or ambiguously"):
        locate_passage(source, "different quote", None, None)
    # Alignment with correct offsets disambiguates an otherwise repeated quotation.
    assert locate_passage(source, "same quote", 0, 10).start == 0


def test_cache_key_changes_with_model_settings_and_prompt():
    luna = LangExtractExtractor(SimpleNamespace(config=ProviderConfig(model="gpt-6-luna", reasoning_effort="medium")))
    changed_model = LangExtractExtractor(SimpleNamespace(config=ProviderConfig(model="gpt-6-sol", reasoning_effort="medium")))
    changed_effort = LangExtractExtractor(SimpleNamespace(config=ProviderConfig(model="gpt-6-luna", reasoning_effort="high")))
    original = luna.key
    assert luna.key == original
    assert changed_model.key != original
    assert changed_effort.key != original
    luna._baseline["prompt"] += "\nChanged semantic extraction instruction"
    assert luna.key != original


REPEATED_LINE = "Scheduled group 10:00–11:30. Nontherapeutic break 10:45–11:00."


def repeated_document():
    return document("Patient: Morgan Example | MRN: TEST-P1 | Document ID: TEST-D1\n\n"
                    "January 22, 2026 | Encounter TEST-E1\n" + REPEATED_LINE +
                    "\n\nJanuary 29, 2026 | Encounter TEST-E2\n" + REPEATED_LINE + "\n")


@pytest.mark.parametrize("encounter,index", [("TEST-E1", 0), ("TEST-E2", 1)])
def test_repeated_quote_uses_explicit_section_identifier(encounter, index):
    source = repeated_document()
    offsets = [m.start() for m in re.finditer(re.escape(REPEATED_LINE), source.text)]
    passage = locate_passage(source, REPEATED_LINE, None, None, context={"encounter_ref": encounter})
    assert (passage.start, passage.end) == (offsets[index], offsets[index] + len(REPEATED_LINE))
    assert source.text[passage.start:passage.end] == REPEATED_LINE
    assert passage.locator == "unique_exact_substring"


@pytest.mark.parametrize("context", [None, {"encounter_ref": "TEST-E"},
                                     {"encounter_ref": "MISSING"},
                                     {"encounter_ref": "TEST-E1", "appointment_ref": "TEST-E2"}])
def test_repeated_quote_remains_fail_closed_without_unique_local_context(context):
    with pytest.raises(ValueError, match="absent or ambiguously"):
        locate_passage(repeated_document(), REPEATED_LINE, None, None, context=context)


def test_repeated_identifier_in_both_sections_does_not_choose_first():
    source = document(repeated_document().text.replace("TEST-E2", "TEST-E1"))
    with pytest.raises(ValueError, match="absent or ambiguously"):
        locate_passage(source, REPEATED_LINE, None, None, context={"encounter_ref": "TEST-E1"})


def test_exact_library_interval_and_unique_quote_keep_existing_paths():
    source = repeated_document()
    start = source.text.rfind(REPEATED_LINE)
    passage = locate_passage(source, REPEATED_LINE, start, start + len(REPEATED_LINE))
    assert passage.start == start and passage.locator == "langextract"
    unique = "January 22, 2026 | Encounter TEST-E1"
    passage = locate_passage(source, unique, -1, 3, context={"encounter_ref": "MISSING"})
    assert passage.quote == unique and passage.locator == "unique_exact_substring"


def test_valid_offset_cannot_bind_repeated_quote_to_other_encounter():
    source = repeated_document()
    start = source.text.find(REPEATED_LINE)
    with pytest.raises(ValueError, match="context does not match"):
        locate_passage(source, REPEATED_LINE, start, start + len(REPEATED_LINE), context={"encounter_ref": "TEST-E2"})


def test_adjacent_encounter_headings_establish_repeated_quote_ownership():
    source = document('Encounter E-1\nsame\nEncounter E-2\nsame\n')
    with pytest.raises(ValueError,match='context does not match'):
        locate_passage(source,'same',14,18,context={'encounter_ref':'E-2'})
    passage = locate_passage(source,'same',None,None,context={'encounter_ref':'E-2'})
    assert passage.start==source.text.rfind('same')


def test_adapter_uses_claim_context_when_library_alignment_is_unavailable(monkeypatch):
    import json
    import langextract as lx
    from clinical_intelligence.provider import CodexCLIProvider

    source = repeated_document()
    extractions = [lx.data.Extraction(extraction_class="patient",
        extraction_text=source.text.splitlines()[0], attributes={"data": json.dumps({
            "patient_id": "TEST-P1", "name": "Morgan Example", "declared_id": "TEST-D1"})})]
    for encounter, date in [("TEST-E1", "2026-01-22"), ("TEST-E2", "2026-01-29")]:
        extractions.append(lx.data.Extraction(extraction_class="service", extraction_text=REPEATED_LINE,
            attributes={"data": json.dumps({"statement": "Scheduled group with nontherapeutic break",
                "encounter_ref": encounter, "service_date": date, "service_type": "group",
                "evidence_kind": "clinical", "signed": True,
                "scheduled_intervals": [{"start": "10:00", "end": "11:30"}],
                "breaks": [{"start": "10:45", "end": "11:00"}]})}))
    # Reproduce the failed library boundary; no model/provider process is invoked.
    assert all(item.char_interval is None for item in extractions)
    monkeypatch.setattr(lx, "extract", lambda **kwargs: SimpleNamespace(extractions=extractions))
    provider = object.__new__(CodexCLIProvider)
    provider.config = ProviderConfig()
    provider.cli_version = "offline-fixture"
    provider.reset_usage()
    monkeypatch.setattr(provider, "language_model", lambda examples, text: None)
    result = LangExtractExtractor(provider).extract(source)
    assert len(result.claims) == 2
    first, second = sorted(result.claims, key=lambda c: c.service_date)
    assert first.encounter_ref == "TEST-E1" and second.encounter_ref == "TEST-E2"
    assert first.passages[0].start == source.text.find(REPEATED_LINE)
    assert second.passages[0].start == source.text.rfind(REPEATED_LINE)
    for claim in result.claims:
        passage = claim.passages[0]
        assert source.text[passage.start:passage.end] == REPEATED_LINE
        assert passage.locator == "unique_exact_substring"
    assert result.usage.model_calls == 0
