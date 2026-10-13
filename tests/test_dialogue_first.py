"""Offline software checks; no clinical accuracy assertions or live model calls."""
import json
import sqlite3
from pathlib import Path

import pytest

from clinical_intelligence.clinical_notes.dataset import sha, write_json
from clinical_intelligence.clinical_notes.schema import ClinicalFact
from clinical_intelligence.dialogue_first.contract import DialogueFact, inspect, inspect_repair, primary_projection, schema
from clinical_intelligence.dialogue_first.dataset import Document, freeze_inputs, load_inputs, note_document, source_index, training_documents
from clinical_intelligence.dialogue_first.prompt import prompt
from clinical_intelligence.dialogue_first.runtime import Budget, run
from clinical_intelligence.provider import ProviderConfig


@pytest.fixture
def doc():
    text = "[doctor] Any headache?[patient] No .[doctor] We could arrange a test .[patient] No headache ."
    return Document("test:dialogue:1", "TEST1", "test", text, sha(text), sha(text), 0)


def proposal(doc):
    ids = [s["source_id"] for s in source_index(doc)["source_catalogue"]]
    return {"document_id": doc.document_id, "facts": [{
        "category": "symptom", "concept": "headache", "polarity": "absent", "temporality": "current",
        "experiencer": "patient", "attributes": None, "assertion_basis": "patient_report",
        "attribution_confidence": "context_supported", "clinical_status": None,
        "evidence": {"source_ids": [ids[0], ids[1], ids[-1]]}}], "relationships": []}


def test_exact_turns_cover_original_with_labels(doc):
    index = source_index(doc)
    assert "".join(t["quote"] for t in index["turns"]) == doc.text
    assert [t["speaker_label"] for t in index["turns"]] == ["[doctor]", "[patient]", "[doctor]", "[patient]"]
    for p in index["source_catalogue"]:
        assert doc.text[p["start"]:p["end"]] == p["quote"]
    assert source_index(doc) == index


def test_unicode_and_unlabelled_source():
    text = "开场🙂 [Doctor] Hi .[Patient] 嗯🙂 .\nSecond sentence."
    d = Document("unicode", "UNICODE", "test", text, sha(text), sha(text), 0)
    index = source_index(d)
    assert index["turns"][0]["speaker_label"] is None
    assert "".join(t["quote"] for t in index["turns"]) == text
    assert all(text[s["start"]:s["end"]] == s["quote"] for s in index["source_catalogue"])


def test_question_answer_repeated_mentions_provenance(doc):
    result = inspect(json.dumps(proposal(doc)), doc)
    assert result["status"] == "VALID"
    f = result["result"]["facts"][0]
    assert len(result["result"]["facts"]) == 1
    assert [p["turn_id"] for p in f["provenance"]] == ["t0001", "t0002", "t0004"]
    assert f["assertion_basis"] == "patient_report"
    assert len(f["supporting_evidence"]) == 2
    ClinicalFact.model_validate(primary_projection(result["result"])["facts"][0])


def test_legacy_fact_remains_accepted(doc):
    result = inspect(json.dumps(proposal(doc)), doc)["result"]
    legacy = primary_projection(result)["facts"][0]
    assert DialogueFact.model_validate(legacy).provenance == []


@pytest.mark.parametrize("mutation", ["unknown_id", "duplicate_id", "bad_polarity", "extra_field", "wrong_identity"])
def test_mechanical_rejections(doc, mutation):
    p = proposal(doc)
    if mutation == "unknown_id": p["facts"][0]["evidence"]["source_ids"] = ["unknown"]
    if mutation == "duplicate_id": p["facts"][0]["evidence"]["source_ids"] *= 2
    if mutation == "bad_polarity": p["facts"][0]["polarity"] = "confirmed"
    if mutation == "extra_field": p["facts"][0]["invented"] = True
    if mutation == "wrong_identity": p["document_id"] = "other"
    outcome = inspect(json.dumps(p), doc)
    assert outcome["status"] == "INVALID"
    assert outcome["errors"]


