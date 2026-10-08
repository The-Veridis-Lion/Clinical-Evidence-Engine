"""Fixed inference responses verify the query boundary, not model accuracy."""
from copy import deepcopy
from datetime import date
import json
import subprocess
from types import SimpleNamespace

import pytest

from clinical_intelligence.natural_language import (
    NaturalLanguageQueryInterpreter, QueryContext, QueryInterpretation, interpretation_schema,
)
from clinical_intelligence.provider import CodexCLIProvider, ProviderConfig
from clinical_intelligence.query import QuerySpec


class FixedProvider:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def structured_output(self, prompt, schema):
        self.calls.append((prompt, schema))
        return deepcopy(self.response)


@pytest.fixture
def context():
    return QueryContext(patient_id="DEMO-NL-1", patient_name="Cedar Example", episode_year=2026)


def ready(spec):
    return {"status": "ready", "query_spec": spec,
            "clarification_question": None, "explanation": None}


@pytest.mark.parametrize("spec", [
    {"family": "utilization", "start": "2026-01-05", "end": "2026-01-30"},
    {"family": "weekly_utilization", "service_types": ["individual", "group", "family"]},
    {"family": "compliance"},
    {"family": "encounters", "dates": ["2026-01-19", "2026-01-21"]},
    {"family": "compare_periods", "start": "2026-01-05", "end": "2026-01-30",
     "change_date": "2026-01-19"},
    {"family": "consecutive_under_target", "consecutive_weeks": 3},
    {"family": "assessments"},
    {"family": "progress"},
    {"family": "cohort", "min_minutes": 590},
])
def test_ready_output_validates_all_families_and_binds_selected_patient(spec, context):
    provider = FixedProvider(ready(spec))
    result = NaturalLanguageQueryInterpreter(provider).interpret("Review Cedar Example's therapy.", context)
    assert isinstance(result, QueryInterpretation)
    assert result.status == "ready"
    assert result.query_spec == QuerySpec(**spec, patient_id=context.patient_id)
    assert len(provider.calls) == 1
    assert provider.response["query_spec"] == spec


def test_prompt_supplies_only_explicit_question_and_patient_context(context):
    question = "How much group therapy did Cedar Example receive January 19?"
    provider = FixedProvider(ready({"family": "encounters", "patient_id": "DEMO-NL-1",
                                    "dates": ["2026-01-19"], "service_types": ["group"]}))
    result = NaturalLanguageQueryInterpreter(provider).interpret(question, context)
    assert result.query_spec.dates == [date(2026, 1, 19)]
    prompt, schema = provider.calls[0]
    for supplied in (question, context.patient_id, context.patient_name, str(context.episode_year)):
        assert supplied in prompt
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["QuerySpec"]["additionalProperties"] is False


def test_explicit_year_does_not_get_replaced_by_episode_year(context):
    spec = {"family": "utilization", "start": "2025-01-05", "end": "2025-01-30"}
    result = NaturalLanguageQueryInterpreter(FixedProvider(ready(spec))).interpret(
        "How many sessions occurred January 5–30, 2025?", context)
    assert (result.query_spec.start, result.query_spec.end) == (date(2025, 1, 5), date(2025, 1, 30))


@pytest.mark.parametrize("changes", [
    {"patient_id": "OTHER-PATIENT"},
    {"family": "diagnosis"},
    {"service_types": ["psychotherapy"]},
    {"start": "2026-01-31", "end": "2026-01-05"},
    {"start": "2026-02-30"},
    {"consecutive_weeks": 1},
    {"min_minutes": -1},
    {"min_sessions": -1},
    {"computed_minutes": 73},
])
def test_invalid_ready_specs_cannot_cross_interpreter_boundary(changes, context):
    provider = FixedProvider(ready({"family": "utilization", **changes}))
    with pytest.raises(ValueError):
        NaturalLanguageQueryInterpreter(provider).interpret("Review the episode.", context)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("spec", [
    {"family": "compare_periods", "start": "2026-01-05", "end": "2026-01-30"},
    {"family": "cohort"},
])
def test_ready_requires_question_specific_comparison_inputs(spec, context):
    with pytest.raises(ValueError):
        NaturalLanguageQueryInterpreter(FixedProvider(ready(spec))).interpret("Compare the episode.", context)


