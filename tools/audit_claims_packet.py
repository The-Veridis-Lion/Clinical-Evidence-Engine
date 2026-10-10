"""Position, identity and policy checks; explicitly not semantic citation scoring."""
import argparse
import json
from pathlib import Path
from clinical_intelligence.claims_review.contracts import CaseInput, ReviewPacket
from clinical_intelligence.claims_review.prepare import digest
from clinical_intelligence.claims_review.facts import source_key
from clinical_intelligence.claims_review.review import load_policy

VERSION = 'claims-packet-audit/1'


def audit(case, packet):
    sources = {s.source_id: s for s in case.sources}
    raw = case.model_dump(mode='json')
    refs = [c for f in packet.facts for c in f.citations]
    refs += [c for r in packet.criteria for c in r.clinical_refs]
    failures = []
    for index, ref in enumerate(refs):
        source = sources.get(ref.source_id)
        valid = source is not None and ref.patient_id == case.claim.patient_id
        if valid:
            valid = (source.patient_id == ref.patient_id and source.available_at is not None
                     and source.available_at <= case.review_context.as_of
                     and ref.source_sha256 == source_key(source.model_dump(mode='json')))
        if valid and ref.method == 'unicode_line_anchor':
            valid = (isinstance(source.content, str) and ref.start is not None and ref.end is not None
                     and 0 <= ref.start < ref.end <= len(source.content)
                     and source.content[ref.start:ref.end] == ref.quote)
        elif valid:
            try:
                tokens = [t.replace('~1', '/').replace('~0', '~') for t in ref.locator.lstrip('/').split('/')]
                # Equal values in another source cannot establish this binding.
                valid = tokens[0] == 'sources' and raw['sources'][int(tokens[1])]['source_id'] == ref.source_id
                node = raw
                for token in tokens:
                    node = node[int(token)] if isinstance(node, list) else node[token]
                valid &= node == ref.raw_value
            except (KeyError, ValueError, IndexError, TypeError):
                valid = False
        if not valid:
            failures.append({'citation_index': index, 'source_id': ref.source_id,
                             'locator': ref.locator, 'reason': 'position_identity_or_availability'})
    policy = load_policy()
    versions = {s['source_id']: (s.get('source_version') or s.get('publication_month') or s['publication_date'],
                               s['official_url']) for s in policy['sources']}
    allowed = {r['criterion_id']: {(ref['source_id'], *versions[ref['source_id']], ref['locator'])
                                  for ref in r['source_refs']} for r in policy['criteria']}
    policy_valid = all(r.policy_refs and all((p.source_id, p.source_version, p.official_url, p.locator)
                                            in allowed.get(r.criterion_id, set()) for p in r.policy_refs)
                       for r in packet.criteria)
    checks = {
        'input_identity': packet.identity['input_sha256'] == digest(raw),
        'target_identity': packet.target == case.claim,
        'fact_patient_source_binding': all(f.patient_id == case.claim.patient_id and f.source_id in sources
                                          and sources[f.source_id].patient_id == f.patient_id for f in packet.facts),
        'exact_citation_positions_and_binding': not failures,
        'registry_policy_locators': policy_valid,
        'supported_has_evidence': all(r.clinical_refs and r.evidence_complete
                                     for r in packet.criteria if r.status == 'SUPPORTED'),
        'no_execution_failure': not packet.execution['execution_failed'],
    }
    return {'version': VERSION, 'case_id': case.case_id, 'checks': checks,
            'passed': all(checks.values()), 'citation_occurrences': len(refs),
            'citation_position_failures': failures, 'semantic_citation_precision': None,
            'semantic_metric_status': 'UNAVAILABLE: positions and registry membership do not certify meaning.',
            'fact_coverage_precision_recall': None, 'independent_semantic_labels': False,
            'human_review_completed': False, 'actual_provider_calls': packet.execution['actual_provider_calls']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    inputs = p.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--case', type=Path)
    inputs.add_argument('--retrieval', type=Path)
    p.add_argument('--packet', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    body = json.loads((a.case or a.retrieval).read_text(encoding='utf-8'))
    case = CaseInput.model_validate_json(json.dumps(body if a.case else body['case']))
    packet = ReviewPacket.model_validate_json(a.packet.read_text(encoding='utf-8'))
    result = audit(case, packet)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