def test_partial_retains_valid_fact_and_remaps_relationship(doc):
    p = proposal(doc)
    p["facts"] = [{**p["facts"][0], "polarity": "invalid"}, p["facts"][0], p["facts"][0]]
    refs = p["facts"][1]["evidence"]
    p["relationships"] = [{"from_fact_index": 1, "to_fact_index": 2, "relation": "documented with", "evidence": refs},
        {"from_fact_index": 0, "to_fact_index": 1, "relation": "invalid target", "evidence": refs}]
    outcome = inspect(json.dumps(p), doc)
    assert outcome["status"] == "PARTIAL" and outcome["accepted_indices"] == [1, 2]
    assert len(outcome["result"]["relationships"]) == 1
    assert outcome["result"]["relationships"][0]["from_fact_index"] == 0


def test_source_hash_tampering_rejected(doc):
    from dataclasses import replace
    with pytest.raises(ValueError, match="hash"):
        source_index(replace(doc, text=doc.text + " extra"))


def test_source_freeze_tampering_rejected(tmp_path, doc):
    freeze_inputs(tmp_path, [doc], checkpoint="checkpoint")
    assert load_inputs(tmp_path) == [doc]
    path = tmp_path / "sources/TEST1.json"
    value = json.loads(path.read_text())
    value["turns"][0]["end"] += 1
    write_json(path, value)
    with pytest.raises(ValueError, match="index changed"):
        load_inputs(tmp_path)


def test_dataset_not_manually_constructed(tmp_path):
    path = tmp_path / "train.csv"
    path.write_text("dataset,encounter_id,dialogue,note\naci,D2N033,handmade,secret\n")
    with pytest.raises(ValueError, match="checksum"):
        training_documents(path)


def test_prompt_schema_payload_has_no_reference_or_fixed_concepts(doc):
    text = prompt(doc)
    assert "no predefined medical concept list" in text
    assert "question alone does not establish" in text
    assert "swapped speaker tags" in text
    body = json.loads(text.splitlines()[-1])
    assert set(body) == {"document_id", "encounter_id", "input_kind", "transcript", "turns", "source_catalogue"}
    assert schema(doc)["properties"]["document_id"]["enum"] == [doc.document_id]


def test_note_soap_secondary_smoke():
    path = Path(__file__).parents[1] / "examples/dialogue_first/soap-smoke.txt"
    d = note_document(path)
    assert d.input_kind == "note"
    assert "SOAP headings are context only" in prompt(d)
    assert json.loads(prompt(d).splitlines()[-1])["note"] == d.text
    assert all(s["speaker_label"] is None for s in source_index(d)["source_catalogue"])
    p = proposal(d)
    assert inspect(json.dumps(p), d)["status"] == "VALID"  # Mechanical fixture, no medical judgement.


def test_repair_preserves_accepted_and_semantic_fields(doc):
    initial = proposal(doc)
    initial["facts"].append({**initial["facts"][0], "evidence": {"source_ids": ["missing"]}})
    initial_raw = json.dumps(initial)
    outcome = inspect(initial_raw, doc)
    repaired = proposal(doc)
    repaired["facts"].append(repaired["facts"][0].copy())
    assert inspect_repair(json.dumps(repaired), initial_raw, outcome, doc)["status"] == "VALID"
    repaired["facts"][1]["temporality"] = "historical"
    assert inspect_repair(json.dumps(repaired), initial_raw, outcome, doc)["status"] == "INVALID"


def test_repair_does_not_add_or_drop_facts(doc):
    raw = json.dumps(proposal(doc))
    initial = inspect(raw, doc)
    p = proposal(doc)
    p["facts"] = []
    assert inspect_repair(json.dumps(p), raw, initial, doc)["status"] == "INVALID"