@pytest.mark.parametrize("spec", [
    {"family": "compare_periods", "change_date": "2026-01-19"},
    {"family": "compare_periods", "start": "2026-01-05", "end": "2026-01-30",
     "change_date": "2026-01-05"},
    {"family": "compare_periods", "start": "2026-01-05", "end": "2026-01-30",
     "change_date": "2026-01-31"},
    {"family": "encounters", "start": "2026-01-05", "end": "2026-01-30",
     "dates": ["2026-02-01"]},
])
def test_ready_dates_must_support_requested_period_operation(spec, context):
    with pytest.raises(ValueError):
        NaturalLanguageQueryInterpreter(FixedProvider(ready(spec))).interpret("Review this period.", context)


@pytest.mark.parametrize("response", [
    {"status": "ready", "query_spec": None},
    {"status": "needs_clarification", "query_spec": {"family": "utilization"},
     "clarification_question": "Which period?"},
    {"status": "needs_clarification", "query_spec": None, "clarification_question": None},
    {"status": "needs_clarification", "query_spec": None, "clarification_question": "  "},
    {"status": "unsupported", "query_spec": {"family": "utilization"},
     "explanation": "Cannot answer this request."},
    {"status": "unknown", "query_spec": None},
    {"status": "ready", "query_spec": {"family": "utilization"}, "answer": "73 minutes"},
])
def test_interpretation_envelope_rejects_invalid_states_and_inferred_answers(response, context):
    with pytest.raises(ValueError):
        NaturalLanguageQueryInterpreter(FixedProvider(response)).interpret("Review therapy.", context)


@pytest.mark.parametrize("clarification", [
    "Which review period should I use?",
    "Which year do these dates refer to?",
    "Which service types should I include?",
    "What date separates the comparison periods?",
    "What minimum session or minute threshold should I apply?",
])
def test_clarification_remains_non_executable(clarification, context):
    provider = FixedProvider({"status": "needs_clarification", "query_spec": None,
                              "clarification_question": clarification, "explanation": None})
    result = NaturalLanguageQueryInterpreter(provider).interpret("Compare my therapy.", context)
    assert result.status == "needs_clarification"
    assert result.query_spec is None
    assert result.clarification_question == clarification


def test_unknown_episode_year_is_preserved_as_missing_context():
    context = QueryContext(patient_id="DEMO-NL-1", patient_name="Cedar Example", episode_year=None)
    provider = FixedProvider({"status": "needs_clarification", "query_spec": None,
                              "clarification_question": "Which year?", "explanation": None})
    result = NaturalLanguageQueryInterpreter(provider).interpret("Review January therapy.", context)
    assert context.episode_year is None
    assert result.query_spec is None


def test_unsupported_output_contains_no_spec_or_clinical_answer(context):
    explanation = "The supported query families cannot answer this request."
    provider = FixedProvider({"status": "unsupported", "query_spec": None,
                              "clarification_question": None, "explanation": explanation})
    result = NaturalLanguageQueryInterpreter(provider).interpret("What treatment should I prescribe?", context)
    assert result.status == "unsupported"
    assert result.query_spec is None
    assert result.explanation == explanation


def test_context_rejects_unrequested_fields():
    with pytest.raises(ValueError):
        QueryContext(patient_id="DEMO-NL-1", patient_name="Cedar Example", episode_year=2026,
                     source_text="Clinical source text must not enter the query interpreter")


@pytest.mark.parametrize("question", ["", " \n\t"])
def test_empty_question_fails_before_inference(question, context):
    provider = FixedProvider(ready({"family": "utilization"}))
    with pytest.raises(ValueError):
        NaturalLanguageQueryInterpreter(provider).interpret(question, context)
    assert provider.calls == []


@pytest.fixture
def offline_cli_provider():
    provider = object.__new__(CodexCLIProvider)
    provider.config = ProviderConfig()
    provider.executable = "offline-codex"
    provider.cli_version = "offline-fixture"
    provider.reset_usage()
    return provider


