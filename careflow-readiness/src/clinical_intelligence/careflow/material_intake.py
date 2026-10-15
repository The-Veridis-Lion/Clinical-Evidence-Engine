"""Received labeled documents -> existing material checks with exact field lines.

This is a bounded form adapter, not clinical NLP. No checkbox is an assertion and
no missing field is populated from the current request. The original text and
each parsed field's Unicode offsets are retained with the candidate material.
"""
from datetime import date
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from .contracts import Contract, EvidenceIntake, Identifier, Review, Source, SourceMaterialUpdate
from .requirement_support import SCOPE, material_envelope

VERSION = 'careflow-received-form/1'
_SOURCE_PATH = Path(__file__).resolve()
_LOADED_SHA256 = hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest()
DOCUMENTS = {
    'provider_order': ('request_intent', 'destination'),
    'referral_request': ('request_intent', 'referral_reason', 'destination', 'investigation_required', 'therapy_required'),
    'prior_authorization_request': ('request_intent', 'referral_reason', 'investigation_required', 'therapy_required'),
    'request_requirements': ('investigation_required', 'therapy_required'),
    'investigation_report': ('investigation_result',),
    'therapy_record': ('therapy_completed',),
    'prior_authorization_form': ('pa_form', 'payer_context'),
    'payer_request': ('payer_context',),
}
FIELD_LABELS = {
    'patient_id': ('patient id',), 'request_id': ('request id',),
    'service_code': ('service code', 'requested service'), 'code_system': ('code system',),
    'provider_id': ('provider id',), 'intent_state': ('intent state', 'request status'),
    'clinical_reason': ('clinical reason', 'reason for referral', 'reason for request'),
    'destination_id': ('destination id',), 'destination_name': ('destination name',),
    'investigation_required': ('investigation required',), 'therapy_required': ('prior therapy required', 'therapy required'),
    'result_id': ('result id',), 'result_value': ('result value',),
    'therapy_name': ('therapy name',), 'completion_scope': ('completion scope',),
    'clinical_purpose': ('clinical purpose',), 'action_state': ('action state',),
    'polarity': ('polarity',), 'temporality': ('temporality',), 'experiencer': ('experiencer',),
    'event_date': ('event date',), 'form_id': ('form id', 'pa form id'),
    'form_status': ('form status',), 'payer_id': ('payer id',), 'payer_request_id': ('payer request id',),
    'amends_fact_id': ('amends fact id',), 'amendment_authority_confirmed': ('amendment authority confirmed',),
    'amendment_scope': ('amendment scope',),
}
LABEL_TO_FIELD = {label: field for field, labels in FIELD_LABELS.items() for label in (*labels, field)}
BOOLEAN_FIELDS = {'investigation_required', 'therapy_required', 'amendment_authority_confirmed'}
ENUM_FIELDS = {
    'intent_state': {'requested', 'ordered', 'not_requested', 'discussed', 'planned'},
    'action_state': {'completed', 'finished', 'performed', 'administered', 'planned', 'scheduled', 'ongoing',
                     'not_completed', 'not_performed', 'not_administered', 'not_started', 'unknown'},
    'completion_scope': {'course', 'single_event', 'unknown'},
    'clinical_purpose': {'therapeutic', 'diagnostic', 'unknown'},
    'polarity': {'present', 'absent', 'uncertain'}, 'temporality': {'current', 'historical', 'planned', 'unknown'},
    'experiencer': {'patient', 'family', 'other', 'unknown'},
    'form_status': {'completed', 'submitted', 'draft', 'blank'},
    'amendment_scope': {'assertion'},
}


class ReceivedMaterial(Contract):
    schema_version: Literal['careflow-received-form/1'] = VERSION
    document_id: Identifier
    document_type: Literal['provider_order', 'referral_request', 'prior_authorization_request',
        'request_requirements', 'investigation_report', 'therapy_record', 'prior_authorization_form', 'payer_request']
    received_at: date
    text: str = Field(min_length=1, max_length=100_000)


class ReceivedMaterialUpdate(Contract):
    expected_revision: int = Field(ge=1)
    document: ReceivedMaterial
    intake: EvidenceIntake | None = None
    review: Review | None = None


def adapter_identity():
    if hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest() != _LOADED_SHA256:
        raise ValueError('Received form adapter changed on disk; restart before evaluating materials')
    return {'version': VERSION, 'code_sha256': _LOADED_SHA256,
            'scope': 'Exact original labeled fields only; no inferred narrative meaning or signature authentication.'}


