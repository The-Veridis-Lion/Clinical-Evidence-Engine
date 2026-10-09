"""Read-only reserved-constraint adapter; never imported by runtime extraction."""
import argparse
import json
from pathlib import Path
from clinical_intelligence.claims_review.contracts import CaseInput, ReviewPacket
from audit_claims_packet import audit

VERSION = 'claims-confirmation-evaluation/1'


def evaluate(case, packet, expected):
    targets = {r['criterion_id']: r['status'] for r in expected['criterion_expectations']}
    for identifier in (expected.get('scope_expectation') or {}).get('criteria_not_evaluated', []):
        targets[identifier] = 'NOT_EVALUATED'
    actual = {r.criterion_id: r.status for r in packet.criteria}
    checks = {'overall_status': packet.status == expected['overall_expectation']['status']}
    checks.update({k: actual[k] == v for k, v in targets.items()})
    for excluded in expected['source_handling_expectations']['exclude']:
        checks['exclude:' + excluded['source_id']] = not any(f.source_id == excluded['source_id'] for f in packet.facts)
    for identifier in expected['source_handling_expectations']['retain']:
        checks['retain:' + identifier] = any(f.source_id == identifier for f in packet.facts)
    for target in expected['source_handling_expectations']['event_groups']:
        group = next((g for g in packet.timeline if g['event_key'] == target['event_link_id']), None)
        checks['event:' + target['event_link_id']] = bool(group and
            set(target['member_source_ids']) <= set(group['source_ids']) and
            group['counted_as_tests'] == target['expected_event_count'] and
            group['dates'] == [target['resolved_event_date']])
    binding = audit(case, packet)
    checks['automated_packet_audit'] = binding['passed']
    return {'case_id': case.case_id, 'passed': all(checks.values()), 'checks': checks,
            'expected_states': targets, 'actual_states': actual,
            'criterion_matches': sum(actual[k] == v for k, v in targets.items()),
            'criterion_total': len(targets), 'actual_overall': packet.status,
            'false_supported': [k for k, v in targets.items() if v != 'SUPPORTED' and actual[k] == 'SUPPORTED'],
            'unnecessary_insufficient': [k for k, v in targets.items() if v == 'SUPPORTED' and actual[k] == 'INSUFFICIENT_EVIDENCE'],
            'fact_constraints': [{'constraint_id': c['constraint_id'], 'status': 'REQUIRES_SEPARATE_AI_ASSISTED_REVIEW'} for c in expected['fact_constraints']],
            'automated_audit': binding, 'usage': packet.execution['usage'],
            'note_sources': packet.execution['note_sources'], 'execution_failed': packet.execution['execution_failed']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--expected', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); results = []
    for identifier in [f'CONF-{i:03}' for i in range(1, 7)]:
        case = CaseInput.model_validate_json((a.inputs/(identifier+'.json')).read_bytes())
        packet = ReviewPacket.model_validate_json((a.predictions/(identifier+'.json')).read_bytes())
        expected = json.loads((a.expected/(identifier+'.expected.json')).read_text(encoding='utf-8'))
        results.append(evaluate(case, packet, expected))
    result = {'version': VERSION, 'expected_type': 'original AI-assisted synthetic constraints; not human clinical gold',
              'cases': results, 'cases_passed': sum(r['passed'] for r in results), 'cases_total': 6,
              'criterion_matches': sum(r['criterion_matches'] for r in results),
              'criterion_total': sum(r['criterion_total'] for r in results),
              'semantic_citation_precision': None, 'human_review_completed': False}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
    return int(result['cases_passed'] != 6)


if __name__ == '__main__':
    raise SystemExit(main())
