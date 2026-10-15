"""Deterministic documentation checks retain the existing five-state semantics."""
import json
import hashlib
from pathlib import Path
from ..claims_review.contracts import Citation, CriterionResult
from ..claims_review.prepare import digest
from .evidence import prepare, available
from .rules import ruleset, documentation_decision

_LOADED_IMPLEMENTATION_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def state(facts):
    values = {value for f in facts for value in f['effective_assertions'] if value is not None}
    unresolved = [f for f in facts if f['reconciliation_status'] in {'CONFLICTED', 'UNRESOLVED'}]
    # An amendment chain containing no source-established value cannot veto a
    # separate, complete original document. A chain involving a verified value
    # still fails closed, as does unresolved authority without any other proof.
    authority_conflict = unresolved and (not values or any(
        any(v is not None for v in f['effective_assertions']) for f in unresolved))
    if (authority_conflict
            or any(f.get('request_identity_conflict') for f in facts) or len(values) > 1):
        return 'CONFLICTED'
    if any(f.get('requirement_support', {}).get('status') == 'DISPUTED'
           and f['reconciliation_status'] != 'AMENDED' for f in facts):
        return 'CONFLICTED'
    # Unverified proposals have effective_assertions=[None]. They remain visible
    # for correction, but cannot veto independently established true/false
    # material or create a conflict. A source-supported disputed claim above
    # still fails closed. Required-target completeness is checked separately.
    if values == {True}:
        return 'SUPPORTED'
    if values == {False}:
        return 'NOT_SUPPORTED'
    return 'INSUFFICIENT_EVIDENCE'


def request_identity_checks(case, facts):
    """Compare original identifiers across active PA materials after corrections.

    A supplied payer identifier documents context; it does not prove eligibility.
    Old material remains stored, while an authenticated field-scoped amendment
    can supersede its assertion in the existing reconciliation mechanism.
    """
    conflicts = []
    if case.request.request_type == 'prior_authorization':
        identities = []
        for fact in facts:
            if (fact['requirement'] not in {'pa_form', 'payer_context'}
                    or fact['reconciliation_status'] == 'AMENDED'
                    or fact['requirement_support']['status'] != 'VERIFIED'
                    or True not in fact['effective_assertions']):
                continue
            for ref in fact['requirement_support']['source_refs']:
                material = ref.get('raw_value')
                if isinstance(material, dict) and material.get('payer_id'):
                    identities.append({'payer_id': material['payer_id'], 'fact_id': fact['fact_id'], 'source_ref': ref})
        if len({r['payer_id'] for r in identities}) > 1:
            conflicts.append({'field': 'payer_id', 'reason': 'Active PA form and payer context identify different payers.',
                              'values': identities, 'resolution': 'unresolved'})
            involved = {r['fact_id'] for r in identities}
            for fact in facts:
                if fact['fact_id'] in involved:
                    fact['request_identity_conflict'] = True
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_IMPLEMENTATION_SHA256:
        raise ValueError('CareFlow engine implementation changed on disk; restart before evaluating a revision.')
    return {'version': 'careflow-request-identity/1', 'conflicts': conflicts,
            'implementation_sha256': _LOADED_IMPLEMENTATION_SHA256,
            'boundary': 'Exact source identifier consistency, not payer policy, eligibility or approval.'}


