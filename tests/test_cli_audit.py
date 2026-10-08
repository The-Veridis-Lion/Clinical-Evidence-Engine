"""The audit display resolves deterministic evidence references, never a model."""
import json

from clinical_intelligence.audit import render_audit
from clinical_intelligence.cli import write_result


def _answer():
    passage = {"quote": "Patient contact lasted 30 minutes.", "start": 9, "end": 42,
               "line_start": 2, "line_end": 2}
    return {"query": {"family": "utilization"}, "result": {
        "totals": {"minutes": {"lower": 30, "upper": 30, "value": 30}},
        "provenance": {"completeness": "complete", "operation": "sum_events",
                       "contributions": [{"fact_id": "encounter-1", "field": "reported_minutes",
                                          "value": 30, "included": True, "reason": "Delivered patient contact",
                                          "source_refs": [{"document_id": "doc-1", "declared_id": "NOTE-1",
                                                           "source_names": ["note.txt"], "claim_id": "claim/1",
                                                           "passage_id": "doc-1:9:42",
                                                           "evidence_path": "/evidence/claim~11/passages/0"}]}],
                       "alternatives": [], "gaps": []}},
        "evidence": {"claim/1": {"passages": [passage]}}}


def test_audit_resolves_existing_quote_and_span():
    answer = _answer()
    rendered = render_audit(answer)
    assert "minutes=30" in rendered
    assert "encounter-1 / reported_minutes: 30 (included)" in rendered
    assert "NOTE-1 — note.txt" in rendered
    assert "Patient contact lasted 30 minutes." in rendered
    assert "chars [9, 42); lines 2..2" in rendered
    assert "quote" not in answer["result"]["provenance"]["contributions"][0]["source_refs"][0]


def test_audit_displays_exclusion_and_separate_alternative():
    answer = _answer()
    trace = answer["result"]["provenance"]
    trace["contributions"][0]["included"] = False
    trace["contributions"][0]["reason"] = "Interruption is excluded"
    trace["alternatives"] = [{"value": 40, "completeness": "complete", "contributions": trace["contributions"]},
                             {"value": 50, "completeness": "partial", "contributions": [], "gaps": ["No direct duration span"]}]
    rendered = render_audit(answer)
    assert "(excluded) — Interruption is excluded" in rendered
    assert "Alternative 1: value: 40" in rendered
    assert "Alternative 2: value: 50" in rendered
    assert "Provenance gap: No direct duration span" in rendered


def test_invalid_pointer_is_explicit_not_invented():
    answer = _answer()
    answer["result"]["provenance"]["contributions"][0]["source_refs"][0]["evidence_path"] = "/missing"
    rendered = render_audit(answer)
    assert "Provenance gap: source passage unavailable at /missing" in rendered
    assert "Patient contact lasted 30 minutes." not in rendered


def test_default_json_output_is_unchanged(tmp_path):
    output = tmp_path / "query.json"
    answer = _answer()
    write_result(answer, output)
    assert json.loads(output.read_text(encoding="utf-8")) == answer