class FakeProvider:
    config = ProviderConfig()
    cli_version = "offline-fake"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def preflight(self): pass
    def command(self, path): return ["offline-fake", str(path)]

    def dispatch(self, doc, folder):
        self.calls += 1
        value = next(self.responses)
        if isinstance(value, Exception): raise value
        raw = json.dumps(value)
        (folder / "raw-response.json").write_text(raw, encoding="utf-8")
        write_json(folder / "usage.json", {"input_tokens": 5, "output_tokens": 10}, immutable=True)
        return raw, {"input_tokens": 5, "output_tokens": 10}


def test_pilot_success_never_resampled(tmp_path, doc):
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    provider = FakeProvider([proposal(doc)])
    assert run(tmp_path, provider=provider)["successfully_processed"] == 1
    assert run(tmp_path, provider=provider)["provider_requests_including_failures"] == 1
    assert provider.calls == 1
    assert (tmp_path / "encounters/TEST1/summary.md").exists()


def test_only_one_structural_repair(tmp_path, doc):
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    bad = proposal(doc)
    bad["facts"][0]["evidence"]["source_ids"] = ["missing"]
    provider = FakeProvider([bad, proposal(doc)])
    report = run(tmp_path, provider=provider)
    assert provider.calls == 2
    assert report["successfully_processed"] == 1
    assert report["structural_repair_requests"] == 1
    assert run(tmp_path, provider=provider)["provider_requests_including_failures"] == 2


def test_failed_transport_no_retry_and_null_usage(tmp_path, doc):
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    provider = FakeProvider([RuntimeError("uncertain transport completion")])
    report = run(tmp_path, provider=provider)
    assert provider.calls == 1
    assert report["encounters"][0]["status"] == "FAILED"
    assert report["usage_records"] == 0
    assert json.loads(report["requests"][0]["usage"]) is None
    assert report["provider_requests_including_failures"] == 1


def test_failed_repair_keeps_partial_output(tmp_path, doc):
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    bad = proposal(doc)
    bad["facts"].append({**bad["facts"][0], "evidence": {"source_ids": ["missing"]}})
    report = run(tmp_path, provider=FakeProvider([bad, RuntimeError("repair failed")]))
    assert report["encounters"][0]["status"] == "PARTIAL"
    assert report["encounters"][0]["facts"] == 1
    assert report["provider_requests_including_failures"] == 2


def test_atomic_global_budget_terminal_immutability_and_no_replay(tmp_path):
    ids = [f"d{i}" for i in range(11)]
    budget = Budget(tmp_path, {"frozen": True}, ids)
    for identity in ids[:10]:
        assert budget.reserve(identity, 1)
        budget.finish(identity, 1, "INVALID", 1.0, None, "bad JSON")
        assert budget.reserve(identity, 2)
        budget.finish(identity, 2, "FAILED", 1.0, None, "failed")
    assert not budget.reserve("d0", 1)
    with pytest.raises(RuntimeError, match="20-request"):
        budget.reserve(ids[-1], 1)
    with pytest.raises(sqlite3.IntegrityError):
        with budget.connect() as db: db.execute("DELETE FROM requests")
    with pytest.raises(sqlite3.IntegrityError):
        with budget.connect() as db: db.execute("UPDATE requests SET status='VALID'")
    with pytest.raises(ValueError, match="identity changed"):
        Budget(tmp_path, {"frozen": False}, ids)


@pytest.mark.parametrize("status", ["VALID", "FAILED"])
def test_valid_failed_requests_cannot_trigger_repair(tmp_path, status):
    budget = Budget(tmp_path, {}, ["d"])
    assert budget.reserve("d", 1)
    budget.finish("d", 1, status, 0.0, None, None)
    with pytest.raises(ValueError, match="mechanical"):
        budget.reserve("d", 2)


