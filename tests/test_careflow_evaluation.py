"""Frozen grouping and reference-first evaluation safeguards, not model scores."""
import json

import pytest

from clinical_intelligence.careflow.evaluation.corpus import freeze_corpus, load_frozen, load_acn
from clinical_intelligence.careflow.evaluation.reference_first import compare, score_original, audit_discrepancies


def documents():
    result = []
    for patient in range(6):
        for kind in ('note', 'dialogue'):
            result.append({'document_id': f'P{patient}:{kind}', 'case_group': f'P{patient}',
                           'dataset': 'fixture', 'input_kind': kind, 'text': f'{kind} source for patient {patient}',
                           'reference': {'labels': [{'reference_id': 'symptom', 'semantic': {'slot': 'symptom', 'value': 'pain'}}]},
                           'reference_origin': 'test_reference'})
    return result


def test_group_partition_keeps_variants_and_duplicate_content_together(tmp_path):
    docs = documents()
    docs[2]['text'] = docs[0]['text']
    manifest = freeze_corpus(docs, tmp_path / 'corpus', development_groups=2, holdout_groups=2,
                             exposed_groups={'P0'}, source_metadata={'revision': 'fixture'})
    dev = {g['group_id'] for g in manifest['partitions']['development']}
    hold = {g['group_id'] for g in manifest['partitions']['holdout']}
    assert not dev & hold
    groups = manifest['partitions']['development'] + manifest['partitions']['holdout'] + manifest['partitions']['reserve']
    combined = next(g for g in groups if 'P0' in g['original_case_groups'])
    assert 'P1' in combined['original_case_groups'] and combined['group_id'] in dev
    loaded = load_frozen(tmp_path / 'corpus', 'development')
    assert {'P0:note', 'P0:dialogue', 'P1:note', 'P1:dialogue'} <= {d['document_id'] for d in loaded}
    assert freeze_corpus(docs, tmp_path / 'corpus', development_groups=2, holdout_groups=2,
                         exposed_groups={'P0'}, source_metadata={'revision': 'fixture'}) == manifest
    docs[0]['reference']['labels'][0]['semantic']['value'] = 'altered'
    with pytest.raises(ValueError, match='Frozen'):
        freeze_corpus(docs, tmp_path / 'corpus', development_groups=2, holdout_groups=2,
                      exposed_groups={'P0'}, source_metadata={'revision': 'fixture'})


def test_frozen_content_tampering_is_detected_and_holdout_requires_candidate_freeze(tmp_path):
    freeze_corpus(documents(), tmp_path / 'corpus', development_groups=2, holdout_groups=2, source_metadata={})
    with pytest.raises(ValueError, match='candidate freeze'):
        load_frozen(tmp_path / 'corpus', 'holdout')
    data = load_frozen(tmp_path / 'corpus', 'holdout', candidate_sha256='frozen-candidate')
    assert data
    path = tmp_path / 'corpus' / 'documents.jsonl'
    path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        load_frozen(tmp_path / 'corpus', 'development')


def test_acn_loading_retains_case_triplets_and_separate_generated_reference(tmp_path):
    raw = [{'idx': i, 'note': f'Original note {i}', 'full_note': f'Full original note {i}',
            'conversation': f'Doctor: conversation {i}', 'summary': json.dumps({'symptoms': [{'name': 'pain'}]})}
           for i in range(3)]
    path = tmp_path / 'acn.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in raw) + '\n', encoding='utf-8')
    docs = load_acn(path)
    assert len(docs) == 9
    assert all(d['reference_origin'] == 'dataset_generated_silver' for d in docs)
    assert all('summary' not in d['text'] for d in docs)
    assert {d['case_group'] for d in docs} == {'acn:0', 'acn:1', 'acn:2'}


def reference():
    return [{'reference_id': 'R1', 'semantic': {'slot': 'symptom', 'value': 'pain'}},
            {'reference_id': 'R2', 'semantic': {'slot': 'diagnosis', 'value': 'arthritis'}}]


def fact(identifier, value, slot='symptom', valid=True):
    return {'fact_id': identifier, 'semantic': {'slot': slot, 'value': value},
            'mechanically_valid': valid, 'evidence': [{'start': 0, 'end': 4, 'quote': 'pain'}]}


def test_reference_matches_do_not_call_reviewer_and_missing_facts_remain_in_denominator():
    diff = compare(reference(), [fact('F1', 'pain'), fact('F2', 'arthritis', 'diagnosis')])
    assert len(diff['matches']) == 2 and not diff['discrepancies']
    def forbidden(_):
        raise AssertionError('Already matched material must not be re-reviewed')
    assert audit_discrepancies(diff, source='pain', rules=[], auditor=forbidden) == []
    missing = compare(reference(), [])
    metrics = score_original([diff, missing])
    assert metrics['reference_denominator'] == 4 and metrics['true_positives'] == 2
    assert metrics['false_negatives'] == 2 and metrics['recall'] == 0.5


