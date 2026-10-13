"""Constructed documents demonstrate workflow, never payer/clinical accuracy."""
from ..claims_review.prepare import digest


def supplemental(requirement, assertion, text, *, patient='SYN-CF-A', request='REF-A',
                 code='specialty-consult', system='careflow-demo', encounter='ENC-A',
                 structured=False, amends=None, authority=None):
    token = digest([requirement, assertion, text, patient, request, code, system, encounter, amends, authority])[:16]
    source_id, fact_id = f'doc-{token}', f'fact-{token}'
    content = {'statement': text, 'documented': assertion} if structured else text
    if amends:
        content = {'statement': text, 'documented': assertion, 'amendment_authority_confirmed': authority,
                   'amends_fact_id': amends, 'amendment_scope': 'assertion'}
        structured = True
    ref = {'source_id': source_id, 'field': 'statement'} if structured else {
        'source_id': source_id, 'span_id': f'{source_id}:L001'}
    source = {
        'source_id': source_id, 'patient_id': patient, 'encounter_id': encounter,
        'available_at': '2026-10-10', 'origin': 'constructed_synthetic',
        'source_kind': 'structured_record' if structured else 'synthetic_note',
        'recorded_at': '2026-10-09', 'event_date': '2026-10-09',
        'record_type': 'order' if structured else 'note', 'event_link_id': None,
        'content': content,
    }
    fact = {
        'fact_id': fact_id, 'patient_id': patient, 'request_id': request, 'service_code': code,
        'code_system': system, 'requirement': requirement, 'assertion': assertion,
        'statement': text, 'evidence': [ref], 'interpretation_origin': 'structured_mapping' if structured else 'human',
    }
    if amends:
        fact.update(amends_fact_id=amends, authority_ref={'source_id': source_id, 'field': 'amendment_authority_confirmed'})
    return {'sources': [source], 'facts': [fact]}


def referral_case(*, patient='SYN-CF-A', request='REF-A', case_id='CF-REF-001',
                  request_type='referral', structured=False):
    value = {
        'schema_version': 'careflow-case/1', 'case_id': case_id,
        'request': {'request_id': request, 'patient_id': patient, 'encounter_id': 'ENC-A',
                    'request_type': request_type, 'service_code': 'specialty-consult', 'code_system': 'careflow-demo',
                    'requested_service_date': '2026-11-01',
                    'ruleset_id': 'careflow-referral' if request_type == 'referral' else 'careflow-pa',
                    'ruleset_version': '1.0.0'},
        'review_as_of': '2026-10-13', 'sources': [], 'facts': [],
    }
    statements = [
        ('request_intent', True, f'Provider requests specialty consultation for {request}.'),
        ('referral_reason', True, f'Reason for {request}: persistent symptoms requiring specialist evaluation.'),
        ('investigation_required', False, f'No investigation result is required for {request} in this constructed request.'),
        ('therapy_required', False, f'Prior therapy documentation is not required for {request}.'),
    ]
    if request_type == 'referral':
        statements.append(('destination', True, f'Destination for {request}: specialty clinic.'))
    else:
        statements += [('pa_form', True, f'PA request form for {request} is attached.'),
                       ('payer_context', True, f'Constructed payer request identifier for {request}: DEMO-PLAN. This is not eligibility verification.')]
    for requirement, assertion, text in statements:
        extra = supplemental(requirement, assertion, text, patient=patient, request=request, structured=structured)
        value['sources'] += extra['sources']
        value['facts'] += extra['facts']
    return value


