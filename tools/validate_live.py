"""Compare a real extraction database to synthetic facts; never calls a model."""
import argparse
import json
from clinical_intelligence.demo import corpus, SyntheticFixtureExtractor
from clinical_intelligence.domain import RegisteredDocument
from clinical_intelligence.reconcile import reconcile
from clinical_intelligence.pipeline import load_patient
from clinical_intelligence.storage import SQLiteStore


def compare(database):
    extractor = SyntheticFixtureExtractor()
    expected = {}
    for row in corpus():
        extraction = extractor.extract(RegisteredDocument(document_id=row['declared_id'],
            fingerprint=row['declared_id'], source_names=[row['name']], text=row['text']))
        expected.setdefault(row['patient']['patient_id'], []).append(extraction)
    differences = []
    def events(abstraction):
        return sorted([dict(encounter=e.encounter_ref, dates=[str(d) for d in e.date_options],
            minutes=e.minute_options, countable=e.countable, state=str(e.state)) for e in abstraction.events],
            key=lambda e: e['encounter'] or '')
    with SQLiteStore(database) as store:
        for patient, extractions in expected.items():
            wanted = events(reconcile(extractions))
            actual = events(load_patient(store, patient))
            if actual != wanted:
                differences.append(dict(patient=patient, expected=wanted, actual=actual))
    return dict(scope='Synthetic encounter semantics only; not real-patient validation.',
                passed=not differences, differences=differences)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    result = compare(parser.parse_args().database)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
