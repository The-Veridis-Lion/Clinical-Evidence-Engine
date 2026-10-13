"""Offline synthetic-claim fixture, explicitly not live model extraction."""
from __future__ import annotations
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
from .domain import DocumentExtraction, ExtractionUsage
from .extraction import locate_passage, normalize_clock_fields
from .pipeline import process, load_patient
from .query import QuerySpec, query_patient


def corpus():
    return json.loads(files('clinical_intelligence').joinpath('synthetic.json').read_text(encoding='utf-8'))


class SyntheticFixtureExtractor:
    """Hand-authored claims let deterministic behavior run without a provider."""
    def __init__(self, rows=None):
        rows = corpus() if rows is None else rows
        self.rows = {r['text']: r for r in rows}
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        self.key = 'synthetic-fixture-v1:' + digest

    def extract(self, document):
        row = self.rows[document.text]
        claims = []
        for index, spec in enumerate(row['claims']):
            spec = dict(spec)
            quote = spec.pop('quote')
            passage = locate_passage(document, quote, None, None)
            kind = spec['kind']
            spec = normalize_clock_fields(kind, spec)
            claims.append(dict(spec, claim_id=f'{document.document_id}:{index}',
                               document_id=document.document_id, patient_id=row['patient']['patient_id'],
                               passages=[passage.model_dump()]))
        return DocumentExtraction.model_validate(dict(document_id=document.document_id,
            extraction_key=self.key, declared_id=row['declared_id'], patient=row['patient'], claims=claims,
            usage=ExtractionUsage(provider='hand-authored-synthetic-fixture', model='none',
                settings={}, latency_seconds=0, model_calls=0).model_dump()))


def run_demo(store):
    rows = corpus()
    with TemporaryDirectory() as directory:
        paths = []
        for row in rows:
            path = Path(directory) / row['name']
            path.write_text(row['text'], encoding='utf-8')
            paths.append(path)
        duplicate = Path(directory) / 'duplicate_attendance.txt'
        duplicate.write_text(rows[0]['text'], encoding='utf-8')
        paths.append(duplicate)
        processing = process(store, paths, SyntheticFixtureExtractor(rows))
    if processing['failed']:
        raise ValueError(f'Synthetic ingestion failed: {processing}')
    answers = {patient: query_patient(load_patient(store, patient),
        QuerySpec(family='utilization', patient_id=patient), store.documents()) for patient in store.patient_ids()}
    return {'validation_scope': 'Hand-authored synthetic claims; no model accuracy or real-patient validation.',
            'processing': processing, 'answers': answers}