def run_demo(db, output):
    import json
    from pathlib import Path
    from .contracts import Case, EvidenceUpdate, Review
    from .report import markdown
    from .service import CareFlow
    from .rules import manifests

    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    app = CareFlow(db)
    summary = []
    for kind, patient, request, cid in [('referral', 'SYN-CF-A', 'REF-A', 'CF-REF-001'),
                                       ('prior_authorization', 'SYN-CF-B', 'PA-B', 'CF-PA-001')]:
        raw = referral_case(patient=patient, request=request, case_id=cid, request_type=kind,
                            structured=kind == 'prior_authorization')
        initial = app.create(Case.model_validate_json(json.dumps(raw)))
        review = Review.model_validate_json(json.dumps({
            'reviewer_id': 'demo-document-intake', 'reviewer_type': 'human',
            'basis_revision': 1, 'basis_packet_sha256': initial['packet_sha256'],
            'fact_ids': [], 'judgment': 'AGREE',
            'reason': 'New request-specific summary received; retain the original gap report.',
        }))
        extra = supplemental('clinical_summary', True, f'Clinical summary for {request}: symptoms, relevant history and examination documented.',
                             patient=patient, request=request, structured=kind == 'prior_authorization')
        update = EvidenceUpdate.model_validate_json(json.dumps({
            'expected_revision': 1, 'review': review.model_dump(mode='json'), **extra}))
        final = app.add_evidence(cid, update)
        for name, data in [('case', raw), ('update', update.model_dump(mode='json')),
                           ('before', initial), ('after', final), ('audit', app.audit(cid))]:
            (root / f'{kind}-{name}.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (root / f'{kind}-report.md').write_text(markdown(final, app.reviews(cid)), encoding='utf-8')
        summary.append({'case_id': cid, 'before': initial['readiness'], 'after': final['readiness'],
                        'audit_verified': app.audit(cid)['verified'], 'model_calls': app.model_calls(cid)})
    (root / 'rules.json').write_text(json.dumps(manifests(), indent=2) + '\n', encoding='utf-8')
    (root / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def run_synthea_demo(db, output, archive, split_path, *, patient_count=3):
    """Constructed requests for existing development patients; no holdout tuning."""
    from datetime import date
    import json
    from pathlib import Path
    from ..claims_engine.split import load_split
    from .archive import safe_index, retrieve_context, verify_context
    from .contracts import Case, EvidenceUpdate
    from .report import markdown
    from .service import CareFlow

    split = load_split(split_path)
    selected = [entry['patient_id'] for entry in split['partitions']['development'][:patient_count]]
    if not selected:
        raise ValueError('No development patients in supplied split')
    index = safe_index(archive, allowed_patients=set(selected))
    if index.archive_sha256 != split['archive_sha256']:
        raise ValueError('SPLIT_ARCHIVE_MISMATCH')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    app, results = CareFlow(db), []
    for ordinal, patient in enumerate(selected, 1):
        encounters = [s for s in index.tables['encounters.csv'] if s.patient_id == patient]
        if not encounters:
            raise ValueError('Selected development patient has no encounter')
        encounter = encounters[-1].original_id
        for kind in ('referral', 'prior_authorization'):
            request_id, case_id = f'DEV-{ordinal}-{kind}', f'CF-SYNTHEA-{ordinal}-{kind}'
            raw = referral_case(patient=patient, request=request_id, case_id=case_id, request_type=kind,
                                structured=kind == 'prior_authorization')
            raw['request']['encounter_id'] = encounter
            for source in raw['sources']:
                source['encounter_id'] = encounter
            context = retrieve_context(index, Case.model_validate_json(json.dumps(raw)).request,
                                       received_at=date(2026, 10, 10))
            verification = verify_context(index, context)
            raw['sources'] += context['sources']
            initial = app.create(Case.model_validate_json(json.dumps(raw)))
            extra = supplemental('clinical_summary', True,
                                 f'Constructed request summary for {request_id}: synthetic demonstration attachment, not an original Synthea note.',
                                 patient=patient, request=request_id, encounter=encounter,
                                 structured=kind == 'prior_authorization')
            review = {'reviewer_id': 'demo-document-intake', 'reviewer_type': 'human',
                      'basis_revision': 1, 'basis_packet_sha256': initial['packet_sha256'], 'fact_ids': [],
                      'judgment': 'AGREE', 'reason': 'Constructed supplementary document received; native context alone did not close the gap.'}
            update = EvidenceUpdate.model_validate_json(json.dumps({'expected_revision': 1, 'review': review, **extra}))
            final = app.add_evidence(case_id, update)
            for label, value in [('case', raw), ('before', initial), ('after', final), ('audit', app.audit(case_id))]:
                with (root / f'{case_id}-{label}.json').open('x', encoding='utf-8') as stream:
                    stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            with (root / f'{case_id}-report.md').open('x', encoding='utf-8') as stream:
                stream.write(markdown(final, app.reviews(case_id)))
            results.append({'case_id': case_id, 'patient_id': patient, 'request_type': kind,
                            'before': initial['readiness'], 'after': final['readiness'],
                            'native_source_count': len(context['sources']), 'original_verification': verification,
                            'audit_verified': app.audit(case_id)['verified'],
                            'original_documentary_assertions_created': 0})
    receipt = {'archive_sha256': index.archive_sha256, 'partition': 'development',
               'patient_count': len(selected), 'case_count': len(results), 'results': results,
               'research_model_calls': 0, 'product_model_calls': 0,
               'scope': 'Source preservation and lifecycle test; requests and supplementary documents are constructed. No clinical accuracy or recall estimate.'}
    with (root / 'summary.json').open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(receipt, indent=2) + '\n')
    return receipt
