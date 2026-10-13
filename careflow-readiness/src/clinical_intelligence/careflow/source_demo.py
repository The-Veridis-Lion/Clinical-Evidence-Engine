"""Original synthetic request documents -> verified material -> auditable revisions.

These authored source documents are software demonstration inputs, not extracted
medical gold, payer policies or actual clinician attestations. No model is called.
"""
import json
from pathlib import Path

from ..claims_review.facts import source_key
from .contracts import Case, EvidenceUpdate
from .requirement_support import material_envelope


def source(identifier, request, content, *, text=False):
    return {'source_id': identifier, 'patient_id': request['patient_id'],
            'encounter_id': request['encounter_id'], 'available_at': '2026-10-10',
            'recorded_at': '2026-10-09', 'event_date': None, 'event_link_id': None,
            'availability_basis': 'explicit_case_metadata', 'original_locator': None,
            'record_type': 'note' if text else 'order', 'origin': 'constructed_synthetic',
            'source_kind': 'synthetic_note' if text else 'structured_record', 'content': content}


def material_source(request, requirement, material, *, assertion=True, suffix=''):
    identifier = request['request_id'] + ':' + requirement + suffix
    scope = {k: request[k] for k in ('patient_id', 'request_id', 'service_code', 'code_system')}
    content = {'material': {**scope, **material}}
    content['requirement_support'] = material_envelope(
        request, requirement, material['document_type'], {'source_id': identifier, 'field': 'material'},
        assertion=assertion, document_present=material['document_type'] != 'missing_document_attestation')
    return source(identifier, request, content)


def source_intake(kind, *, patient=None, case_id=None):
    """Complete, distinct Referral and PA materials; a diagnosis creates no form."""
    patient = patient or ('SYN-REFERRAL' if kind == 'referral' else 'SYN-PA')
    request = {'request_id': patient + ':request', 'patient_id': patient, 'encounter_id': patient + ':visit',
               'request_type': kind, 'service_code': 'pulmonary-consult' if kind == 'referral' else '73221',
               'code_system': 'synthetic-services' if kind == 'referral' else 'CPT',
               'requested_service_date': '2026-10-20',
               'ruleset_id': 'careflow-referral' if kind == 'referral' else 'careflow-pa', 'ruleset_version': '1.0.0'}
    reason = 'Persistent cough requiring pulmonary evaluation.' if kind == 'referral' else 'Persistent shoulder pain despite documented physical therapy.'
    summary = source(patient + ':summary-original', request,
                     'Synthetic clinical summary. ' + reason + ' Examination and relevant history are documented.', text=True)
    materials = [
        ('request_intent', {'document_type': 'provider_order', 'provider_id': 'SYN-PROVIDER', 'intent_state': 'requested'}, True),
        ('referral_reason', {'document_type': 'referral_request' if kind == 'referral' else 'prior_authorization_request', 'clinical_reason': reason}, True),
        ('clinical_summary', {'document_type': 'clinical_summary', 'document_role': 'clinical_summary',
                              'summary_source_id': summary['source_id'], 'summary_sha256': source_key(summary)}, True),
        ('investigation_required', {'document_type': 'request_requirements', 'investigation_required': kind == 'referral'}, kind == 'referral'),
        ('therapy_required', {'document_type': 'request_requirements', 'therapy_required': kind != 'referral'}, kind != 'referral'),
    ]
    if kind == 'referral':
        materials += [
            ('destination', {'document_type': 'referral_request', 'destination_id': 'SYN-CLINIC', 'destination_name': 'Pulmonary clinic'}, True),
            ('investigation_result', {'document_type': 'investigation_report', 'result_id': 'SYN-CXR',
                'result_value': 'No acute pulmonary process', 'action_state': 'completed', 'polarity': 'present',
                'temporality': 'historical', 'experiencer': 'patient', 'event_date': '2026-10-08'}, True),
        ]
    else:
        materials += [
            ('pa_form', {'document_type': 'prior_authorization_form', 'form_id': 'SYN-PA-FORM',
                'payer_id': 'SYN-PLAN', 'provider_id': 'SYN-PROVIDER', 'form_status': 'completed',
                'form_content': {'requested_service': request['service_code'], 'service_code': request['service_code'], 'code_system': request['code_system'],
                                 'patient_id': patient, 'request_id': request['request_id'], 'reason': reason}}, True),
            ('payer_context', {'document_type': 'payer_request', 'payer_id': 'SYN-PLAN', 'payer_request_id': 'SYN-PAYER-REQUEST'}, True),
            ('therapy_completed', {'document_type': 'therapy_record', 'therapy_name': 'Six week physical therapy course',
                'clinical_purpose': 'therapeutic', 'completion_scope': 'course', 'action_state': 'completed', 'polarity': 'present',
                'temporality': 'historical', 'experiencer': 'patient', 'event_date': '2026-10-08'}, True),
        ]
    return {'schema_version': 'careflow-source-intake/1', 'case_id': case_id or ('CF-REF-001' if kind == 'referral' else 'CF-PA-001'),
            'request': request, 'review_as_of': '2026-10-13',
            'sources': [summary, *[material_source(request, req, material, assertion=value) for req, material, value in materials]],
            'extractions': [], 'clinical_bindings': []}


