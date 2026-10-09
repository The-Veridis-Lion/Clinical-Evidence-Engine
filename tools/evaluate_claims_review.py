"""Development conformance evaluator. Expected files never enter runtime extraction."""
import argparse
import json
from pathlib import Path
from clinical_intelligence.claims_review.contracts import CaseInput, ReviewPacket


def evaluate(case, packet, expected):
    checks = []
    def check(name, passed):
        checks.append({'check': name, 'passed': bool(passed)})
    check('overall_state', packet.status == expected['overall_expectation']['status'])
    actual = {r.criterion_id: r for r in packet.criteria}
    targets = {r['criterion_id']: r['status'] for r in expected['criterion_expectations']}
    if packet.status == 'UNSUPPORTED_SCOPE':
        targets = {k: 'NOT_EVALUATED' for k in actual}
    for identifier, target in targets.items():
        check(identifier, actual[identifier].status == target)
    sources = {s.source_id: s for s in case.sources}
    refs = [c for f in packet.facts for c in f.citations] + [c for r in packet.criteria for c in r.clinical_refs]
    binding_ok = True
    for ref in refs:
        s = sources.get(ref.source_id)
        if s is None or ref.patient_id != case.claim.patient_id or s.patient_id != ref.patient_id or s.available_at is None or s.available_at > case.review_context.as_of:
            binding_ok = False
            continue
        if ref.method == 'unicode_line_anchor':
            binding_ok &= isinstance(s.content, str) and ref.start is not None and ref.end is not None and s.content[ref.start:ref.end] == ref.quote
        else:
            node = case.model_dump(mode='json')
            try:
                for token in ref.locator.lstrip('/').split('/'):
                    token = token.replace('~1', '/').replace('~0', '~')
                    node = node[int(token)] if isinstance(node, list) else node[token]
                binding_ok &= node == ref.raw_value
            except (KeyError, ValueError, IndexError, TypeError):
                binding_ok = False
    check('citation_position_and_source_binding', binding_ok)
    check('policy_refs_and_supported_evidence', all(r.policy_refs and (not r.evidence_complete or bool(r.clinical_refs)) for r in packet.criteria))
    check('no_execution_failure', not packet.execution['execution_failed'])
    for excluded in expected['source_handling_expectations']['exclude']:
        check('excluded_source:' + excluded['source_id'], not any(f.source_id == excluded['source_id'] for f in packet.facts))
    for group in expected['source_handling_expectations']['event_groups']:
        g = next((g for g in packet.timeline if g['event_key'] == group['event_link_id']), None)
        check('explicit_event:' + group['event_link_id'], g is not None and g['identity_explicit'] and
              set(group['member_source_ids']) <= set(g['source_ids']) and g['conflicted'] == group['conflicting_event_dates'])
    # These are the original development constraints, not production answers.
    if case.case_id == 'DEV-002':
        planned = [f for f in packet.facts if f.source_id == 'DEV-002-S003' and f.kind == 'regimen_change']
        actual_change = [f for f in packet.facts if f.source_id == 'DEV-002-S004' and f.kind == 'regimen_change' and f.value is True and f.temporal_status == 'actual' and str(f.fact_date) == '2026-08-10']
        check('order_is_not_implemented_change', bool(planned) and all(f.value is None and f.temporal_status == 'planned' for f in planned))
        check('necessary_note_start_fact', bool(actual_change))
    if case.case_id == 'DEV-003':
        for sid, value, day in [('DEV-003-S002', 7.1, '2026-09-25'), ('DEV-003-S003', 6.9, None)]:
            check('partial_fact:' + sid, any(f.source_id == sid and f.kind == 'test_event' and f.value == value and (f.fact_date.isoformat() if f.fact_date else None) == day for f in packet.facts))
        check('missing_order_not_cancellation', not any(f.kind == 'order_intent' and f.value is False for f in packet.facts))
    if case.case_id == 'DEV-004':
        check('conflict_dates_not_latest_wins', any(g['dates'] == ['2026-05-20', '2026-08-20'] and g['conflicted'] for g in packet.timeline))
    if case.case_id == 'DEV-005':
        check('screening_not_diabetes_invention', not any(f.kind == 'diabetes_context' and f.value is True for f in packet.facts))
    check('no_billing_code_invention', packet.target.procedure_code is None and packet.target.code_system is None)
    false_support = [k for k, target in targets.items() if target != 'SUPPORTED' and actual[k].status == 'SUPPORTED']
    abstentions = [k for k, target in targets.items() if target == 'SUPPORTED' and actual[k].status == 'INSUFFICIENT_EVIDENCE']
    return {'case_id': case.case_id, 'passed': all(c['passed'] for c in checks), 'checks': checks,
            'criterion_states': {k: r.status for k, r in actual.items()},
            'unsupported_support': false_support, 'unnecessary_criterion_abstention': abstentions,
            'actual_provider_calls': packet.execution['actual_provider_calls'],
            'note_calls': packet.execution['note_sources'], 'usage': packet.execution['usage'],
            'semantic_quote_review': 'Requires separate AI-assisted source review; exact positions do not certify meaning.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--cases', type=Path, default=Path('examples/claims_review/development'))
    parser.add_argument('--expected', type=Path, default=Path('tests/fixtures/claims_review/development_expected.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    expectations = json.loads(args.expected.read_text(encoding='utf-8'))['cases']
    results = []
    for expected in expectations:
        identifier = expected['case_id']
        case = CaseInput.model_validate_json((args.cases / (identifier + '.json')).read_text(encoding='utf-8'))
        packet = ReviewPacket.model_validate_json((args.results / (identifier + '.json')).read_text(encoding='utf-8'))
        results.append(evaluate(case, packet, expected))
    summary = {'evaluator_version': 'claims-review-development/1', 'test_type': 'development_conformance_not_clinical_accuracy',
               'human_reviewed': False, 'cases_passed': sum(r['passed'] for r in results),
               'cases_total': len(results), 'cases': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(f"{summary['cases_passed']}/{len(results)} development packets passed")
    return int(summary['cases_passed'] != len(results))


if __name__ == '__main__':
    raise SystemExit(main())
