"""New corpus expectations come from independent clock arithmetic, not saved answers."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from clinical_intelligence.audit import render_audit
from clinical_intelligence.demo import run_demo, corpus, SyntheticFixtureExtractor
from clinical_intelligence.pipeline import load_patient, process
from clinical_intelligence.query import query_patient, QuerySpec
from clinical_intelligence.storage import SQLiteStore
from clinical_intelligence.domain import State


def delta(start, end):
    return int((datetime.strptime(end, '%H:%M') - datetime.strptime(start, '%H:%M')).total_seconds() / 60)


def test_synthetic_reconciliation_grounding_duplicate_and_restart(tmp_path):
    database = tmp_path / 'demo.sqlite'
    # Independently derived from authored clock facts, outside engine arithmetic.
    group_minutes = delta('09:12', '10:31') - delta('09:41', '09:49')
    conflict_options = [37, 49]  # Independent signed source statements, not prior answers.
    expected_options = [group_minutes + minutes for minutes in conflict_options]
    with SQLiteStore(database) as store:
        first = run_demo(store)
        assert first['processing']['registered'] == first['processing']['extracted'] == len(corpus())
        assert first['processing']['cache_hits'] == 1
        assert first['processing']['model_calls'] == first['processing']['failed'] == 0
        assert store.patient_ids() == ['DEMO-CEDAR', 'DEMO-JUNIPER']
        abstraction = load_patient(store, 'DEMO-CEDAR')
        group = next(e for e in abstraction.events if e.encounter_ref == 'LAB-G7')
        assert group.minute_options == [group_minutes]
        conflicting = next(e for e in abstraction.events if e.encounter_ref == 'LAB-I8')
        assert conflicting.state == State.CONFLICTED
        assert conflicting.minute_options == conflict_options
        assert conflicting.conflicts
        cedar = first['answers']['DEMO-CEDAR']
        assert cedar['result']['totals']['minute_alternatives'] == expected_options
        assert cedar['result']['totals']['sessions']['value'] == 2
        juniper = first['answers']['DEMO-JUNIPER']
        assert juniper['result']['totals']['minutes']['value'] == delta('15:03', '15:26')
        assert juniper['result']['totals']['sessions']['value'] == 1
        assert cedar['provenance_completeness'] == juniper['provenance_completeness'] == 'complete'
        audit = render_audit(cedar)
        for name in ['DEMO-AMENDMENT', 'DEMO-ACTIVITY', 'DEMO-ATTENDANCE', 'DEMO-DURATION-A', 'DEMO-DURATION-B']:
            assert name in audit
        for quote in [r['claims'][0]['quote'] for r in corpus() if r['declared_id'] in ['DEMO-AMENDMENT', 'DEMO-ACTIVITY']]:
            assert quote in audit
        docs = {d.document_id: d for d in store.documents()}
        claims = {c.claim_id: c for c in abstraction.source_claims}
        calculation = next(c for c in group.calculations if c.output == {'minutes': group_minutes})
        ids = {docs[claims[i].document_id].declared_id for i in calculation.claim_ids}
        assert {'DEMO-ATTENDANCE', 'DEMO-ACTIVITY', 'DEMO-AMENDMENT'} <= ids
        for extraction in store.patient_extractions('DEMO-CEDAR'):
            for claim in extraction.claims:
                for passage in claim.passages:
                    assert docs[passage.document_id].text[passage.start:passage.end] == passage.quote
        compliance = query_patient(abstraction, QuerySpec(family='compliance'), store.documents())
        assert 'cannot_determine' in json.dumps(compliance, default=str)
        # The existing narrow field locator does not recognize intervening words
        # in "115 patient-present minutes"; preserve and expose that audit gap.
        assert compliance['provenance_completeness'] == 'partial'
        assert 'required_minutes' in json.dumps(compliance, default=str)
        second = run_demo(store)
        assert second['processing']['registered'] == second['processing']['extracted'] == 0
        assert second['processing']['cache_hits'] == len(corpus()) + 1
        assert second['answers'] == first['answers']
    environment = dict(os.environ)
    completed = subprocess.run([sys.executable, '-m', 'clinical_intelligence', '--db', str(database),
        'query', '--patient', 'DEMO-CEDAR', '--family', 'utilization'],
        capture_output=True, text=True, encoding='utf-8', check=True, env=environment)
    assert json.loads(completed.stdout) == json.loads(json.dumps(first['answers']['DEMO-CEDAR'], default=str))


def test_synthetic_examples_match_packaged_corpus():
    root = Path(__file__).resolve().parents[1]
    for row in corpus():
        assert (root / 'examples/synthetic/documents' / row['name']).read_text(encoding='utf-8') == row['text']


def test_correction_effect_before_and_after_retransmission(tmp_path):
    rows = corpus()
    with SQLiteStore(tmp_path / 'incremental.sqlite') as store:
        extractor = SyntheticFixtureExtractor(rows)
        for index in [0, 1, 2, 3]:
            path = tmp_path / rows[index]['name']
            path.write_text(rows[index]['text'], encoding='utf-8')
            assert process(store, [path], extractor)['failed'] == 0
            if index >= 1:
                event = load_patient(store, 'DEMO-CEDAR').events[0]
                departure = '10:46' if index == 1 else '10:31'
                assert event.minute_options == [delta('09:12', departure) - delta('09:41', '09:49')]


def test_benchmark_reports_partial_provenance_instead_of_hiding_it(tmp_path):
    from clinical_intelligence.evaluation import benchmark
    with SQLiteStore(tmp_path / 'benchmark.sqlite') as store:
        run_demo(store)
        result = benchmark(store, 1)
        assert result['documents'] == len(corpus())
        assert result['patients'] == 2
        assert result['cli_provenance_completeness'] == ['partial']
