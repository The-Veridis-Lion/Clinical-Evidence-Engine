"""Adapt request-scoped assertions to existing provenance and reconciliation."""
from ..claims_review.contracts import Citation
from ..claims_review.facts import pointer, source_key
from ..claims_review.prepare import digest, line_anchors
from ..claims_review.relationships import reconcile


def source_dict(source, position):
    value = source.model_dump(mode='json')
    value['source_ref'] = {'json_pointer': f'/sources/{position}', 'source_id': source.source_id}
    return value


def citation(ref, source):
    if ref.span_id is not None:
        if not isinstance(source['content'], str):
            raise ValueError('Line citation requires note content')
        anchor = next((a for a in line_anchors(source['source_id'], source['content'])
                       if a['span_id'] == ref.span_id), None)
        if anchor is None:
            raise ValueError('Unknown Unicode source anchor')
        return Citation(patient_id=source['patient_id'], source_id=source['source_id'],
                        source_sha256=source_key(source), method='unicode_line_anchor',
                        locator=ref.span_id, quote=anchor['quote'], start=anchor['start'], end=anchor['end'],
                        original_locator=source['original_locator'])
    if not isinstance(source['content'], dict) or ref.field not in source['content']:
        raise ValueError('Unknown original structured field')
    return pointer(source, 'content/' + ref.field)


def available(source, case):
    request = case.request
    if source['patient_id'] != request.patient_id:
        return 'patient_mismatch'
    if source['available_at'] is None:
        return 'availability_unknown'
    if source['available_at'] > case.review_as_of.isoformat():
        return 'not_available_as_of'
    if source['recorded_at'] is not None and source['recorded_at'] > source['available_at']:
        return 'inconsistent_recorded_and_available_dates'
    # A future service order is valid PA/referral evidence; future actual events are not.
    if (source['record_type'] in {'observation', 'procedure', 'condition', 'encounter'}
            and source['event_date'] is not None and source['event_date'] > case.review_as_of.isoformat()):
        return 'future_actual_event'
    if request.encounter_id and source['encounter_id'] and source['encounter_id'] != request.encounter_id:
        return 'encounter_mismatch'
    return None


def prepare(case, extra_facts=()):
    from .requirement_support import verify_requirement_support
    sources = {s.source_id: source_dict(s, i) for i, s in enumerate(case.sources)}
    facts, excluded, projected = [], [], []
    for i, fact in enumerate([*case.facts, *extra_facts]):
        reason = None
        request = case.request
        if fact.patient_id != request.patient_id:
            reason = 'patient_mismatch'
        elif fact.request_id != request.request_id:
            reason = 'request_mismatch'
        elif (fact.service_code, fact.code_system) != (request.service_code, request.code_system):
            reason = 'service_mismatch'
        refs, errors = [], []
        for ref in fact.evidence:
            source = sources[ref.source_id]
            error = available(source, case)
            try:
                grounded = citation(ref, source)
                refs.append(grounded.model_dump(mode='json'))
            except ValueError as exc:
                errors.append(str(exc))
                error = error or 'ungrounded_citation'
            if error:
                reason = reason or error
        verification = verify_requirement_support(case, fact, refs, derived_facts=extra_facts)
        for support_ref in verification['source_refs']:
            if not any(digest(existing) == digest(support_ref) for existing in refs):
                refs.append(support_ref)
        effective_assertion = verification['effective_assertion']
        row = {**fact.model_dump(mode='json'), 'citations': refs,
               'assertion_status': 'ASSERTED_PRESENT' if fact.assertion is True else
                                   'ASSERTED_ABSENT' if fact.assertion is False else 'UNKNOWN',
               'grounding_errors': errors, 'fact_sha256': digest(fact.model_dump(mode='json')),
               'requirement_support': verification}
        if verification.get('semantic_evidence_binding_version'):
            row.update(selected_refs=[r.model_dump(mode='json') for r in fact.evidence],
                semantic_support_refs=verification['semantic_support_refs'],
                requirement_citations=verification['source_refs'])
        if reason:
            excluded.append({**row, 'reason': reason})
            continue
        facts.append(row)
        # The existing field-level engine evaluates amendments and cycles. IDs
        # identify assertions; the projection does not modify original documents.
        # Original proposals stay visible. Only independently supported source
        # semantics enter the deterministic truth-state projection.
        content = {'value': effective_assertion}
        if fact.amends_fact_id:
            authority_source = sources[fact.authority_ref.source_id]
            try:
                auth = citation(fact.authority_ref, authority_source)
                refs.append(auth.model_dump(mode='json'))
                metadata = authority_source['content']
                valid_authority = (available(authority_source, case) is None
                                   and auth.raw_value is True
                                   and fact.authority_ref.field == 'amendment_authority_confirmed'
                                   and fact.authority_ref.source_id in {r.source_id for r in fact.evidence}
                                   and metadata.get('amends_fact_id') == fact.amends_fact_id
                                   and metadata.get('amendment_scope') == 'assertion')
            except ValueError:
                valid_authority = False
            content['source_relationship'] = {
                'relation': 'amends', 'target_source_id': fact.amends_fact_id,
                'field': 'content/value', 'replacement': effective_assertion,
                'authenticated': valid_authority, 'authority_scope': 'content/value',
            }
        projected.append({
            'patient_id': fact.patient_id, 'source_id': fact.fact_id,
            'encounter_id': request.encounter_id, 'available_at': None,
            'availability_basis': 'unknown', 'event_date': None, 'recorded_at': None,
            'origin': 'constructed_synthetic', 'record_type': 'order',
            'event_link_id': f'{request.request_id}:{fact.requirement}', 'content': content,
            'original_locator': {'careflow_fact_id': fact.fact_id, 'citations': refs},
            'source_ref': {'json_pointer': f'/facts/{i}'},
        })
    resolution = reconcile(projected)
    for row in facts:
        state = resolution['derived'][row['fact_id']]['content/value']
        row['effective_assertions'] = state['values']
        row['reconciliation_status'] = state['status']
        row['related_fact_ids'] = state['source_ids']
    return facts, excluded, resolution
