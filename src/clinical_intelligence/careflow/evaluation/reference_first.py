"""Frozen-reference comparison; source disputes never overwrite original scores."""
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
import re

from ...claims_review.prepare import digest

CLASSES = {'MODEL_ERROR', 'REFERENCE_ERROR', 'EQUIVALENT', 'BOTH_WRONG', 'UNRESOLVED'}


def normalized(value):
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', value).strip()
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def compare(references, predictions, *, execution_status='SUCCESS'):
    if len({r['reference_id'] for r in references}) != len(references):
        raise ValueError('Duplicate reference identity')
    if len({p['fact_id'] for p in predictions}) != len(predictions):
        raise ValueError('Duplicate prediction identity')
    matches, missing, remaining = [], [], list(predictions)
    for ref in references:
        match = next((p for p in remaining if p.get('mechanically_valid') is True
                      and digest(normalized(p['semantic'])) == digest(normalized(ref['semantic']))), None)
        if match is None:
            missing.append(ref)
        else:
            remaining.remove(match)
            matches.append({'reference_id': ref['reference_id'], 'fact_id': match['fact_id'],
                            'semantic': deepcopy(ref['semantic']), 'route': 'REFERENCE_MATCH_NO_SOL_REVIEW'})
    disagreements = []
    reference_slots = Counter(r['semantic'].get('slot') for r in missing)
    prediction_slots = Counter(p['semantic'].get('slot') for p in remaining)
    for ref in missing:
        # Multiple facts in one slot need explicit source judgment. List order
        # cannot establish correspondence or become auxiliary scoring credit.
        slot = ref['semantic'].get('slot')
        unique = isinstance(slot, str) and bool(slot) and reference_slots[slot] == prediction_slots[slot] == 1
        item = next((p for p in remaining if p['semantic'].get('slot') == slot), None) if unique else None
        if item is not None:
            remaining.remove(item)
        pair = {'reference': deepcopy(ref), 'prediction': deepcopy(item),
                'kind': 'VALUE_OR_GROUNDING_MISMATCH' if item else 'MISSING_PREDICTION'}
        disagreements.append({'discrepancy_id': digest(pair), **pair})
    for item in remaining:
        pair = {'reference': None, 'prediction': deepcopy(item), 'kind': 'EXTRA_PREDICTION'}
        disagreements.append({'discrepancy_id': digest(pair), **pair})
    return {'schema_version': 'careflow-reference-comparison/2', 'matches': matches,
            'discrepancies': disagreements, 'reference_count': len(references), 'prediction_count': len(predictions),
            'execution_status': execution_status, 'original_reference_sha256': digest(references),
            'original_predictions_sha256': digest(predictions)}


def score_original(comparisons):
    tp = sum(len(c['matches']) for c in comparisons)
    references = sum(c['reference_count'] for c in comparisons)
    predictions = sum(c['prediction_count'] for c in comparisons)
    fp, fn = predictions - tp, references - tp
    return {'metric': 'original_frozen_reference_exact_structured_match',
            'documents': len(comparisons), 'failed_documents': sum(c['execution_status'] != 'SUCCESS' for c in comparisons),
            'reference_denominator': references, 'prediction_denominator': predictions,
            'true_positives': tp, 'false_positives': fp, 'false_negatives': fn,
            'precision': tp / predictions if predictions else 0.0,
            'recall': tp / references if references else 0.0,
            'f1': 2 * tp / (references + predictions) if references + predictions else 0.0,
            'independent_medical_accuracy': False}


def audit_discrepancies(comparison, *, source, rules, auditor):
    findings = []
    for difference in comparison['discrepancies']:
        payload = {'source': source, 'difference': deepcopy(difference), 'rules': deepcopy(rules),
                   'original_reference_sha256': comparison['original_reference_sha256'],
                   'original_predictions_sha256': comparison['original_predictions_sha256']}
        result = auditor(payload)
        if result.get('classification') not in CLASSES:
            raise ValueError('Unknown source/reference dispute classification')
        if result.get('reviewer_type') != 'advanced_ai' or not result.get('model') or not result.get('model_version'):
            raise ValueError('Source reviewer identity/model/version required')
        if not result.get('reason') or not result.get('error_mechanism'):
            raise ValueError('Reviewer reason and generalizable error mechanism required')
        evidence = result.get('evidence')
        if not evidence:
            raise ValueError('A source dispute requires exact source evidence')
        for ref in evidence:
            start, end = ref.get('start'), ref.get('end')
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source)
                    or source[start:end] != ref.get('quote')):
                raise ValueError('Reviewer source evidence does not match original Unicode slice')
        findings.append({**deepcopy(result), 'discrepancy_id': difference['discrepancy_id'],
                         'reviewed_at': datetime.now(timezone.utc).isoformat(),
                         'source_sha256': digest(source), 'comparison_sha256': digest(comparison),
                         'boundary': 'Source-checked silver opinion; original references and scores remain unchanged.'})
    return findings


def score_auxiliary(comparisons, findings):
    """Conservative source-reviewed credit, with the original denominators intact.

    Equivalence can recover an existing pair. Reference-error credit requires an
    existing prediction and reference for that same slot; no missing material is
    invented. BOTH_WRONG and UNRESOLVED earn no credit. This is explicitly an
    AI-reviewed auxiliary metric, never independent clinical accuracy.
    """
    original = score_original(comparisons)
    by_id = {(f['comparison_sha256'], f['discrepancy_id']): f for f in findings}
    extra_tp = 0
    for comparison in comparisons:
        for difference in comparison['discrepancies']:
            finding = by_id.get((digest(comparison), difference['discrepancy_id']))
            if (finding and difference['reference'] and difference['prediction']
                    and difference['prediction'].get('mechanically_valid') is True
                    and finding['classification'] in {'EQUIVALENT', 'REFERENCE_ERROR'}):
                extra_tp += 1
    tp = original['true_positives'] + extra_tp
    refs, preds = original['reference_denominator'], original['prediction_denominator']
    return {'metric': 'source_checked_silver_auxiliary_fixed_denominators',
            'reference_denominator': refs, 'prediction_denominator': preds, 'true_positives': tp,
            'precision': tp / preds if preds else 0.0, 'recall': tp / refs if refs else 0.0,
            'f1': 2 * tp / (refs + preds) if refs + preds else 0.0,
            'classification_counts': {kind: sum(f['classification'] == kind for f in findings) for kind in sorted(CLASSES)},
            'unreviewed_discrepancies': sum((digest(c), d['discrepancy_id']) not in by_id for c in comparisons for d in c['discrepancies']),
            'independent_medical_accuracy': False, 'original_scores': original}