def test_interrupted_reservation_blocks_replay(tmp_path, doc):
    from clinical_intelligence.dialogue_first.runtime import initialize
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    provider = FakeProvider([])
    identity, _ = initialize(tmp_path, provider)
    budget = Budget(tmp_path, identity, [doc.document_id])
    budget.reserve(doc.document_id, 1)
    with pytest.raises(RuntimeError, match="Interrupted"):
        run(tmp_path, provider=provider)
    assert provider.calls == 0


def test_offline_audit_replays_original_outputs(tmp_path, doc):
    from dialogue_first_audit import audit
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    provider = FakeProvider([proposal(doc)])
    run(tmp_path, provider=provider)
    result = audit(tmp_path)
    assert result["encounters"][0]["completed_raw_attempts_replayed"] == 1
    assert result["encounters"][0]["fact_evidence_spans_checked"] == 3
    assert provider.calls == 1


def test_offline_audit_detects_saved_provenance_tampering(tmp_path, doc):
    from dialogue_first_audit import audit
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    run(tmp_path, provider=FakeProvider([proposal(doc)]))
    path = tmp_path / "encounters/TEST1/outcome.json"
    outcome = json.loads(path.read_text())
    outcome["result"]["facts"][0]["provenance"][0]["turn_id"] = "invented"
    write_json(path, outcome)
    with pytest.raises(ValueError, match="provenance"):
        audit(tmp_path)


def relationship_repair_pair(doc):
    from copy import deepcopy
    original = proposal(doc)
    original["facts"].append(deepcopy(original["facts"][0]))
    refs = deepcopy(original["facts"][0]["evidence"])
    original["relationships"] = [
        {"from_fact_index": 0, "to_fact_index": 1, "relation": "documented with", "evidence": refs},
        {"from_fact_index": 0, "to_fact_index": 49, "relation": "source-supported relationship", "evidence": refs}]
    repaired = deepcopy(original)
    repaired["relationships"][1]["to_fact_index"] = 1
    return original, repaired


def test_invalid_relationship_endpoint_only_repair(doc):
    original, repaired = relationship_repair_pair(doc)
    raw = json.dumps(original)
    initial = inspect(raw, doc)
    outcome = inspect_repair(json.dumps(repaired), raw, initial, doc)
    assert initial["status"] == "PARTIAL" and outcome["status"] == "VALID"
    assert outcome["result"]["facts"] == initial["result"]["facts"]
    assert outcome["result"]["relationships"][0] == initial["result"]["relationships"][0]
    assert outcome["result"]["relationships"][1]["to_fact_index"] == 1


@pytest.mark.parametrize("mutation", ["valid_fact", "valid_fact_evidence", "valid_relation", "valid_endpoint",
    "relation_text", "relation_evidence", "add", "drop", "reorder", "still_invalid", "bool_endpoint"])
def test_relationship_index_guard_rejects_other_changes(doc, mutation):
    original, repaired = relationship_repair_pair(doc)
    if mutation == "valid_fact": repaired["facts"][0]["concept"] = "changed assertion"
    if mutation == "valid_fact_evidence": repaired["facts"][0]["evidence"]["source_ids"] = repaired["facts"][0]["evidence"]["source_ids"][:1]
    if mutation == "valid_relation": repaired["relationships"][0]["to_fact_index"] = 0
    if mutation == "valid_endpoint": repaired["relationships"][1]["from_fact_index"] = 1
    if mutation == "relation_text": repaired["relationships"][1]["relation"] = "different relationship"
    if mutation == "relation_evidence": repaired["relationships"][1]["evidence"] = {"source_ids": [source_index(doc)["source_catalogue"][2]["source_id"]]}
    if mutation == "add": repaired["relationships"].append(repaired["relationships"][0])
    if mutation == "drop": repaired["relationships"].pop()
    if mutation == "reorder": repaired["relationships"].reverse()
    if mutation == "still_invalid": repaired["relationships"][1]["to_fact_index"] = 48
    if mutation == "bool_endpoint": repaired["relationships"][0]["from_fact_index"] = False
    raw = json.dumps(original)
    result = inspect_repair(json.dumps(repaired), raw, inspect(raw, doc), doc)
    assert result["status"] == "INVALID"


