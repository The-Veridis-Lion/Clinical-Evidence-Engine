"""Explicit offline truth-logic boundary for the original v1 material fixtures.

These inputs predate source-semantic verification. Their booleans are assumptions
of a deterministic-rule unit test, not confirmed clinical/documentary evidence.
This module does not call CareFlow service/store, produce a review packet, attach
verification envelopes, or expose a runtime/API option to trust caller assertions.
"""
from ...claims_review.prepare import digest
from ...claims_review.relationships import reconcile
from ..evidence import available, citation, source_dict
from ..rules import documentation_decision, ruleset


def evaluate_rule_fixture(case):
    """Replay original scope, citation, amendment and five-state unit semantics.

    Exact original inputs and labels stay untouched. All accepted input booleans
    are explicitly marked ASSUMED_VERIFIED_BY_RULE_FIXTURE in the result. The
    production evidence gate never consumes this record.
    """
    sources = {s.source_id: source_dict(s, i) for i, s in enumerate(case.sources)}
    rows, excluded, projected = [], [], []
    for fact in case.facts:
        reason, refs = None, []
        for field, issue in [('patient_id', 'patient_mismatch'), ('request_id', 'request_mismatch'),
                             ('service_code', 'service_mismatch'), ('code_system', 'service_mismatch')]:
            if getattr(fact, field) != getattr(case.request, field):
                reason = reason or issue
        for ref in fact.evidence:
            source = sources[ref.source_id]
            reason = reason or available(source, case)
            try:
                refs.append(citation(ref, source).model_dump(mode='json'))
            except ValueError:
                reason = reason or 'ungrounded_citation'
        row = {**fact.model_dump(mode='json'), 'citations': refs,
               'fact_sha256': digest(fact.model_dump(mode='json')),
               'verification_boundary': 'ASSUMED_VERIFIED_BY_RULE_FIXTURE'}
        if reason:
            excluded.append({**row, 'reason': reason})
            continue
        content = {'value': fact.assertion}
        if fact.amends_fact_id:
            authority_source = sources[fact.authority_ref.source_id]
            try:
                auth = citation(fact.authority_ref, authority_source)
                meta = authority_source['content']
                valid = (available(authority_source, case) is None and auth.raw_value is True
                    and fact.authority_ref.field == 'amendment_authority_confirmed'
                    and fact.authority_ref.source_id in {r.source_id for r in fact.evidence}
                    and meta.get('amends_fact_id') == fact.amends_fact_id
                    and meta.get('amendment_scope') == 'assertion')
            except ValueError:
                valid = False
            content['source_relationship'] = {'relation': 'amends', 'target_source_id': fact.amends_fact_id,
                'field': 'content/value', 'replacement': fact.assertion, 'authenticated': valid,
                'authority_scope': 'content/value'}
        projected.append({'patient_id': fact.patient_id, 'source_id': fact.fact_id,
            'encounter_id': case.request.encounter_id, 'available_at': None,
            'availability_basis': 'unknown', 'event_date': None, 'recorded_at': None,
            'origin': 'constructed_synthetic', 'record_type': 'order',
            'event_link_id': case.request.request_id + ':' + fact.requirement, 'content': content,
            'original_locator': {'careflow_fact_id': fact.fact_id, 'citations': refs},
            'source_ref': {'json_pointer': '/facts/' + str(len(rows))}})
        rows.append(row)
    resolution = reconcile(projected)
    for row in rows:
        resolved = resolution['derived'][row['fact_id']]['content/value']
        row.update(effective_assertions=resolved['values'], reconciliation_status=resolved['status'])

    def truth(requirement):
        facts = [r for r in rows if r['requirement'] == requirement]
        values = {v for f in facts for v in f['effective_assertions'] if v is not None}
        if any(f['reconciliation_status'] in {'CONFLICTED', 'UNRESOLVED'} for f in facts) or len(values) > 1:
            return 'CONFLICTED'
        return 'SUPPORTED' if values == {True} else 'NOT_SUPPORTED' if values == {False} else 'INSUFFICIENT_EVIDENCE'

    rules, manifest = ruleset(case.request.ruleset_id, case.request.ruleset_version, case.request.request_type)
    checks = []
    for rule in rules:
        selected = [r for r in rows if r['requirement'] in {rule.requirement, rule.trigger_requirement}]
        status, reason, trigger = documentation_decision(truth(rule.requirement),
            trigger_state=truth(rule.trigger_requirement) if rule.trigger_requirement else None)
        checks.append({'rule_id': rule.rule_id, 'rule_version': rule.version, 'requirement': rule.requirement,
                       'status': status, 'reason': reason, 'trigger': trigger,
                       'fact_ids': [f['fact_id'] for f in selected],
                       'clinical_refs': [c for f in selected for c in f['citations']],
                       'derivation': {'trigger': trigger},
                       'conflicts': [{'fact_ids': [f['fact_id'] for f in selected], 'reason': reason}]
                           if status == 'CONFLICTED' else []})
    states = {c['status'] for c in checks}
    global_conflict = any(truth(r['requirement']) == 'CONFLICTED' for r in rows)
    fixture_readiness = ('CONFLICTED' if global_conflict or 'CONFLICTED' in states else
        'NOT_SUPPORTED' if 'NOT_SUPPORTED' in states else
        'NEEDS_EVIDENCE' if 'INSUFFICIENT_EVIDENCE' in states else 'DOCUMENTATION_READY')
    return {'schema_version': 'careflow-offline-rule-fixture/1', 'case_id': case.case_id,
        'input_sha256': digest(case.model_dump(mode='json')), 'ruleset': manifest,
        'fixture_readiness': fixture_readiness, 'checks': checks, 'facts': rows, 'excluded_facts': excluded,
        'unresolved_conflicts': [{'requirement': req, 'fact_ids': [r['fact_id'] for r in rows if r['requirement'] == req]}
            for req in sorted({r['requirement'] for r in rows}) if truth(req) == 'CONFLICTED'],
        'fixture_sha256': digest({'input': case.model_dump(mode='json'), 'checks': checks}),
        'fixture_review_recommended': fixture_readiness in {'CONFLICTED', 'NOT_SUPPORTED'},
        'production_evidence_certificate': False,
        'boundary': 'Assumed truth values for original deterministic rule fixtures only. '
                    'No source-semantic, document-existence, clinical or insurance approval validation.'}