def test_provider_structured_output_passes_schema_and_records_reported_usage(
        offline_cli_provider, monkeypatch):
    provider = offline_cli_provider
    response = ready({"family": "utilization", "patient_id": "DEMO-NL-1"})
    schema = interpretation_schema()
    reported_usage = {"input_tokens": 120, "output_tokens": 30, "cached_input_tokens": 10}
    calls = []

    def fixed_cli(command, request, folder):
        calls.append((command, request, folder))
        assert json.loads((folder / "schema.json").read_text(encoding="utf-8")) == schema
        (folder / "answer.json").write_text(json.dumps(response), encoding="utf-8")
        event = {"type": "turn.completed", "usage": reported_usage}
        return SimpleNamespace(returncode=0, stdout=json.dumps(event), stderr="")

    monkeypatch.setattr(provider, "run_cli", fixed_cli)
    assert provider.structured_output("Fixed interpretation request.", schema) == response
    assert len(calls) == 1
    command, request, folder = calls[0]
    assert request == "Fixed interpretation request."
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command and "--ignore-user-config" in command
    assert "project_doc_max_bytes=0" in command and "features.shell_tool=false" in command
    assert "features.apply_patch_freeform=false" in command and "features.multi_agent=false" in command
    assert command[command.index("--output-schema") + 1] == str(folder / "schema.json")
    assert not folder.exists()
    usage = provider.usage(0.2)
    assert (usage.model_calls, usage.input_tokens, usage.output_tokens, usage.cached_tokens) == (1, 120, 30, 10)
    assert usage.call_metrics[0]["purpose"] == "query_interpretation"
    assert usage.call_metrics[0]["status"] == "completed"
    assert usage.call_metrics[0]["tokens"] == reported_usage
    assert usage.call_metrics[0]["started_at"] and usage.call_metrics[0]["ended_at"]
    assert usage.cost_usd is None


def test_provider_rejects_malformed_json_without_retry(offline_cli_provider, monkeypatch):
    provider = offline_cli_provider
    calls = []

    def fixed_cli(command, request, folder):
        calls.append(command)
        (folder / "answer.json").write_text("{invalid JSON", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(provider, "run_cli", fixed_cli)
    with pytest.raises(json.JSONDecodeError):
        provider.structured_output("Fixed request.", interpretation_schema())
    usage = provider.usage(0.1)
    assert len(calls) == usage.model_calls == 1
    assert usage.parse_failures == 1
    assert usage.call_metrics[0]["status"] == "parse_failed"
    assert usage.input_tokens is None and usage.output_tokens is None


def test_provider_rejects_tool_use_even_with_valid_interpretation(offline_cli_provider, monkeypatch):
    provider = offline_cli_provider

    def fixed_cli(command, request, folder):
        (folder / "answer.json").write_text(json.dumps(ready({"family": "utilization"})), encoding="utf-8")
        event = {"type": "item.completed", "item": {"type": "mcp_tool_call"}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(event), stderr="")

    monkeypatch.setattr(provider, "run_cli", fixed_cli)
    with pytest.raises(RuntimeError, match="tool operation"):
        provider.structured_output("Fixed request.", interpretation_schema())
    assert provider.usage(0.1).call_metrics[0]["status"] == "tool_rejected"


def test_provider_reports_cli_failure_instead_of_using_answer(offline_cli_provider, monkeypatch):
    provider = offline_cli_provider

    def fixed_cli(command, request, folder):
        (folder / "answer.json").write_text(json.dumps(ready({"family": "utilization"})), encoding="utf-8")
        event = {"type": "error", "message": "offline authentication error"}
        return SimpleNamespace(returncode=1, stdout=json.dumps(event), stderr="")

    monkeypatch.setattr(provider, "run_cli", fixed_cli)
    with pytest.raises(RuntimeError, match="offline authentication error"):
        provider.structured_output("Fixed request.", interpretation_schema())
    assert provider.usage(0.1).call_metrics[0]["status"] == "cli_failed"


def test_provider_timeout_has_one_attempt_and_no_fabricated_usage(offline_cli_provider, monkeypatch):
    provider = offline_cli_provider
    calls = []

    def fixed_cli(command, request, folder):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, provider.config.timeout_seconds)

    monkeypatch.setattr(provider, "run_cli", fixed_cli)
    with pytest.raises(RuntimeError, match="timed out; no retry"):
        provider.structured_output("Fixed request.", interpretation_schema())
    usage = provider.usage(0.1)
    assert len(calls) == usage.model_calls == 1
    assert usage.call_metrics[0]["status"] == "timeout"
    assert usage.input_tokens is None and usage.output_tokens is None