def test_unchanged_invalid_relationship_remains_partial(doc):
    original, _ = relationship_repair_pair(doc)
    raw = json.dumps(original)
    assert inspect_repair(raw, raw, inspect(raw, doc), doc)["status"] == "PARTIAL"


def test_relationship_indices_use_original_accepted_fact_positions(doc):
    original, repaired = relationship_repair_pair(doc)
    # A rejected fact creates a gap; relations must use original indices, not compacted ones.
    original["facts"].insert(1, {**original["facts"][0], "polarity": "bad"})
    repaired["facts"].insert(1, {**repaired["facts"][0], "polarity": "bad"})
    original["relationships"][0]["to_fact_index"] = 2
    repaired["relationships"][0]["to_fact_index"] = 2
    repaired["relationships"][1]["to_fact_index"] = 2
    raw = json.dumps(original)
    outcome = inspect_repair(json.dumps(repaired), raw, inspect(raw, doc), doc)
    assert outcome["status"] == "PARTIAL"  # Rejected fact still unresolved.
    assert [r["to_fact_index"] for r in outcome["result"]["relationships"]] == [1, 1]


def test_invalid_evidence_cannot_be_fixed_by_changing_relation_indices(doc):
    original, repaired = relationship_repair_pair(doc)
    for value in (original, repaired):
        value["relationships"][1]["evidence"] = {"source_ids": ["missing"]}
    raw = json.dumps(original)
    assert inspect_repair(json.dumps(repaired), raw, inspect(raw, doc), doc)["status"] == "INVALID"


def test_offline_saved_repair_revalidation_preserves_history(tmp_path, doc, monkeypatch):
    from clinical_intelligence.dialogue_first import runtime
    from dialogue_first_revalidate import revalidate
    original, repaired = relationship_repair_pair(doc)
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    # Simulate the former guard's historical rejection, retaining both original responses.
    monkeypatch.setattr(runtime, "inspect_repair", lambda *args: {
        "status": "INVALID", "result": None, "accepted_indices": [], "errors": ["Repair changed relationships"]})
    provider = FakeProvider([original, repaired])
    run(tmp_path, provider=provider)
    protected = {p: sha(p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    record = revalidate(tmp_path, doc.encounter_id)
    assert record["historical_status"] == "PARTIAL" and record["revalidated_status"] == "VALID"
    assert record["facts_unchanged"] and record["provider_requests_added"] == 0
    assert record["provider_requests_total"] == provider.calls == 2
    assert record["index_changes"] == [{"relationship_index": 1, "field": "to_fact_index", "before": 49, "after": 1}]
    assert all(sha(p.read_bytes()) == digest for p, digest in protected.items())
    assert revalidate(tmp_path, doc.encounter_id) == record


@pytest.mark.parametrize("file_name,allowed", [("contract.py", True), ("runtime.py", False)])
def test_offline_revalidation_limits_implementation_drift(tmp_path, doc, monkeypatch, file_name, allowed):
    import dialogue_first_revalidate as offline
    original, repaired = relationship_repair_pair(doc)
    freeze_inputs(tmp_path, [doc], checkpoint="test")
    run(tmp_path, provider=FakeProvider([original, repaired]))
    current = offline.implementation_hashes()
    key = next(k for k in current if k.replace("\\", "/") == "dialogue_first/" + file_name)
    current[key] = "simulated-validator-change"
    monkeypatch.setattr(offline, "implementation_hashes", lambda: current)
    if allowed:
        assert offline.revalidate(tmp_path, doc.encounter_id)["changed_implementation_files"] == [key]
    else:
        with pytest.raises(ValueError, match="Unexpected implementation change"):
            offline.revalidate(tmp_path, doc.encounter_id)