@pytest.mark.parametrize('classification', ['MODEL_ERROR', 'REFERENCE_ERROR', 'EQUIVALENT', 'BOTH_WRONG', 'UNRESOLVED'])
def test_discrepancy_review_is_separate_and_requires_source_grounding(classification):
    diff = compare(reference(), [fact('F1', 'pain'), fact('F2', 'wrong')])
    calls = []
    def reviewer(payload):
        calls.append(payload)
        return {'classification': classification, 'reviewer_type': 'advanced_ai', 'model': 'gpt-6.1-sol',
                'model_version': 'test', 'reason': 'Compare exact source and frozen labels.',
                'evidence': [{'start': 0, 'end': 4, 'quote': 'pain'}], 'error_mechanism': 'source_role_mismatch'}
    before = json.dumps(diff, sort_keys=True)
    findings = audit_discrepancies(diff, source='pain and clinical history', rules=[{'rule_id': 'versioned-rule'}], auditor=reviewer)
    assert len(calls) == len(diff['discrepancies']) == len(findings)
    assert all(f['classification'] == classification for f in findings)
    assert json.dumps(diff, sort_keys=True) == before
    assert all(p['source'] == 'pain and clinical history' for p in calls)


def test_invalid_grounding_cannot_pass_reference_match():
    diff = compare(reference(), [fact('F1', 'pain', valid=False)])
    assert not diff['matches'] and diff['discrepancies']
    metrics = score_original([diff])
    assert metrics['true_positives'] == 0 and metrics['false_negatives'] == 2
    def bad(_):
        return {'classification': 'EQUIVALENT', 'reviewer_type': 'advanced_ai', 'model': 'gpt-6.1-sol',
                'model_version': 'test', 'reason': 'Uncited opinion', 'evidence': [], 'error_mechanism': 'none'}
    with pytest.raises(ValueError, match='source evidence'):
        audit_discrepancies(diff, source='pain', rules=[], auditor=bad)


@pytest.mark.parametrize('reference_value,predicted_value', [
    ({'slot': 'test_result', 'value': 7.1, 'unit': 'mM'}, {'slot': 'test_result', 'value': 7.1, 'unit': 'mm'}),
    ({'slot': 'test_result', 'value': 1}, {'slot': 'test_result', 'value': True}),
])
def test_reference_first_does_not_equate_case_sensitive_units_or_bool_numbers(reference_value, predicted_value):
    diff = compare([{'reference_id': 'STRICT-REFERENCE', 'semantic': reference_value}],
                   [{'fact_id': 'STRICT-FACT', 'semantic': predicted_value, 'mechanically_valid': True, 'evidence': []}])
    assert not diff['matches'] and diff['discrepancies']


def test_multiple_unmatched_facts_are_not_paired_by_list_order():
    refs = [{'reference_id': 'R-COUGH', 'semantic': {'slot': 'symptom', 'value': 'cough'}},
            {'reference_id': 'R-PAIN', 'semantic': {'slot': 'symptom', 'value': 'pain'}}]
    predictions = [fact('F-ONE', 'different cough description'), fact('F-TWO', 'different pain description')]
    for ordered in (predictions, list(reversed(predictions))):
        diff = compare(refs, ordered)
        assert not diff['matches']
        assert all(d['reference'] is None or d['prediction'] is None for d in diff['discrepancies'])
        assert score_original([diff])['reference_denominator'] == 2


def test_auxiliary_findings_cannot_be_reused_with_a_changed_comparison():
    from clinical_intelligence.careflow.evaluation.reference_first import score_auxiliary
    diff = compare([reference()[0]], [fact('F-ONE', 'ache')])
    def reviewer(_):
        return {'classification': 'EQUIVALENT', 'reviewer_type': 'advanced_ai', 'model': 'offline-fixture',
                'model_version': '1', 'reason': 'Fixture semantic equivalence opinion.',
                'evidence': [{'start': 0, 'end': 4, 'quote': 'pain'}], 'error_mechanism': 'terminology'}
    findings = audit_discrepancies(diff, source='pain', rules=[], auditor=reviewer)
    assert score_auxiliary([diff], findings)['true_positives'] == 1
    changed = {**diff, 'execution_status': 'DIFFERENT_SNAPSHOT'}
    assert score_auxiliary([changed], findings)['true_positives'] == 0
