"""Lifecycle checks with a recording extractor; these tests never call a model."""
import json
import os
import subprocess
import sys

import pytest

from conftest import PROJECT_ROOT

from clinical_intelligence.pipeline import load_patient, process
from clinical_intelligence.storage import SQLiteStore


class RecordingExtractor:
    def __init__(self, evidence, service, key="fixture-v1", fail=False):
        self.evidence = evidence
        self.service = service
        self.key = key
        self.fail = fail
        self.calls = 0

    def extract(self, document):
        self.calls += 1
        if self.fail:
            raise ValueError("Synthetic extraction failure")
        value = self.evidence(document.document_id,
                              [self.service(quote=document.text)], key=self.key)
        value.usage.model_calls = 1
        return value


def source(tmp_path, name="original.txt", text="Synthetic explicit clinical evidence"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_renamed_duplicate_after_restart_does_not_extract(evidence, service, tmp_path):
    original = source(tmp_path)
    renamed = source(tmp_path, "renamed.txt")
    database = tmp_path / "clinical.sqlite"
    initial = RecordingExtractor(evidence, service)
    with SQLiteStore(database) as store:
        first = process(store, [original], initial)
        before = load_patient(store, "SYN-P1")
        assert first["extracted"] == first["model_calls"] == initial.calls == 1
    after_restart = RecordingExtractor(evidence, service, fail=True)
    with SQLiteStore(database) as store:
        second = process(store, [renamed], after_restart)
        after = load_patient(store, "SYN-P1")
        assert second["cache_hits"] == 1
        assert second["registered"] == second["extracted"] == second["model_calls"] == 0
        assert after_restart.calls == 0
        assert len(store.documents()) == len(store.attempts()) == 1
        assert before == after


def test_same_content_new_configuration_requires_one_new_extraction(evidence, service, tmp_path):
    path = source(tmp_path)
    with SQLiteStore(tmp_path / "clinical.sqlite") as store:
        first = RecordingExtractor(evidence, service, key="model-a-schema-1")
        changed = RecordingExtractor(evidence, service, key="model-b-schema-1")
        process(store, [path], first)
        report = process(store, [path], changed)
        assert report["registered"] == report["cache_hits"] == 0
        assert report["extracted"] == changed.calls == 1
        assert len(store.documents()) == 1
        document = store.documents()[0]
        assert store.extraction(document.document_id, first.key) is not None
        assert store.extraction(document.document_id, changed.key) is not None


def test_changed_content_is_a_new_fingerprint_and_not_a_cache_hit(evidence, service, tmp_path):
    path = source(tmp_path)
    extractor = RecordingExtractor(evidence, service)
    with SQLiteStore(tmp_path / "clinical.sqlite") as store:
        process(store, [path], extractor)
        path.write_text("Changed synthetic source evidence", encoding="utf-8")
        report = process(store, [path], extractor)
        assert report["registered"] == report["extracted"] == 1
        assert report["cache_hits"] == 0
        assert len(store.documents()) == 2
        assert extractor.calls == 2


def test_registered_but_unextracted_evidence_blocks_clinical_answers(evidence, service, tmp_path):
    path = source(tmp_path)
    with SQLiteStore(tmp_path / "clinical.sqlite") as store:
        process(store, [path], RecordingExtractor(evidence, service))
        store.register("additional-unprocessed.txt", "Not yet extracted clinical evidence")
        with pytest.raises(ValueError, match="incomplete"):
            load_patient(store, "SYN-P1")


def test_failed_extraction_is_explicit_and_blocks_zero_care_answer(evidence, service, tmp_path):
    path = source(tmp_path)
    with SQLiteStore(tmp_path / "clinical.sqlite") as store:
        report = process(store, [path], RecordingExtractor(evidence, service, fail=True))
        assert report["failed"] == 1
        assert report["documents"][0]["status"] == "failed"
        assert store.documents()[0].status == "failed"
        assert store.attempts()[0]["status"] == "failed"
        with pytest.raises(ValueError, match="incomplete"):
            load_patient(store, "SYN-P1")
        # A successful retry makes coverage complete; failure was not permanent zero care.
        report = process(store, [path], RecordingExtractor(evidence, service))
        assert report["extracted"] == 1
        assert load_patient(store, "SYN-P1").events[0].minute_options == [45]


def test_new_cli_process_reloads_abstraction_without_provider(evidence, service, tmp_path):
    path = source(tmp_path, text="Synthetic evidence — café 中文")
    database = tmp_path / "clinical.sqlite"
    with SQLiteStore(database) as store:
        process(store, [path], RecordingExtractor(evidence, service))
        load_patient(store, "SYN-P1")
        attempts_before = store.attempts()
    # Starting a genuinely new Python process proves persistence across interpreter exit.
    # Any accidental provider construction would fail this process.
    code = """
from clinical_intelligence import provider
def forbidden(*args, **kwargs):
    raise AssertionError('A persisted inspect operation must not construct a model provider')
provider.CodexCLIProvider = forbidden
from clinical_intelligence.cli import main
import sys
raise SystemExit(main(sys.argv[1:]))
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    result = subprocess.run([sys.executable, "-c", code, "--db", str(database),
                             "inspect", "--patient", "SYN-P1"],
                            cwd=PROJECT_ROOT, capture_output=True,
                            encoding="utf-8", timeout=20, env=environment)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["events"][0]["minute_options"] == [45]
    assert output["source_claims"][0]["passages"][0]["quote"] == path.read_text(encoding="utf-8")
    with SQLiteStore(database) as store:
        assert store.attempts() == attempts_before



def test_parallel_extraction_has_ten_independent_workers_and_serial_storage(evidence, service, tmp_path, monkeypatch):
    from threading import Barrier, Lock, get_ident
    barrier, lock = Barrier(10, timeout=10), Lock()
    main_thread = get_ident()
    active = maximum = 0
    workers = []
    paths = [source(tmp_path, f"note-{i:02d}.txt", f"Independent source {i}") for i in range(10)]
    paths.append(source(tmp_path, "renamed.txt", "Independent source 0"))

    class IndependentExtractor(RecordingExtractor):
        def extract(self, document):
            nonlocal active, maximum
            assert get_ident() != main_thread
            self.calls += 1
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                barrier.wait()
                value = evidence(document.document_id,
                    [service(quote=document.text, encounter_ref=document.document_id)], key=self.key)
                value.usage.model_calls = 1  # Fixture accounting, not a real inference call.
                return value
            finally:
                with lock:
                    active -= 1

    def factory():
        worker = IndependentExtractor(evidence, service)
        workers.append(worker)
        return worker

    with SQLiteStore(tmp_path / "parallel.sqlite") as store:
        save = store.save_extraction
        def save_on_main(extraction):
            assert get_ident() == main_thread
            save(extraction)
        monkeypatch.setattr(store, "save_extraction", save_on_main)
        def progress(item):
            assert get_ident() == main_thread
        report = process(store, paths, RecordingExtractor(evidence, service), progress,
                         max_workers=10, extractor_factory=factory)
        assert maximum == 10
        assert len(workers) == 10 and all(w.calls == 1 for w in workers)
        assert report["extracted"] == report["registered"] == report["model_calls"] == 10
        assert report["cache_hits"] == 1 and report["failed"] == 0
        assert len(store.documents()) == len(store.attempts()) == 10
        assert len(load_patient(store, "SYN-P1").events) == 10
        assert [r["source"] for r in report["documents"]] == [p.name for p in sorted(paths)]
        def forbidden():
            raise AssertionError("Cached sources must not construct inference workers")
        replay = process(store, paths, RecordingExtractor(evidence, service, fail=True),
                         max_workers=10, extractor_factory=forbidden)
        assert replay["cache_hits"] == 11 and replay["model_calls"] == 0


def test_parallel_failure_is_not_retried_and_next_run_only_extracts_failure(evidence, service, tmp_path):
    paths = [source(tmp_path, "good.txt", "Good evidence"), source(tmp_path, "bad.txt", "Bad evidence")]
    workers = []
    class SelectiveExtractor(RecordingExtractor):
        def extract(self, document):
            self.fail = document.text == "Bad evidence"
            return super().extract(document)
    def factory():
        worker = SelectiveExtractor(evidence, service)
        workers.append(worker)
        return worker
    with SQLiteStore(tmp_path / "parallel.sqlite") as store:
        first = process(store, paths, RecordingExtractor(evidence, service),
                        max_workers=10, extractor_factory=factory)
        assert first["failed"] == first["extracted"] == 1
        assert len(workers) == 2 and all(w.calls == 1 for w in workers)
        assert len(store.attempts()) == 2
        second = process(store, paths, RecordingExtractor(evidence, service),
                         max_workers=10, extractor_factory=factory)
        assert second["cache_hits"] == second["failed"] == 1
        assert len(workers) == 3 and all(w.calls == 1 for w in workers)
        assert len(store.attempts()) == 3


def test_parallel_extraction_rejects_shared_mutable_extractor(evidence, service, tmp_path):
    with SQLiteStore(tmp_path / "parallel.sqlite") as store:
        with pytest.raises(ValueError, match="independent extractor"):
            process(store, [], RecordingExtractor(evidence, service), max_workers=10)
        with pytest.raises(ValueError, match="between 1 and 10"):
            process(store, [], RecordingExtractor(evidence, service), max_workers=11,
                    extractor_factory=lambda: RecordingExtractor(evidence, service))


def test_process_cli_requests_ten_independent_extractors(tmp_path, monkeypatch, capsys):
    from clinical_intelligence import cli, extraction, provider
    path = source(tmp_path)
    made = []
    class FixedExtractor:
        def __init__(self, model):
            made.append(self)
    monkeypatch.setattr(provider, "CodexCLIProvider", lambda config: config)
    monkeypatch.setattr(extraction, "LangExtractExtractor", FixedExtractor)
    def inspect_process(store, paths, extractor, progress, *, max_workers, extractor_factory):
        assert max_workers == 10 and paths == [path]
        assert extractor_factory() is not extractor
        assert len(made) == 2
        return {"failed": 0}
    monkeypatch.setattr(cli, "process", inspect_process)
    assert cli.main(["--db", str(tmp_path / "cli.sqlite"), "process", "--input", str(path),"--extractor","baseline","--workers","10"]) == 0
    assert json.loads(capsys.readouterr().out) == {"failed": 0}


def test_optimized_cli_parameters_reach_each_independent_extractor(tmp_path,monkeypatch):
    from clinical_intelligence import cli, provider, luna_candidates
    path=source(tmp_path);made=[]
    class FixedExtractor:
        def __init__(self,model,configuration):
            self.model=model;self.configuration=configuration;made.append(self)
    monkeypatch.setattr(provider,'CodexCLIProvider',lambda config:config)
    monkeypatch.setattr(luna_candidates,'CandidateExtractor',FixedExtractor)
    def inspect_process(store,paths,extractor,progress,*,max_workers,extractor_factory):
        second=extractor_factory()
        assert max_workers==2 and second is not extractor
        assert all(e.model.reasoning_effort==e.configuration['reasoning']=='medium' and e.model.timeout_seconds==60 for e in made)
        assert all(e.configuration['flow']=='clinical_partition' for e in made)
        return {'failed':0}
    monkeypatch.setattr(cli,'process',inspect_process)
    assert cli.main(['--db',str(tmp_path/'cli.sqlite'),'process','--input',str(path),
                     '--reasoning','medium','--timeout','60','--workers','2'])==0