def parsed_fields(text):
    """Only whole original labeled lines; no prose keywords or fuzzy truth votes."""
    adapter_identity()
    fields, evidence, unknown, unparsed = {}, {}, [], []
    offset = 0
    for line in text.splitlines(keepends=True):
        match = re.fullmatch(r'\s*([^:\n\r]{1,70})\s*:\s*([^\n\r]*)\s*', line.rstrip('\r\n'))
        recognized = False
        if match:
            label = ' '.join(match[1].strip().casefold().split())
            field = LABEL_TO_FIELD.get(label)
            if field:
                recognized = True
                if field in fields:
                    raise ValueError('Duplicate original field: ' + field + '; retain conflicting documents as separate sources')
                raw = match[2].strip()
                value = raw
                if field in BOOLEAN_FIELDS:
                    value = {'yes': True, 'true': True, 'no': False, 'false': False}.get(raw.casefold())
                elif field in ENUM_FIELDS:
                    canonical = '_'.join(raw.casefold().split())
                    value = canonical if canonical in ENUM_FIELDS[field] else None
                elif field == 'event_date':
                    try:
                        value = date.fromisoformat(raw).isoformat()
                    except ValueError:
                        value = None
                if not raw:
                    value = None
                fields[field] = value
                evidence[field] = {'start': offset, 'end': offset + len(line.rstrip('\r\n')),
                    'quote': line.rstrip('\r\n'), 'raw_value': raw}
                if value is None:
                    unknown.append(field)
        if line.strip() and not recognized:
            # Unknown narrative can qualify or revoke an otherwise positive
            # field. A partial parser has no authority to discard it as noise.
            unparsed.append({'start': offset, 'end': offset + len(line.rstrip('\r\n')),
                             'quote': line.rstrip('\r\n')})
        offset += len(line)
    return fields, evidence, unknown, unparsed


def received_material_sources(document, request):
    """Create candidates from received fields, leaving all truth decisions downstream."""
    fields, evidence, unknown, unparsed = parsed_fields(document.text)
    if any(not isinstance(fields.get(key), str) or not fields[key].strip() for key in SCOPE):
        raise ValueError('Received form needs its actual Patient ID, Request ID, Service code and Code system labeled fields')
    # Source identity is the document's actual patient, not a rewritten target.
    # Other request/service IDs remain in material and fail the existing scope gate.
    same_patient = fields['patient_id'] == request.patient_id
    common = {'patient_id': fields['patient_id'], 'encounter_id': request.encounter_id if same_patient else None,
        'available_at': document.received_at.isoformat(), 'recorded_at': None, 'event_date': None,
        'event_link_id': None, 'origin': 'request_intake', 'availability_basis': 'explicit_case_metadata',
        'original_locator': {'adapter_version': VERSION, 'document_id': document.document_id}}
    original = Source.model_validate_json(json.dumps({**common, 'source_id': document.document_id,
        'record_type': 'note', 'source_kind': 'clinical_text', 'content': document.text}))
    sources = [original]
    material = {**{key: value for key, value in fields.items() if key not in {'amends_fact_id', 'amendment_authority_confirmed', 'amendment_scope'}},
                'document_type': document.document_type}
    if document.document_type == 'prior_authorization_form':
        # Each retained body value came from the actual form. No target IDs or
        # synthetic form body are injected to make an incomplete form pass.
        material['form_content'] = {key: fields[key] for key in (*SCOPE, 'payer_id', 'provider_id', 'clinical_reason') if key in fields}
    for requirement in DOCUMENTS[document.document_type]:
        # Unknown conditional fields remain unknown, never an automatic waiver.
        assertion = fields.get(requirement) if requirement in BOOLEAN_FIELDS else True
        if requirement == 'request_intent' and fields.get('intent_state') == 'not_requested':
            assertion = False
        if requirement in {'therapy_completed', 'investigation_result'} and fields.get('action_state') in {'not_completed', 'not_performed', 'not_administered'}:
            assertion = False
        source_id = document.document_id + ':' + requirement
        content = {'material': material, 'requirement_support': material_envelope(
            request, requirement, document.document_type, {'source_id': source_id, 'field': 'material'}, assertion=assertion),
            'original_document': {'source_id': original.source_id,
                'text_sha256': hashlib.sha256(document.text.encode('utf-8')).hexdigest()},
            'original_field_evidence': evidence, 'unrecognized_field_values': unknown,
            'unparsed_document_lines': unparsed,
            'adapter_version': VERSION,
            'boundary': 'Exact received form fields; document authenticity and clinical truth are not certified.'}
        if fields.get('amends_fact_id'):
            # Exactly one requirement per amendment avoids guessing its target.
            if len(DOCUMENTS[document.document_type]) != 1:
                raise ValueError('Multi-requirement form amendments require the existing field-scoped correction API')
            content.update(amends_fact_id=fields['amends_fact_id'],
                amendment_authority_confirmed=fields.get('amendment_authority_confirmed'),
                amendment_scope=fields.get('amendment_scope'))
        sources.append(Source.model_validate_json(json.dumps({**common, 'source_id': source_id,
            'record_type': 'order', 'source_kind': 'structured_record', 'content': content})))
    return sources


def append_received_material(app, case_id, update):
    packet = app.packet(case_id)
    from .contracts import Request
    request = Request.model_validate_json(json.dumps(packet['request']))
    sources = received_material_sources(update.document, request)
    raw = {'expected_revision': update.expected_revision, 'sources': [s.model_dump(mode='json') for s in sources],
        'intake': update.intake.model_dump(mode='json') if update.intake else None,
        'review': update.review.model_dump(mode='json') if update.review else None}
    return app.add_material_sources(case_id, SourceMaterialUpdate.model_validate_json(json.dumps(raw)))
