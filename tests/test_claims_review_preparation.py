"""Behavior checks for the preparation boundary; no gold or live model is used."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pydantic import ValidationError
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.prepare import line_anchors, prepare_case


POLICY = {"registry_version": "test/1", "review_status": "draft_ai_reviewed",
          "human_review_completed": False, "criteria": [{"criterion_id": "TEST_TIMELINE"}]}


def raw_source(source_id="SRC-A", **changes):
    source = {"source_id": source_id, "patient_id": "PAT-A", "encounter_id": "ENC-A",
              "available_at": "2026-10-06", "origin": "constructed_synthetic",
              "source_kind": "structured_record", "recorded_at": "2026-10-05",
              "event_date": "2026-10-05", "record_type": "observation", "event_link_id": None,
              "content": {"value": 7.2, "unit": "%"}}
    source.update(changes)
    return source


def raw_case(sources=None):
    return {"schema_version": "claims-review-prep/0.1", "case_id": "TEST-1",
        "claim": {"claim_id": "CL-A", "patient_id": "PAT-A", "encounter_id": None,
            "service_date": "2026-10-05", "service_concept": "hba1c_monitoring",
            "procedure_code": None, "code_system": None, "mapping_status": "constructed_demo",
            "data_origin": "constructed_synthetic"},
        "review_context": {"as_of": "2026-10-08", "history_start": "2026-01-01",
            "history_end": "2026-10-05", "history_completeness": "not_asserted"},
        "sources": [raw_source()] if sources is None else sources}


def prepare(raw, policy=POLICY):
    return prepare_case(CaseInput.model_validate_json(json.dumps(raw)), policy, input_label="test-case.json")


class PreparationTests(unittest.TestCase):
    def test_known_false_zero_and_unknown_are_preserved(self):
        raw = raw_case([raw_source(content={"negative": False, "zero": 0, "unknown": None})])
        content = prepare(raw)["source_candidates"][0]["content"]
        self.assertIs(content["negative"], False)
        self.assertEqual(content["zero"], 0)
        self.assertIs(content["unknown"], None)

    def test_unknown_dates_do_not_borrow_recorded_or_review_date(self):
        raw = raw_case([raw_source(event_date=None)])
        raw["claim"]["service_date"] = None
        result = prepare(raw)
        self.assertIsNone(result["claim"]["service_date"])
        self.assertIsNone(result["source_candidates"][0]["event_date"])
        self.assertEqual(result["source_candidates"][0]["content"]["value"], 7.2)
        self.assertEqual(result["preparation_status"], "NEEDS_INPUT_REVIEW")

    def test_numeric_and_boolean_dates_are_not_coerced_to_calendar_dates(self):
        for value in (0, False, 1750000000):
            raw = raw_case()
            raw["claim"]["service_date"] = value
            with self.assertRaises(ValidationError):
                prepare(raw)

    def test_other_patient_is_excluded_without_exposing_their_text(self):
        raw = raw_case([raw_source(), raw_source("OTHER", patient_id="PAT-B", content={"secret": "NOT-FOR-TARGET"})])
        result = prepare(raw)
        self.assertEqual(len(result["source_candidates"]), 1)
        self.assertEqual(result["excluded_sources"][0]["reason"], "patient_mismatch")
        self.assertNotIn("NOT-FOR-TARGET", json.dumps(result))

    def test_receipt_cutoff_and_unknown_receipt_are_distinct(self):
        raw = raw_case([raw_source("LATE", available_at="2026-10-09"), raw_source("UNKNOWN", available_at=None)])
        result = prepare(raw)
        self.assertEqual({entry["reason"] for entry in result["excluded_sources"]}, {"not_available_as_of", "availability_unknown"})
        self.assertEqual(result["preparation_status"], "NEEDS_INPUT_REVIEW")
        self.assertEqual(result["unresolved_source_metadata"], [{"source_id": "UNKNOWN", "reason": "availability_unknown"}])

    def test_future_structured_event_is_not_prior_support(self):
        result = prepare(raw_case([raw_source("FUTURE", event_date="2026-10-20", content={"status": "scheduled"})]))
        self.assertEqual(result["excluded_sources"][0]["reason"], "future_event_as_of_not_prior_support")
        self.assertEqual(result["execution"]["policy_evaluation"], "not_run")

    def test_notes_are_not_dated_by_their_recording_date(self):
        text = "On 2026-08-01 the regimen changed. A new follow-up is planned for 2026-11-01."
        source = raw_source(source_kind="synthetic_note", record_type="note", event_date=None,
                            recorded_at="2026-10-06", content=text)
        entry = prepare(raw_case([source]))["source_candidates"][0]
        self.assertIsNone(entry["event_date"])
        self.assertEqual(entry["content"], text)
        self.assertEqual(entry["temporal_role"], "requires_semantic_extraction")

    def test_conflicting_linked_dates_remain_two_sources(self):
        result = prepare(raw_case([raw_source("A", event_link_id="EXPLICIT-EVENT", event_date="2026-08-01"),
                                   raw_source("B", event_link_id="EXPLICIT-EVENT", event_date="2026-08-11")]))
        self.assertEqual(len(result["source_candidates"]), 2)
        group = result["explicit_event_groups"][0]
        self.assertTrue(group["has_date_disagreement"])
        self.assertEqual(group["documented_event_dates"], ["2026-08-01", "2026-08-11"])
        self.assertIsNone(group["counted_as_tests"])

    def test_same_value_without_link_does_not_create_an_event_match(self):
        result = prepare(raw_case([raw_source("A"), raw_source("B")]))
        self.assertEqual(len(result["source_candidates"]), 2)
        self.assertEqual(result["explicit_event_groups"], [])

    def test_linked_conflict_is_retained_even_when_one_event_date_is_outside_window(self):
        for other_date in ("2026-10-06", "2025-12-01"):
            result = prepare(raw_case([raw_source("A", event_link_id="ONE", event_date="2026-08-01"),
                                       raw_source("B", event_link_id="ONE", event_date=other_date)]))
            self.assertEqual(len(result["source_candidates"]), 1)
            group = result["explicit_event_groups"][0]
            self.assertEqual(group["source_ids"], ["A", "B"])
            self.assertTrue(group["has_date_disagreement"])
            self.assertEqual(result["unresolved_source_metadata"][0]["reason"], "explicit_event_date_disagreement")

    def test_unknown_target_date_does_not_promote_future_condition_to_history(self):
        raw = raw_case([raw_source("FUTURE", record_type="condition", event_date="2026-10-09"),
                        raw_source("PAST", record_type="condition", event_date="2026-08-01")])
        raw["claim"]["service_date"] = None
        result = prepare(raw)
        self.assertEqual([entry["source_id"] for entry in result["source_candidates"]], ["PAST"])
        self.assertEqual(result["source_candidates"][0]["temporal_role"], "relative_to_target_unknown")
        self.assertEqual(result["excluded_sources"][0]["reason"], "future_event_as_of_not_prior_support")

    def test_history_window_does_not_drop_target_date_source(self):
        raw = raw_case()
        raw["review_context"]["history_end"] = "2026-09-01"
        result = prepare(raw)
        self.assertEqual(len(result["source_candidates"]), 1)
        self.assertEqual(result["source_candidates"][0]["temporal_role"], "same_calendar_date_as_target")
        self.assertTrue(any("gap" in reason for reason in result["reasons"]))

    def test_explicit_same_event_group_preserves_both_records(self):
        result = prepare(raw_case([raw_source("A", event_link_id="ONE"),
                                   raw_source("B", event_link_id="ONE", record_type="procedure")]))
        self.assertEqual(result["explicit_event_groups"][0]["source_ids"], ["A", "B"])
        self.assertFalse(result["explicit_event_groups"][0]["has_date_disagreement"])

    def test_old_test_is_outside_window_but_background_is_not_deleted(self):
        result = prepare(raw_case([raw_source("OLD-TEST", event_date="2025-12-01"),
                                   raw_source("BACKGROUND", record_type="condition", event_date="2000-01-01")]))
        self.assertEqual([source["source_id"] for source in result["source_candidates"]], ["BACKGROUND"])
        self.assertEqual(result["excluded_sources"][0]["reason"], "outside_declared_history_window")
        self.assertEqual(result["review_context"]["history_completeness"], "not_asserted")

    def test_source_and_policy_changes_invalidate_output_identity(self):
        raw = raw_case()
        first = prepare(raw)
        self.assertEqual(first["output_sha256"], prepare(raw)["output_sha256"])
        updated = copy.deepcopy(raw)
        updated["sources"][0]["content"]["value"] = None
        self.assertNotEqual(first["output_sha256"], prepare(updated)["output_sha256"])
        changed_policy = copy.deepcopy(POLICY)
        changed_policy["interpretation_note"] = "Changed despite same version label"
        self.assertNotEqual(first["output_sha256"], prepare(raw, changed_policy)["output_sha256"])

    def test_empty_case_does_not_invent_facts_or_zero_tests(self):
        result = prepare(raw_case([]))
        self.assertEqual(result["source_candidates"], [])
        self.assertEqual(result["explicit_event_groups"], [])
        self.assertEqual(result["preparation_status"], "NEEDS_INPUT_REVIEW")

    def test_screening_and_real_code_requests_do_not_become_denials(self):
        for mode in ("screening", "real-code"):
            raw = raw_case()
            if mode == "screening":
                raw["claim"]["service_concept"] = "hba1c_screening"
            else:
                raw["claim"].update(procedure_code="UNVERIFIED-CODE", code_system="UNVERIFIED", mapping_status="verified")
            result = prepare(raw)
            self.assertEqual(result["preparation_status"], "UNSUPPORTED_SCOPE")
            self.assertEqual(result["execution"]["policy_evaluation"], "not_run")
            self.assertNotIn("DENIED", json.dumps(result))

    def test_duplicate_source_ids_and_unexpected_runtime_labels_are_rejected(self):
        for raw in (raw_case([raw_source(), raw_source()]), {**raw_case(), "expected_status": "SUPPORTED"}):
            with self.assertRaises(ValidationError):
                CaseInput.model_validate(raw)

    def test_quote_offsets_preserve_unicode_crlf_and_repeated_text(self):
        text = "\u03b1 same\r\n\r\n\u03b1 same\n"
        anchors = line_anchors("NOTE", text)
        self.assertEqual([anchor["span_id"] for anchor in anchors], ["NOTE:L001", "NOTE:L003"])
        self.assertNotEqual(anchors[0]["start"], anchors[1]["start"])
        for anchor in anchors:
            self.assertEqual(text[anchor["start"]:anchor["end"]], anchor["quote"])

    def test_cli_failure_replaces_stale_success_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            case_path, policy_path, output = folder / "bad.json", folder / "policy.json", folder / "output"
            case_path.write_text(json.dumps({**raw_case(), "unexpected": True}), encoding="utf-8")
            policy_path.write_text(json.dumps(POLICY), encoding="utf-8")
            output.mkdir()
            (output / "bad_prepared.json").write_text('{"status":"OLD_SUCCESS"}', encoding="utf-8")
            completed = subprocess.run([sys.executable, "-m", "clinical_intelligence.claims_review", "prepare",
                "--case", str(case_path), "--output", str(output / "bad_prepared.json")],
                capture_output=True, text=True)
            self.assertEqual(completed.returncode, 1)
            failure = json.loads((output / "bad_prepared.json").read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "PREPARATION_FAILED")


if __name__ == "__main__":
    unittest.main()
