"""Source-independent, lossless native reference units, never fabricated gold.

This deliberately does not normalize clinical semantics or repair malformed JSON.
Full clinical recall is unavailable where the original reference denominator is
unknown. Original fields and note spans remain independently inspectable.
"""
import json
from pathlib import Path

from ...clinical_notes.dataset import sha
from ...dialogue_first.dataset import Document, source_index
from .corpus import canonical, write_once
from .public import SEMANTIC_FIELDS, source_audit_batches, public_metrics

VERSION = 'careflow-native-reference-units/1'
PLACEHOLDERS = {'', 'none', 'null', 'unknown', 'not documented'}


def native_units(record):
    references, nonassertions = [], []
    def add(value, locator, context):
        identifier = 'R-' + sha(record['document_id'] + ':' + locator)[:24]
        item = {'reference_id': identifier, 'semantic': {'slot': 'native_reference_unit',
                'category': 'native_reference', 'value': value, 'locator': locator},
                'original_label_evidence': {'locator': locator, 'raw_value': value}, 'context': context}
        if value is None or (isinstance(value, str) and value.strip().casefold() in PLACEHOLDERS):
            nonassertions.append(item)
        else:
            references.append(item)
    if record['dataset'] == 'ACI-BENCH':
        text = record['reference']['original_note']
        document = Document('REFERENCE-' + sha(text), record['case_group'], 'original_reference',
                            text, sha(text), sha(text), 0, input_kind='note')
        for span in source_index(document)['source_catalogue']:
            add(span['quote'], f"unicode:{span['start']}:{span['end']}", {'original_span': span})
        failure = False
    else:
        summary = record['reference']['original_summary']
        failure = bool(record['reference']['reference_error'])
        def visit(value, pointer='', context=None):
            if isinstance(value, dict):
                for key, item in value.items():
                    visit(item, pointer + '/' + key.replace('~', '~0').replace('/', '~1'), value)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    visit(item, pointer + '/' + str(i), item)
            else:
                add(value, pointer, context)
        if not failure:
            visit(summary)
    return {'version': VERSION, 'reference_origin': 'original native field values/note spans; no AI repair or clinical gold',
            'facts': references, 'nonassertions': nonassertions,
            'status': 'REFERENCE_FAILED' if failure else 'NATIVE_REFERENCE_UNITS',
            'complete_clinical_gold': False}


def freeze_native(records, output):
    root = Path(output)
    results = {r['document_id']: native_units(r) for r in records}
    freeze = {'version': VERSION, 'document_ids': list(results),
              'original_reference_hashes': {r['document_id']: sha(canonical(r['reference'])) for r in records},
              'unit_hashes': {key: sha(canonical(value)) for key, value in results.items()},
              'placeholder_values': sorted(PLACEHOLDERS),
              'policy': 'Lossless native units; no candidate input; original malformed labels remain failures; '
                        'no complete clinical accuracy or full-cohort recall from unavailable denominators.'}
    write_once(root/'freeze.json', (canonical(freeze)+'\n').encode('utf-8'))
    for key, value in results.items():
        write_once(root/'units'/(sha(key)+'.json'), (canonical(value)+'\n').encode('utf-8'))
    return results


def native_comparison(record, prediction, reference):
    from .batch import validate_source_result
    from ..clinical_context import prepared_context
    original_ids = [f['context_fact_id'] for context in prepared_context(validate_source_result(record, prediction['extraction']))
                    for f in context['facts']] if prediction else []
    refs = reference['facts']
    preds = [{'fact_id': 'F-' + sha(record['document_id'])[:16] + '-' + str(i),
              'original_clinical_fact_id': original_ids[i],
              'semantic': {key: fact.get(key) for key in SEMANTIC_FIELDS},
              'attribution_confidence': fact.get('attribution_confidence'),
              'mechanically_valid': True, 'evidence': [fact['evidence'], *fact.get('supporting_evidence', [])]}
             for i, fact in enumerate(prediction['extraction']['facts'])] if prediction else []
    # Native fields/whole note spans cannot certify every ClinicalFact qualifier.
    # Hence there are no invented whole-assertion exact matches. A source reviewer
    # checks extra dimensions and all predictions, as the reference-first contract
    # requires for annotations absent from the original reference schema.
    comparison = {'schema_version': VERSION, 'matches': [], 'reference_count': len(refs),
                  'prediction_count': len(preds), 'execution_status': 'SUCCESS' if prediction else 'EXTRACTION_FAILED',
                  'reference_failure': reference['status']=='REFERENCE_FAILED',
                  'reference_origin': reference['reference_origin'], 'source_sha256': sha(record['text']),
                  'original_reference_sha256': sha(canonical(record['reference'])),
                  'original_predictions_sha256': sha(canonical(preds)),
                  'raw_clinical_exact_score_status': 'UNAVAILABLE_NATIVE_REFERENCE_SCHEMA_DIFFERS',
                  'scope': 'All predicted assertions; native reference field/span coverage, not complete clinical recall.'}
    return comparison, refs, preds


