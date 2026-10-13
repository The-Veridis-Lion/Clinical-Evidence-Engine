"""A frozen acceptance evaluator must count failures and reject false Ready."""
from copy import deepcopy
import json

import pytest

from clinical_intelligence.careflow.demo import referral_case, supplemental
from clinical_intelligence.careflow.engine import evaluate
from clinical_intelligence.careflow.contracts import Case
from clinical_intelligence.careflow.evaluation.acceptance import freeze_materials, evaluate_materials, seal_candidate, verify_packet


def scenarios():
    values = []
    for i, state in enumerate(['SUPPORTED', 'NOT_SUPPORTED', 'INSUFFICIENT_EVIDENCE', 'CONFLICTED', 'NOT_APPLICABLE']):
        raw = referral_case(patient=f'ACCEPT-PAT-{i}', request=f'ACCEPT-REQ-{i}', case_id=f'ACCEPT-CASE-{i}')
        # Fixed oracle refers only to the designated summary or conditional rule;
        # all other expected outcomes are declared before candidate evaluation.
        target = 'clinical_summary' if state != 'NOT_APPLICABLE' else 'investigation_result'
        assertions = {'SUPPORTED': [True], 'NOT_SUPPORTED': [False], 'INSUFFICIENT_EVIDENCE': [],
                      'CONFLICTED': [True, False], 'NOT_APPLICABLE': []}[state]
        for index, assertion in enumerate(assertions):
            extra = supplemental(target, assertion, f'Independent source {i}/{index}.', patient=f'ACCEPT-PAT-{i}', request=f'ACCEPT-REQ-{i}')
            raw['sources'] += extra['sources']
            raw['facts'] += extra['facts']
        expected = {'CF-DOC-001': 'SUPPORTED', 'CF-DOC-002': 'SUPPORTED',
                    'CF-DOC-003': state if target == 'clinical_summary' else 'INSUFFICIENT_EVIDENCE',
                    'CF-DOC-004': 'NOT_APPLICABLE', 'CF-DOC-005': 'NOT_APPLICABLE', 'CF-REF-001': 'SUPPORTED'}
        overall = {'SUPPORTED': 'DOCUMENTATION_READY', 'NOT_SUPPORTED': 'NOT_SUPPORTED',
                   'CONFLICTED': 'CONFLICTED'}.get(state, 'NEEDS_EVIDENCE')
        values.append({'scenario_id': f'ORACLE-{i}', 'partition': 'development', 'case': raw,
                       'expected_checks': expected, 'expected_readiness': overall})
    return values


def test_frozen_acceptance_counts_all_states_and_mechanical_refs(tmp_path):
    root = tmp_path / 'frozen'
    manifest = freeze_materials(scenarios(), root)
    result = evaluate_materials(root, tmp_path / 'result', partition='development')
    assert result['criteria_macro_f1'] == 1.0
    assert result['serious_false_ready'] == 0
    assert result['source_reference_validation_rate'] == result['rule_reference_validation_rate'] == 1.0
    assert result['case_count'] == 5 and result['criterion_denominator'] == 30
    assert result['meets_deterministic_targets'] is True
    assert result['manifest_sha256'] == manifest['manifest_sha256']
    assert freeze_materials(scenarios(), root) == manifest
    changed = scenarios()
    changed[0]['expected_readiness'] = 'NEEDS_EVIDENCE'
    with pytest.raises(ValueError, match='Frozen'):
        freeze_materials(changed, root)


def test_exceptions_stay_in_denominator_and_false_ready_is_fatal(tmp_path):
    root = tmp_path / 'frozen'
    freeze_materials(scenarios(), root)
    def bad(case, **kwargs):
        if case.request.patient_id.endswith('0'):
            raise RuntimeError('Injected extraction/engine failure')
        packet = evaluate(case, **kwargs)
        packet['readiness'] = 'DOCUMENTATION_READY'
        return packet
    result = evaluate_materials(root, tmp_path / 'bad-result', partition='development', evaluator=bad)
    assert result['case_count'] == 5 and result['criterion_denominator'] == 30
    assert result['failed_cases'] == 1 and result['serious_false_ready'] >= 1
    assert result['criteria_macro_f1'] < 1 and not result['meets_deterministic_targets']


def test_packet_mechanical_verification_rejects_changed_quote_and_version():
    packet = evaluate(Case.model_validate_json(json.dumps(referral_case())))
    assert all(verify_packet(packet)['source_checks'])
    changed = deepcopy(packet)
    changed['facts'][0]['citations'][0]['quote'] = 'invented'
    changed['checks'][0]['rule_version'] = 'untracked-version'
    result = verify_packet(changed)
    assert not all(result['source_checks']) and not all(result['rule_checks'])


def test_holdout_is_reserved_only_after_candidate_seal_and_cannot_be_rerun(tmp_path):
    data = scenarios()
    for row in data:
        row['partition'] = 'holdout'
    root = tmp_path / 'frozen'
    freeze_materials(data, root)
    with pytest.raises(ValueError, match='candidate'):
        evaluate_materials(root, tmp_path / 'not-ready', partition='holdout')
    seal_candidate(root)
    final = evaluate_materials(root, tmp_path / 'final', partition='holdout')
    assert final['meets_deterministic_targets']
    with pytest.raises(ValueError, match='reserved'):
        evaluate_materials(root, tmp_path / 'repeat', partition='holdout')


def test_global_conflict_false_ready_counts_even_when_item_is_inapplicable(tmp_path):
    rows = scenarios()[:1]
    rows[0]['expected_readiness'] = 'CONFLICTED'
    # Here all rule expectations are supported/inapplicable; the expected global
    # conflict must still count as severe rather than disappearing in scoring.
    freeze_materials(rows, tmp_path / 'frozen')
    report = evaluate_materials(tmp_path / 'frozen', tmp_path / 'output', partition='development')
    assert report['serious_false_ready'] == 1
    assert not report['meets_deterministic_targets']