def evaluate(case, *, revision=1):
    rules, manifest = ruleset(case.request.ruleset_id, case.request.ruleset_version, case.request.request_type)
    from .mapping import map_clinical, mapping_manifest, VERSION as MAPPING_VERSION
    from .requirement_support import support_manifest
    mapped, mapping_decisions = map_clinical(case) if case.clinical_bindings else ([], [])
    facts, excluded, resolution = prepare(case, mapped)
    identity_checks = request_identity_checks(case, facts)
    unresolved = []
    for requirement in sorted({f['requirement'] for f in facts}):
        relevant = [f for f in facts if f['requirement'] == requirement]
        if state(relevant) == 'CONFLICTED':
            unresolved.append({'requirement': requirement, 'fact_ids': [f['fact_id'] for f in relevant],
                               'reason': 'Source assertions or amendment authority remain in conflict.',
                               'resolution': 'unresolved'})
    checks, gaps, verification_reviews = [], [], []
    for rule in rules:
        support = [f for f in facts if f['requirement'] == rule.requirement]
        trigger_facts = [f for f in facts if f['requirement'] == rule.trigger_requirement]
        trigger_state = state(trigger_facts) if rule.trigger_requirement else 'SUPPORTED'
        selected = support + trigger_facts
        status = state(support)
        if status == 'SUPPORTED' and any(d.get('required_target_incomplete') and d['binding']['requirement'] == rule.requirement
                and any(not any(v is not None for v in f['effective_assertions']) for f in support
                        if f['fact_id'] in d['derived_fact_ids']) for d in mapping_decisions):
            status = 'INSUFFICIENT_EVIDENCE'
        status, reason, trigger_value = documentation_decision(
            status, trigger_state=trigger_state if rule.trigger_requirement else None)
        questions = []
        missing = []
        if status == 'INSUFFICIENT_EVIDENCE':
            wanted = rule.trigger_requirement if trigger_value is None else rule.requirement
            existing = [f for f in selected if f.get('requirement_support', {}).get('document_present') is True
                        and f.get('requirement_support', {}).get('clinical_source_support') == 'INSUFFICIENT_EVIDENCE']
            if existing:
                missing = [f'Review existing source semantics for {wanted}; the document exists but support is unresolved.']
                questions = [f'Which asserted dimensions are supported in the existing source for {wanted}?']
            else:
                missing = [f'Obtain source-backed {wanted} for request {case.request.request_id}.']
                questions = [f'Which original document establishes {wanted}, and where is the exact supporting passage?']
        elif status == 'NOT_SUPPORTED':
            questions = [f'Is the explicit contrary assertion for {rule.requirement} still correct? Supply new evidence for any correction.']
        elif status == 'CONFLICTED':
            questions = [f'Which source explicitly corrects the disputed {rule.requirement} or its trigger, with scoped authority?']
        for fact in selected:
            for opinion in fact.get('requirement_support', {}).get('reviewer_opinions', []):
                questions.append(f"Review {fact['fact_id']} / {opinion['source_id']}: " + opinion['question'])
        pending_review = [f['fact_id'] for f in selected
                          if f['reconciliation_status'] != 'AMENDED'
                          and f.get('requirement_support', {}).get('readiness_review_required')]
        # Source support and automatic readiness eligibility are separate decisions.
        # Explicitly inapplicable requirements do not consume irrelevant clinical evidence.
        pending_review = pending_review if status == 'SUPPORTED' else []
        if pending_review:
            questions.append('Resolve the source verification risk for ' + ', '.join(pending_review)
                             + '; a reviewer opinion alone cannot replace source evidence.')
            verification_reviews.append({'rule_id': rule.rule_id, 'fact_ids': pending_review,
                                         'reason': 'Source supported; automatic processing threshold is not established.'})
        refs = {digest(c): Citation.model_validate_json(json.dumps(c))
                for f in selected for c in f.get('requirement_citations', f['citations'])}
        conflicts = ([{'fact_ids': [f['fact_id'] for f in selected],
                       'reason': reason, 'resolution': 'unresolved'}] if status == 'CONFLICTED' else [])
        criterion = CriterionResult(
            criterion_id=rule.rule_id, criterion_role='documentation_requirement', status=status,
            reason=reason, clinical_refs=list(refs.values()), policy_refs=[], gaps=missing,
            conflicts=conflicts, derivation={'trigger': trigger_value, 'trigger_status': trigger_state},
            evidence_complete=status in {'SUPPORTED', 'NOT_APPLICABLE'} and bool(refs) and not pending_review,
        )
        result = {**criterion.model_dump(mode='json'), 'rule_id': rule.rule_id, 'rule_version': rule.version,
                  'requirement': rule.requirement, 'description': rule.description,
                  'trigger_condition': f'{rule.trigger_requirement} == true' if rule.trigger_requirement else 'always',
                  'fact_ids': [f['fact_id'] for f in selected], 'review_questions': questions,
                  'verification_review_fact_ids': pending_review}
        checks.append(result)
        if missing:
            gaps.append({'rule_id': rule.rule_id, 'requirement': rule.requirement, 'reason': reason, 'actions': missing})
    statuses = {c['status'] for c in checks}
    readiness = ('CONFLICTED' if unresolved or 'CONFLICTED' in statuses else 'NOT_SUPPORTED' if 'NOT_SUPPORTED' in statuses
                 else 'NEEDS_EVIDENCE' if 'INSUFFICIENT_EVIDENCE' in statuses or verification_reviews else 'DOCUMENTATION_READY')
    risk_reasons = [f"{c['rule_id']}:{c['status']}" for c in checks if c['status'] in {'CONFLICTED', 'NOT_SUPPORTED'}]
    risk_reasons += [f"unresolved_assertions:{c['requirement']}" for c in unresolved]
    risk_reasons += [f"source_verification_review:{r['rule_id']}" for r in verification_reviews]
    risk_reasons += [f"document_review_opinion:{f['fact_id']}" for f in facts
                     if f.get('requirement_support', {}).get('reviewer_opinions')]
    if any(f.amends_fact_id for f in case.facts):
        risk_reasons.append('fact_correction_present')
    if any(f['reason'] == 'ungrounded_citation' for f in excluded):
        risk_reasons.append('citation_grounding_failed')
    packet = {
        'schema_version': 'careflow-review-packet/1', 'case_id': case.case_id, 'revision': revision,
        'request': case.request.model_dump(mode='json'), 'review_as_of': case.review_as_of.isoformat(),
        'readiness': readiness, 'ruleset': manifest, 'checks': checks, 'facts': facts,
        'requirement_support_manifest': support_manifest(),
        'request_identity_checks': identity_checks,
        'sources': [s.model_dump(mode='json') for s in case.sources], 'excluded_facts': excluded,
        'source_screening': [{'source_id': s.source_id,
                              'availability_scope_issue': available(s.model_dump(mode='json'), case),
                              'referenced_by_fact_ids': [f['fact_id'] for f in facts
                                                        if s.source_id in {c['source_id'] for c in f['citations']}]}
                             for s in case.sources],
        'source_relationships': resolution,
        'gaps': gaps, 'unresolved_conflicts': unresolved,
        'verification_reviews': verification_reviews,
        'review_route': {'recommended': bool(risk_reasons), 'reasons': risk_reasons,
                         'reviewer_types': ['human', 'advanced_ai'], 'mandatory': False},
        'input_sha256': digest(case.model_dump(mode='json')),
        'execution': {'research_model_calls': 0, 'product_model_calls': 0,
                      'note_extraction': 'supplied_assertions_only', 'deterministic_rules': True,
                      **({'source_support_policy': case.source_support_policy,
                          'runtime_model': 'gpt-6-luna', 'external_ai_review_consumed': False}
                         if case.source_support_policy else {})},
        'decision_boundary': manifest['boundary'],
        'interpretation_limit': 'Exact provenance validates location. Requirement support additionally verifies '
                                'versioned structured material fields or an explicit source-atomic review. '
                                'Unverified assertions cannot establish readiness. Neither verifies signature authenticity '
                                'or independent medical correctness.',
    }
    if case.clinical_context:
        from .clinical_context import prepared_context
        packet['clinical_context'] = prepared_context(case)
        packet['execution'].update({
            'scope': 'this_deterministic_evaluation_only',
            'note_extraction': 'supplied_clinical_context_and_documentation_assertions',
            'upstream_extraction_model_calls': None,
            'upstream_accounting': 'External shared extraction ledger; unknown here is not zero.',
        })
    if case.clinical_bindings:
        packet['clinical_mapping'] = {'version': MAPPING_VERSION, 'manifest': mapping_manifest(), 'decisions': mapping_decisions,
                                      'derived_fact_ids': [f.fact_id for f in mapped]}
    return {**packet, 'packet_sha256': digest(packet)}