def run_source_demo(db, output):
    from .raw_input import build_case
    from .report import markdown
    from .service import CareFlow
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    app, outcomes = CareFlow(db), []
    for kind in ('referral', 'prior_authorization'):
        full = source_intake(kind)
        missing = {**full, 'sources': [s for s in full['sources'] if 'summary' not in s['source_id']]}
        initial_case, initial_receipt = build_case(**{k: v for k, v in missing.items() if k != 'schema_version'})
        final_case, final_receipt = build_case(**{k: v for k, v in full.items() if k != 'schema_version'})
        before = app.create(initial_case)
        received_ids = {s.source_id for s in initial_case.sources}
        added_sources = [s.model_dump(mode='json') for s in final_case.sources if s.source_id not in received_ids]
        added_facts = [f.model_dump(mode='json') for f in final_case.facts if any(r.source_id not in received_ids for r in f.evidence)]
        update = EvidenceUpdate.model_validate_json(json.dumps({
            'expected_revision': 1, 'sources': added_sources, 'facts': added_facts,
            'intake': {'actor_id': 'synthetic-document-receipt', 'actor_type': 'intake_service', 'basis_revision': 1,
                       'basis_packet_sha256': before['packet_sha256'], 'reason': 'Receive the original request-attached clinical summary.'}}))
        after = app.add_evidence(full['case_id'], update)
        audit = app.audit(full['case_id'])
        result = {'case_id': full['case_id'], 'before': before['readiness'], 'after': after['readiness'],
                  'audit_verified': audit['verified'], 'revision_count': audit['revision_count'],
                  'reference_type': 'constructed_original_materials', 'new_model_calls': 0,
                  'model_calls': app.model_calls(full['case_id'])}
        outcomes.append(result)
        for label, data in [('intake', missing), ('complete-intake', full), ('case', initial_case.model_dump(mode='json')),
                            ('update', update.model_dump(mode='json')), ('before', before), ('after', after),
                            ('audit', audit), ('intake-receipts', [initial_receipt, final_receipt])]:
            with (root / f'{kind}-{label}.json').open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        with (root / f'{kind}-report.md').open('x', encoding='utf-8') as stream:
            stream.write(markdown(after))
    with (root / 'summary.json').open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(outcomes, indent=2) + '\n')
    if any(r['before'] != 'NEEDS_EVIDENCE' or r['after'] != 'DOCUMENTATION_READY'
           or not r['audit_verified'] for r in outcomes):
        raise ValueError('Source demo did not meet its declared workflow; retained outputs explain the failure.')
    return outcomes
