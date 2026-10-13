"""Deterministic documentation checks retain the existing five-state semantics."""
import json
from ..claims_review.contracts import Citation, CriterionResult
from ..claims_review.prepare import digest
from .evidence import prepare, available
from .rules import ruleset


def state(facts):
    values = {value for f in facts for value in f['effective_assertions'] if value is not None}
    if any(f['reconciliation_status'] in {'CONFLICTED', 'UNRESOLVED'} for f in facts) or len(values) > 1:
        return 'CONFLICTED'
    if values == {True}:
        return 'SUPPORTED'
    if values == {False}:
        return 'NOT_SUPPORTED'
    return 'INSUFFICIENT_EVIDENCE'


def evaluate(case, *, revision=1):
    rules, manifest = ruleset(case.request.ruleset_id, case.request.ruleset_version, case.request.request_type)
    facts, excluded, resolution = prepare(case)
    unresolved = []
    for requirement in sorted({f['requirement'] for f in facts}):
        relevant = [f for f in facts if f['requirement'] == requirement]
        if state(relevant) == 'CONFLICTED':
            unresolved.append({'requirement': requirement, 'fact_ids': [f['fact_id'] for f in relevant],
                               'reason': 'Source assertions or amendment authority remain in conflict.',
                               'resolution': 'unresolved'})
    checks, gaps = [], []
    for rule in rules:
        support = [f for f in facts if f['requirement'] == rule.requirement]
        trigger_facts = [f for f in facts if f['requirement'] == rule.trigger_requirement]
        trigger_state = state(trigger_facts) if rule.trigger_requirement else 'SUPPORTED'
        selected = support + trigger_facts
        trigger_value = True if not rule.trigger_requirement else (
            True if trigger_state == 'SUPPORTED' else False if trigger_state == 'NOT_SUPPORTED' else None)
        status = state(support)
        reason = {
            'SUPPORTED': 'Traceable assertions support the required document or fact.',
            'NOT_SUPPORTED': 'Explicit contrary evidence is documented; this is not an absence inference.',
            'INSUFFICIENT_EVIDENCE': 'Required material is missing, unknown, unavailable, or not grounded.',
            'CONFLICTED': 'Relevant assertions or amendment authority remain unresolved.',
        }[status]
        if rule.trigger_requirement:
            if trigger_state == 'CONFLICTED':
                status, reason = 'CONFLICTED', 'The requirement trigger has unresolved contradictory evidence.'
            elif trigger_value is False:
                status, reason = 'NOT_APPLICABLE', 'Source-linked explicit false trigger establishes inapplicability.'
            elif trigger_value is None:
                status, reason = 'INSUFFICIENT_EVIDENCE', 'Applicability is unknown; missing triggers cannot waive a requirement.'
        questions = []
        missing = []
        if status == 'INSUFFICIENT_EVIDENCE':
            wanted = rule.trigger_requirement if trigger_value is None else rule.requirement
            missing = [f'Obtain source-backed {wanted} for request {case.request.request_id}.']
            questions = [f'Which original document establishes {wanted}, and where is the exact supporting passage?']
        elif status == 'NOT_SUPPORTED':
            questions = [f'Is the explicit contrary assertion for {rule.requirement} still correct? Supply new evidence for any correction.']
        elif status == 'CONFLICTED':
            questions = [f'Which source explicitly corrects the disputed {rule.requirement} or its trigger, with scoped authority?']
        refs = {digest(c): Citation.model_validate_json(json.dumps(c))
                for f in selected for c in f['citations']}
        conflicts = ([{'fact_ids': [f['fact_id'] for f in selected],
                       'reason': reason, 'resolution': 'unresolved'}] if status == 'CONFLICTED' else [])
        criterion = CriterionResult(
            criterion_id=rule.rule_id, criterion_role='documentation_requirement', status=status,
            reason=reason, clinical_refs=list(refs.values()), policy_refs=[], gaps=missing,
            conflicts=conflicts, derivation={'trigger': trigger_value, 'trigger_status': trigger_state},
            evidence_complete=status in {'SUPPORTED', 'NOT_APPLICABLE'} and bool(refs),
        )
        result = {**criterion.model_dump(mode='json'), 'rule_id': rule.rule_id, 'rule_version': rule.version,
                  'requirement': rule.requirement, 'description': rule.description,
                  'trigger_condition': f'{rule.trigger_requirement} == true' if rule.trigger_requirement else 'always',
                  'fact_ids': [f['fact_id'] for f in selected], 'review_questions': questions}
        checks.append(result)
        if missing:
            gaps.append({'rule_id': rule.rule_id, 'requirement': rule.requirement, 'reason': reason, 'actions': missing})
    statuses = {c['status'] for c in checks}
    readiness = ('CONFLICTED' if unresolved or 'CONFLICTED' in statuses else 'NOT_SUPPORTED' if 'NOT_SUPPORTED' in statuses
                 else 'NEEDS_EVIDENCE' if 'INSUFFICIENT_EVIDENCE' in statuses else 'DOCUMENTATION_READY')
    risk_reasons = [f"{c['rule_id']}:{c['status']}" for c in checks if c['status'] in {'CONFLICTED', 'NOT_SUPPORTED'}]
    risk_reasons += [f"unresolved_assertions:{c['requirement']}" for c in unresolved]
    if any(f.amends_fact_id for f in case.facts):
        risk_reasons.append('fact_correction_present')
    if any(f['reason'] == 'ungrounded_citation' for f in excluded):
        risk_reasons.append('citation_grounding_failed')
    packet = {
        'schema_version': 'careflow-review-packet/1', 'case_id': case.case_id, 'revision': revision,
        'request': case.request.model_dump(mode='json'), 'review_as_of': case.review_as_of.isoformat(),
        'readiness': readiness, 'ruleset': manifest, 'checks': checks, 'facts': facts,
        'sources': [s.model_dump(mode='json') for s in case.sources], 'excluded_facts': excluded,
        'source_screening': [{'source_id': s.source_id,
                              'availability_scope_issue': available(s.model_dump(mode='json'), case),
                              'referenced_by_fact_ids': [f['fact_id'] for f in facts
                                                        if s.source_id in {c['source_id'] for c in f['citations']}]}
                             for s in case.sources],
        'source_relationships': resolution,
        'gaps': gaps, 'unresolved_conflicts': unresolved,
        'review_route': {'recommended': bool(risk_reasons), 'reasons': risk_reasons,
                         'reviewer_types': ['human', 'advanced_ai'], 'mandatory': False},
        'input_sha256': digest(case.model_dump(mode='json')),
        'execution': {'research_model_calls': 0, 'product_model_calls': 0,
                      'note_extraction': 'supplied_assertions_only', 'deterministic_rules': True},
        'decision_boundary': manifest['boundary'],
        'interpretation_limit': 'Exact provenance validates location, not clinical interpretation or signature authenticity. '
                                'Supplied assertions require independent human or advanced-AI review when warranted.',
    }
    return {**packet, 'packet_sha256': digest(packet)}