def evaluate_native(records, prediction_root, reference_root, output, ledger_path, *, provider=None, batch_size=20):
    from .batch import validate_source_result
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((Path(reference_root)/'freeze.json').read_text(encoding='utf-8'))
    if frozen['document_ids'] != [r['document_id'] for r in records]:
        raise ValueError('Native reference document cohort changed')
    items = []
    for record in records:
        key = record['document_id']
        if sha(canonical(record['reference'])) != frozen['original_reference_hashes'][key]:
            raise ValueError('Original reference changed')
        reference = json.loads((Path(reference_root)/'units'/(sha(key)+'.json')).read_text(encoding='utf-8'))
        if sha(canonical(reference)) != frozen['unit_hashes'][key]:
            raise ValueError('Native reference units changed')
        path = Path(prediction_root)/'results'/(sha(key)+'.json')
        prediction = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if prediction:
            validate_source_result(record, prediction['extraction'])
        comparison, refs, preds = native_comparison(record, prediction, reference)
        write_once(root/'comparisons'/(sha(key)+'.json'), (canonical(comparison)+'\n').encode('utf-8'))
        items.append((record, comparison, refs, preds))
    write_once(root/'original-reference-availability.json', (canonical({
        'status': 'No complete universal-schema clinical gold in original datasets',
        'document_denominator': len(records),
        'malformed_reference_documents': sum(c['reference_failure'] for _, c, _, _ in items),
        'known_native_reference_units': sum(len(refs) for _, _, refs, _ in items),
        'original_precision': None, 'original_recall': None, 'original_f1': None,
        'boundary': 'Native reference field/span coverage is an auxiliary diagnostic, not full clinical accuracy.'})+'\n').encode('utf-8'))
    findings, failures = source_audit_batches(items, root/'source-review', ledger_path,
                                             provider=provider, compact=True, batch_size=batch_size)
    results = {}
    for dataset in sorted({r['dataset'] for r in records}):
        selected = [item for item in items if item[0]['dataset']==dataset]
        identifiers = {item[0]['document_id'] for item in selected}
        results[dataset] = public_metrics(selected, [f for f in findings if f['document_id'] in identifiers],
                                         [f for f in failures if identifiers.intersection(f['document_ids'])])
        results[dataset]['reference_origin'] = 'Original native field values/note spans; not AI-transcribed or corrected gold'
        results[dataset]['scope'] = 'Source support of all predicted assertions; native reference field/span coverage only. Not independent medical accuracy or complete clinical recall.'
    write_once(root/'metrics.json', (canonical(results)+'\n').encode('utf-8'))
    return results


if __name__ == '__main__':
    import argparse
    from .batch import development_records
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['freeze', 'review'])
    parser.add_argument('--aci', required=True)
    parser.add_argument('--acn', required=True)
    parser.add_argument('--references', required=True)
    parser.add_argument('--predictions')
    parser.add_argument('--output')
    parser.add_argument('--ledger')
    parser.add_argument('--batch-size', type=int, default=20)
    args = parser.parse_args()
    records = development_records(args.aci, args.acn)
    if args.phase == 'freeze':
        result = freeze_native(records, args.references)
        print(canonical({'documents': len(result), 'known_units': sum(len(v['facts']) for v in result.values()),
                         'malformed_reference_documents': sum(v['status']=='REFERENCE_FAILED' for v in result.values())}))
    else:
        if not all([args.predictions, args.output, args.ledger]):
            parser.error('review requires --predictions, --output and --ledger')
        print(canonical(evaluate_native(records, args.predictions, args.references, args.output, args.ledger,
                                       batch_size=args.batch_size)))
