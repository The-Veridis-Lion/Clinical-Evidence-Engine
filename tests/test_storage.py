"""Persistence tests prove exact deduplication, grounding and version-aware reuse."""
import pytest

from clinical_intelligence.reconcile import reconcile
from clinical_intelligence.pipeline import load_patient
from clinical_intelligence.storage import SQLiteStore, input_digest


def test_duplicate_content_is_one_registered_document_after_restart(tmp_path):
    path = tmp_path / "test.sqlite"
    with SQLiteStore(path) as store:
        original, created = store.register("first.txt", "Exact source text\n")
        duplicate, duplicate_created = store.register("copied.txt", "Exact source text\n")
        assert created is True and duplicate_created is False
        assert duplicate.document_id == original.document_id
        assert len(store.documents()) == 1
    with SQLiteStore(path) as restarted:
        existing, created_again = restarted.register("first.txt", "Exact source text\n")
        assert created_again is False
        assert existing.source_names == ["copied.txt", "first.txt"]
        assert len(restarted.documents()) == 1


def test_restart_loads_claims_and_abstraction_without_model(tmp_path, evidence, service):
    path = tmp_path / "test.sqlite"
    text = "Patient received forty-five minutes of psychotherapy."
    with SQLiteStore(path) as store:
        document, _ = store.register("clinical.txt", text)
        extraction = evidence(document.document_id, [service(quote=text)], declared_id="SOURCE-1")
        store.save_extraction(extraction)
        abstract = reconcile([extraction])
        digest = input_digest([extraction], "policy-v1")
        store.save_abstraction(abstract, digest)
    with SQLiteStore(path) as restarted:
        loaded = restarted.extraction(document.document_id, "fixture-v1")
        assert loaded == extraction
        assert restarted.patient_ids() == [extraction.patient.patient_id]
        assert restarted.patient_extractions(extraction.patient.patient_id) == [extraction]
        assert restarted.abstraction(extraction.patient.patient_id, digest) == abstract
        assert restarted.abstraction(extraction.patient.patient_id, "changed-input") is None
        assert restarted.document(document.document_id).status == "extracted"


def test_extraction_version_is_retained_and_only_active_version_is_queried(tmp_path, evidence, service):
    with SQLiteStore(tmp_path / "test.sqlite") as store:
        document, _ = store.register("clinical.txt", "Exact phrase")
        first = evidence(document.document_id, [service(quote="Exact phrase")], key="v1")
        second = evidence(document.document_id, [service(quote="Exact phrase", reported_minutes=30)], key="v2")
        store.save_extraction(first)
        store.save_extraction(second)
        assert store.extraction(document.document_id, "v1") == first
        assert store.extraction(document.document_id, "v2") == second
        assert store.extraction(document.document_id, "v3") is None
        assert store.patient_extractions(first.patient.patient_id) == [second]
        store.activate_extraction(document.document_id, "v1")
        assert store.patient_extractions(first.patient.patient_id) == [first]


def test_ungrounded_quote_is_rejected_before_persistence(tmp_path, evidence, service):
    with SQLiteStore(tmp_path / "test.sqlite") as store:
        document, _ = store.register("clinical.txt", "Source said patient absent")
        extraction = evidence(document.document_id, [service(quote="Patient was present")])
        with pytest.raises(ValueError, match="Ungrounded"):
            store.save_extraction(extraction)
        assert store.document(document.document_id).status == "registered"
        assert store.extraction(document.document_id, extraction.extraction_key) is None


def test_input_digest_ignores_input_order_but_not_configuration(evidence, service):
    one = evidence("a", [service()])
    two = evidence("b", [service(encounter_ref="SYN-E2")])
    assert input_digest([one, two], "v1") == input_digest([two, one], "v1")
    assert input_digest([one, two], "v1") != input_digest([one, two], "v2")
    changed = two.model_copy(update={"extraction_key": "new-model"})
    assert input_digest([one, two], "v1") != input_digest([one, changed], "v1")


def test_identical_snapshot_resave_is_an_idempotent_noop(tmp_path, evidence, service):
    with SQLiteStore(tmp_path / "test.sqlite") as store:
        document, _ = store.register("clinical.txt", "Exact phrase")
        snapshot = evidence(document.document_id, [service(quote="Exact phrase", actual_intervals=[], reported_minutes=30)])
        store.save_extraction(snapshot)
        before = store.connection.total_changes
        store.save_extraction(snapshot.model_copy(deep=True))
        assert store.connection.total_changes == before
        assert store.extraction(document.document_id, snapshot.extraction_key) == snapshot
        assert store.connection.execute("SELECT count(*) FROM extractions").fetchone()[0] == 1


def test_divergent_same_key_snapshot_is_rejected_before_cached_fact_changes(tmp_path, evidence, service):
    with SQLiteStore(tmp_path / "test.sqlite") as store:
        document, _ = store.register("clinical.txt", "Exact phrase")
        first = evidence(document.document_id, [service(quote="Exact phrase", actual_intervals=[], reported_minutes=30)])
        divergent = evidence(document.document_id, [service(quote="Exact phrase", actual_intervals=[], reported_minutes=60)])
        store.save_extraction(first)
        assert load_patient(store, first.patient.patient_id).events[0].minute_options == [30]
        before = store.connection.total_changes
        with pytest.raises(ValueError, match="Immutable.*divergent same-key"):
            store.save_extraction(divergent)
        assert store.connection.total_changes == before
        assert store.extraction(document.document_id, first.extraction_key) == first
        assert load_patient(store, first.patient.patient_id).events[0].minute_options == [30]

        # A new extraction version is a distinct immutable snapshot, not an overwrite.
        new_version = divergent.model_copy(update={"extraction_key": "fixture-v2"})
        store.save_extraction(new_version)
        assert store.document(document.document_id).extraction_key == "fixture-v2"
        assert store.extraction(document.document_id, first.extraction_key) == first
        assert load_patient(store, first.patient.patient_id).events[0].minute_options == [60]
