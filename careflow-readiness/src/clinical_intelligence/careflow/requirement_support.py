"""Versioned source-semantic gate before a declared assertion affects readiness.

An exact quotation proves location. It does not prove an order, completed therapy
or an attached form. This module accepts explicit typed original material fields
or a retained independent atomic source review; free text remains unverified.
Neither path authenticates a provider nor supplies independent medical gold.
"""
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictBool

from ..claims_review.contracts import Contract, Identifier
from ..claims_review.facts import source_key
from ..claims_review.prepare import digest
from .contracts import EvidenceRef, Fact, Requirement

_SOURCE_PATH = Path(__file__).resolve()
_LOADED_SOURCE_SHA256 = hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest()
VERSION = 'careflow-requirement-support/2'
ATOMIC_REVIEW_VERSION = 'careflow-atomic-support-review/2'
CLINICAL_SUPPORT_VERSION = 'careflow-clinical-source-support/3'
SCOPE = ('patient_id', 'request_id', 'service_code', 'code_system')
DOCUMENT_TYPES = {
    'request_intent': {'provider_order', 'referral_request', 'prior_authorization_request'},
    'referral_reason': {'referral_request', 'prior_authorization_request', 'clinical_summary'},
    'destination': {'provider_order', 'referral_request'},
    'clinical_summary': {'clinical_summary'},
    'investigation_required': {'request_requirements', 'referral_request', 'prior_authorization_request'},
    'therapy_required': {'request_requirements', 'referral_request', 'prior_authorization_request'},
    'investigation_result': {'investigation_report'},
    'therapy_completed': {'therapy_record'},
    'pa_form': {'prior_authorization_form'},
    'payer_context': {'payer_request', 'prior_authorization_form'},
}


class RequirementEvidence(Contract):
    # Preserve original v1 sources for review; current semantic checks do not
    # restore its unsafe dose -> completed-course inference.
    schema_version: Literal['careflow-requirement-support/1', 'careflow-requirement-support/2'] = VERSION
    patient_id: Identifier
    request_id: Identifier
    service_code: Identifier
    code_system: Identifier
    requirement: Requirement
    assertion: StrictBool | None
    document_type: Identifier
    document_present: StrictBool | None
    support_basis: Literal['original_structured_fields', 'source_atomic_review']
    review_status: Literal['source_confirmed', 'candidate', 'disputed']
    source_refs: list[EvidenceRef] = Field(min_length=1)
    reviewer_id: Identifier | None = None
    reviewer_type: Literal['human', 'advanced_ai'] | None = None
    model: Identifier | None = None
    model_version: Identifier | None = None


def check_loaded_implementation():
    if hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
        raise ValueError('requirement_support_implementation_changed: restart before evaluating original materials')


def support_manifest():
    check_loaded_implementation()
    from ..evidence_bridge import verification_identity
    value = {'version': VERSION, 'code_sha256': _LOADED_SOURCE_SHA256,
        'document_types': {k: sorted(v) for k, v in DOCUMENT_TYPES.items()},
        'therapy_completed': {'action_states': ['completed', 'finished'], 'completion_scope': 'course'},
        'rules': ['Exact original fields plus complete request scope.',
            'Typed material, actual form content and identifiers; a boolean is insufficient.',
            'Unknown, disputed, unavailable, planned and other-subject evidence cannot support readiness.',
            'An administered dose or performed event does not establish completion of the requested course.',
            'Mapped clinical assertions additionally require an independent retained atomic source review.'],
        'clinical_support_version': CLINICAL_SUPPORT_VERSION,
        'atomic_review_version': ATOMIC_REVIEW_VERSION,
        'shared_verification': verification_identity(),
        'boundary': 'Synthetic project documentation requirements, no payer-policy authority or inferred lookback window. '
                    'Documentation support and retained reviewer judgment, not signature authentication or medical gold. '
                    'Advanced-AI opinions alone cannot establish verified materials.'}
    return {**value, 'sha256': digest(value)}


def material_envelope(request, requirement, document_type, material_ref, *, assertion=True,
                      document_present=True):
    """Build a candidate envelope; verification still reads the original material."""
    request = request.model_dump(mode='json') if hasattr(request, 'model_dump') else request
    return RequirementEvidence.model_validate_json(json.dumps({
        **{field: request[field] for field in SCOPE}, 'requirement': requirement,
        'assertion': assertion, 'document_type': document_type, 'document_present': document_present,
        'support_basis': 'original_structured_fields', 'review_status': 'source_confirmed',
        'source_refs': [material_ref],
    })).model_dump(mode='json')


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def clinical_verification_input(source, clinical, *, completion_scope=None):
    """Lossless clinical -> shared-source claim adapter; no source interpretation.

    The metadata digest and original text digest serve different purposes. Keep
    both in retained reviews, rather than replacing the original provenance hash.
    A free-form status is not an event conclusion: noncanonical values remain
    unknown until a source verifier can resolve them.
    """
    raw = source.model_dump(mode='json') if hasattr(source, 'model_dump') else source
    if not isinstance(raw.get('content'), str):
        raise ValueError('Atomic clinical verification requires original source text')
    original = clinical.model_dump(mode='json') if hasattr(clinical, 'model_dump') else clinical
    from .mapping import normalized_status
    action = original['category'] in {'medication', 'treatment', 'procedure'}
    canonical = normalized_status(original.get('clinical_status'))
    known_states = {'completed', 'finished', 'administered', 'performed', 'ongoing', 'taken',
                    'stopped', 'prescribed', 'ordered', 'planned', 'discussed', 'not_completed',
                    'not_performed', 'not_administered', 'not_started', 'not_taken', 'unknown'}
    spans = [original['evidence'], *original.get('supporting_evidence', [])]
    available_at = raw.get('available_at')
    if hasattr(available_at, 'isoformat'):
        available_at = available_at.isoformat()
    source_value = {'source_id': raw['source_id'], 'text': raw['content'],
        'sha256': hashlib.sha256(raw['content'].encode('utf-8')).hexdigest(),
        'patient_id': raw['patient_id'], 'encounter_id': raw.get('encounter_id'),
        'available_at': available_at,
        'input_kind': (raw.get('original_locator') or {}).get('input_kind', 'note')}
    claim = {'claim_id': original['context_fact_id'], 'source_id': raw['source_id'],
        'patient_id': raw['patient_id'], 'encounter_id': raw.get('encounter_id'),
        'category': original['category'], 'concept': original['concept'], 'spans': spans,
        'experiencer': original['experiencer'], 'reporting_basis': original.get('assertion_basis') or 'unknown',
        'polarity': original['polarity'],
        # ClinicalFact has no typed certainty/action-type field. Polarity or a
        # medication category cannot manufacture either missing dimension.
        'certainty': 'unknown',
        'temporality': original['temporality'], 'event_time': None,
        'action_type': None,
        'action_state': canonical if action and canonical in known_states else 'unknown',
        'completion_scope': completion_scope,
        'attributes': {key: value for key, value in (original.get('attributes') or {}).items() if value is not None}}
    return source_value, claim


def atomic_support_review(source, clinical, *, requirement, reviews=()):
    """Retain an independently computed source result, not a reviewer stamp.

    The shared verifier is recomputed on consumption. Caller-supplied status,
    confidence, source locations or a model name cannot authenticate this proof.
    """
    from ..evidence_bridge import verify_source_claim
    completion_scope = 'course' if requirement == 'therapy_completed' else None
    original_source, claim = clinical_verification_input(source, clinical, completion_scope=completion_scope)
    result = verify_source_claim(original_source, claim, reviews=reviews)
    raw = source.model_dump(mode='json') if hasattr(source, 'model_dump') else source
    return {'schema_version': ATOMIC_REVIEW_VERSION,
        'clinical_fact_id': clinical['context_fact_id'], 'source_id': raw['source_id'],
        'source_sha256': source_key(raw), 'source_text_sha256': original_source['sha256'],
        'patient_id': original_source['patient_id'], 'encounter_id': original_source['encounter_id'],
        'claim': claim, 'source_verification': result, 'independent_reviews': list(reviews),
        'clinical_expert_validation': 'NOT_ESTABLISHED',
        'boundary': 'Source support is distinct from clinical truth, material authenticity and request relevance.'}


def _shared_clinical_value(source, clinical, fact, review, source_ref):
    """Separate source entailment, requirement satisfaction and risk routing."""
    from ..evidence_bridge import verify_source_claim
    source_value, claim = clinical_verification_input(source, clinical,
        completion_scope='course' if fact.requirement == 'therapy_completed' else None)
    identity = (review.get('clinical_fact_id') == clinical['context_fact_id']
        and review.get('source_id') == source.source_id
        and review.get('source_sha256') == source_key(source.model_dump(mode='json'))
        and review.get('source_text_sha256') == source_value['sha256']
        and review.get('patient_id') == source.patient_id
        and review.get('encounter_id') == source.encounter_id
        and review.get('claim') == claim
        and isinstance(review.get('independent_reviews'), list))
    result = None
    if identity:
        try:
            result = verify_source_claim(source_value, claim, reviews=review['independent_reviews'])
            identity = digest(result) == digest(review.get('source_verification'))
        except (ValueError, TypeError, KeyError):
            identity = False
    status = result.get('status') if result and identity else None
    supported = status == 'SUPPORTED_BY_SOURCE' and fact.assertion is not None
    risk_route = result.get('risk_route', 'REVIEW_REQUIRED') if result and identity else 'REVIEW_REQUIRED'
    automatic = (supported and risk_route == 'AUTO_ACCEPT_ELIGIBLE'
                 and nonempty(result.get('calibration_id')))
    # A positive source relation is neither a clinical expert opinion nor an
    # automatic readiness certificate. The engine consumes this routing field.
    return {'value': fact.assertion if supported else None,
        'status': 'VERIFIED' if supported else 'DISPUTED' if status in {'CONTRADICTED', 'CONFLICTED'} else 'UNVERIFIED',
        'issues': [] if supported else ['clinical_source_proof_invalid' if not identity else 'clinical_source_' + str(status).lower()],
        'refs': [source_ref], 'method': 'shared_atomic_source_verifier', 'review': review,
        'source_verification': result if identity else None,
        'clinical_source_support': status or 'INSUFFICIENT_EVIDENCE',
        'clinical_expert_validation': 'NOT_ESTABLISHED', 'auto_accept_eligible': automatic,
        'risk_route': risk_route, 'readiness_review_required': supported and not automatic,
        'clinical_support_version': CLINICAL_SUPPORT_VERSION}


def event_is_available(value, as_of):
    try:
        return isinstance(value, str) and date.fromisoformat(value) <= as_of
    except ValueError:
        return False


def material_value(requirement, material, case, document_type):
    """Interpret a canonical original field; do not infer from a diagnosis/text."""
    if not isinstance(material, dict):
        return None, 'original_material_not_typed'
    if any(material.get(field) != getattr(case.request, field) for field in SCOPE):
        return None, 'original_material_request_scope_mismatch'
    if material.get('document_type') != document_type:
        return None, 'original_document_type_mismatch'
    if document_type == 'missing_document_attestation':
        valid = (material.get('absent_requirement') == requirement
            and nonempty(material.get('absence_statement'))
            and event_is_available(material.get('checked_as_of'), case.review_as_of))
        return (False, 'explicit_documented_absence') if valid else (None, 'absence_not_explicitly_documented')
    if document_type not in DOCUMENT_TYPES.get(requirement, set()):
        return None, 'document_type_cannot_establish_requirement'
    if requirement in {'investigation_required', 'therapy_required'}:
        value = material.get(requirement)
        return (value, 'explicit_request_requirement') if type(value) is bool else (None, 'request_trigger_unknown')
    if requirement == 'request_intent':
        if not nonempty(material.get('provider_id')):
            return None, 'provider_identifier_missing'
        if material.get('intent_state') in {'requested', 'ordered'}:
            return True, 'original_provider_request'
        if material.get('intent_state') == 'not_requested':
            return False, 'explicit_provider_nonrequest'
        return None, 'provider_intent_not_committed'
    if requirement == 'referral_reason':
        return (True, 'explicit_request_reason') if nonempty(material.get('clinical_reason')) else (None, 'clinical_reason_missing')
    if requirement == 'destination':
        valid = nonempty(material.get('destination_id')) and nonempty(material.get('destination_name'))
        return (True, 'explicit_referral_destination') if valid else (None, 'destination_missing')
    if requirement == 'clinical_summary':
        source = next((s for s in case.sources if s.source_id == material.get('summary_source_id')), None)
        from .evidence import available
        valid = (source is not None and isinstance(source.content, str) and nonempty(source.content)
            and material.get('summary_sha256') == source_key(source.model_dump(mode='json'))
            and material.get('document_role') == 'clinical_summary'
            and available(source.model_dump(mode='json'), case) is None)
        return (True, 'available_request_attached_summary') if valid else (None, 'actual_summary_attachment_missing_or_unavailable')
    if requirement in {'therapy_completed', 'investigation_result'}:
        if (material.get('experiencer') != 'patient' or material.get('temporality') not in {'historical', 'current'}
                or not event_is_available(material.get('event_date'), case.review_as_of)):
            return None, 'actual_patient_event_time_not_established'
        if material.get('polarity') not in {'present', 'absent'}:
            return None, 'event_assertion_uncertain'
        if requirement == 'therapy_completed' and material.get('completion_scope') != 'course':
            return None, 'whole_requested_therapy_course_not_established'
        if material.get('action_state') in {'not_completed', 'not_performed', 'not_administered'}:
            return False, 'explicit_documented_nonperformance'
        if material.get('action_state') not in {'completed', 'performed', 'administered', 'finished'}:
            return None, 'event_completion_not_established'
        if requirement == 'therapy_completed':
            valid = (nonempty(material.get('therapy_name')) and material.get('clinical_purpose') == 'therapeutic'
                and material.get('polarity') == 'present' and material.get('action_state') in {'completed', 'finished'})
            return (True, 'documented_completed_therapy') if valid else (None, 'therapeutic_event_missing')
        valid = nonempty(material.get('result_id')) and material.get('result_value') is not None and material.get('result_value') != ''
        return (True, 'documented_available_result') if valid else (None, 'actual_result_missing')
    if requirement == 'pa_form':
        body = material.get('form_content')
        valid = (all(nonempty(material.get(field)) for field in ('form_id', 'payer_id', 'provider_id'))
            and material.get('form_status') in {'completed', 'submitted'}
            and isinstance(body, dict) and all(body.get(field) == getattr(case.request, field) for field in SCOPE)
            and ('requested_service' not in body or body['requested_service'] == case.request.service_code)
            and all(field not in body or body[field] == material[field] for field in ('payer_id', 'provider_id')))
        return (True, 'actual_request_specific_form') if valid else (None, 'actual_completed_pa_form_missing')
    if requirement == 'payer_context':
        valid = all(nonempty(material.get(field)) for field in ('payer_id', 'payer_request_id'))
        return (True, 'supplied_payer_request_identifiers') if valid else (None, 'payer_request_identifiers_missing')
    return None, 'unsupported_requirement'


def _reviewed_clinical_value(case, fact, derived_facts):
    """Check identity and a retained independent source review of every qualifier."""
    from .clinical_context import prepared_context
    from .mapping import map_clinical, normalized_status
    recomputed, decisions = map_clinical(case)
    known = {f.fact_id: f for f in recomputed}
    if fact.fact_id not in known or known[fact.fact_id].model_dump(mode='json') != fact.model_dump(mode='json'):
        return None
    if derived_facts and not any(f.model_dump(mode='json') == fact.model_dump(mode='json') for f in derived_facts):
        return None
    decision = next(d for d in decisions if fact.fact_id in d.get('derived_fact_ids', []))
    clinical_id = next(item[0] for item, fid in zip(decision['clinical_checks'], decision['derived_fact_ids']) if fid == fact.fact_id)
    clinical = next(f for c in prepared_context(case) for f in c['facts'] if f['context_fact_id'] == clinical_id)
    sources = {s.source_id: s for s in case.sources}
    binding_source = sources[decision['binding']['binding_source_id']]
    records = binding_source.content.get('atomic_support_reviews', [])
    if not isinstance(records, list):
        return None
    reviews = [r for r in records if isinstance(r, dict) and r.get('clinical_fact_id') == clinical_id]
    if len(reviews) != 1:
        return None
    review = reviews[0]
    source = sources[clinical['source_id']]
    from .evidence import citation, source_dict
    ref = EvidenceRef(source_id=binding_source.source_id, field='atomic_support_reviews')
    position = next(i for i, s in enumerate(case.sources) if s.source_id == binding_source.source_id)
    source_ref = citation(ref, source_dict(binding_source, position)).model_dump(mode='json')
    if review.get('schema_version') == ATOMIC_REVIEW_VERSION:
        return _shared_clinical_value(source, clinical, fact, review, source_ref)
    qualifiers = {k: clinical[k] for k in ('category', 'concept', 'polarity', 'temporality', 'experiencer')}
    qualifiers['action_state'] = normalized_status(clinical['clinical_status'])
    if fact.requirement == 'therapy_completed':
        # Course scope is an independently source-checked qualifier, absent from
        # the legacy ClinicalFact. Do not manufacture it from "administered".
        qualifiers['completion_scope'] = 'course'
    spans = [clinical['evidence'], *clinical['supporting_evidence']]
    identity = (review.get('schema_version') == 'careflow-atomic-support-review/1'
        and review.get('source_id') == source.source_id
        and review.get('source_sha256') == source_key(source.model_dump(mode='json'))
        and review.get('source_spans') == spans and review.get('assertion') == qualifiers
        and nonempty(review.get('reviewer_id')))
    if review.get('reviewer_type') == 'advanced_ai':
        identity = identity and nonempty(review.get('model')) and review['model'] != 'gpt-6-luna' and nonempty(review.get('model_version'))
    elif review.get('reviewer_type') != 'human':
        identity = False
    if not identity or review.get('status') != 'SOURCE_GROUNDED' or review.get('reviewer_type') == 'advanced_ai':
        issue = ('advanced_ai_review_alone_not_verified_material' if identity
            and review.get('status') == 'SOURCE_GROUNDED' and review.get('reviewer_type') == 'advanced_ai'
            else 'clinical_atomic_source_review_unconfirmed')
        return {'value': None, 'status': 'DISPUTED' if review.get('status') == 'DISPUTED' else 'UNVERIFIED',
            'issues': [issue], 'refs': [source_ref], 'method': 'source_atomic_review', 'review': review}
    return {'value': fact.assertion, 'status': 'VERIFIED' if fact.assertion is not None else 'UNVERIFIED',
        'issues': [] if fact.assertion is not None else ['clinical_mapping_target_unknown'],
        'refs': [source_ref], 'method': 'source_atomic_review', 'review': review}


def verify_requirement_support(case, fact, citations, *, derived_facts=()):
    """Return confirmed assertion separately; never overwrite caller/source data."""
    check_loaded_implementation()
    from .evidence import available, citation, source_dict
    result = {'support_version': VERSION, 'status': 'UNVERIFIED', 'effective_assertion': None,
        'evidence_exists': bool(citations), 'semantic_supports_requirement': False,
        'request_scope_matches': all(getattr(fact, field) == getattr(case.request, field) for field in SCOPE),
        'document_present': None, 'issues': [], 'source_refs': [], 'source_reviews': [], 'support_method': None}
    if not result['request_scope_matches']:
        result['issues'].append('fact_request_scope_mismatch')
        return result
    sources = {s.source_id: source_dict(s, i) for i, s in enumerate(case.sources)}
    for ref in fact.evidence:
        if ref.source_id not in sources or available(sources[ref.source_id], case):
            if ref.source_id in sources and available(sources[ref.source_id], case) in {'patient_mismatch', 'encounter_mismatch'}:
                result['request_scope_matches'] = False
            result['issues'].append('evidence_source_unavailable_or_wrong_scope')
            return result
        try:
            expected = citation(ref, sources[ref.source_id]).model_dump(mode='json')
        except ValueError:
            result['issues'].append('evidence_reference_ungrounded')
            return result
        if not any(digest(c) == digest(expected) for c in citations):
            result['issues'].append('citation_differs_from_original_reference')
            return result
    clinical = _reviewed_clinical_value(case, fact, derived_facts) if case.clinical_bindings else None
    if clinical is not None:
        result.update(status=clinical['status'], effective_assertion=clinical['value'],
            semantic_supports_requirement=clinical['status'] == 'VERIFIED', document_present=True,
            issues=clinical['issues'], source_refs=clinical['refs'], source_reviews=[clinical['review']],
            support_method=clinical['method'])
        for key in ('source_verification', 'clinical_source_support', 'clinical_expert_validation',
                    'auto_accept_eligible', 'risk_route', 'readiness_review_required', 'clinical_support_version'):
            if key in clinical:
                result[key] = clinical[key]
        return result
    envelopes = []
    for ref in fact.evidence:
        source = sources[ref.source_id]
        if ref.field == 'requirement_support' and isinstance(source['content'], dict):
            try:
                envelope = RequirementEvidence.model_validate_json(json.dumps(source['content']['requirement_support']))
                envelopes.append((ref.source_id, envelope))
            except (ValueError, TypeError):
                result['issues'].append('invalid_requirement_support_envelope')
    if not envelopes:
        result['issues'].append('semantic_support_not_recorded')
        return result
    values = []
    for support_source, envelope in envelopes:
        if (any(getattr(envelope, field) != getattr(case.request, field) for field in SCOPE)
                or envelope.requirement != fact.requirement or envelope.assertion is not fact.assertion):
            if any(getattr(envelope, field) != getattr(case.request, field) for field in SCOPE):
                result['request_scope_matches'] = False
            result['issues'].append('support_envelope_scope_or_assertion_mismatch')
            continue
        if envelope.review_status != 'source_confirmed':
            if envelope.review_status == 'disputed':
                result['status'] = 'DISPUTED'
            result['issues'].append('support_review_' + envelope.review_status)
            continue
        if envelope.support_basis != 'original_structured_fields':
            result['issues'].append('text_atomic_review_requires_a_recomputed_clinical_binding')
            continue
        if fact.assertion is True and envelope.document_present is not True:
            result['issues'].append('document_presence_not_established')
            continue
        material_values = []
        for ref in envelope.source_refs:
            if ref.source_id == support_source and ref.field == 'requirement_support':
                result['issues'].append('support_reference_cannot_verify_itself')
                continue
            if ref.source_id not in sources or available(sources[ref.source_id], case):
                if ref.source_id in sources and available(sources[ref.source_id], case) in {'patient_mismatch', 'encounter_mismatch'}:
                    result['request_scope_matches'] = False
                result['issues'].append('original_material_unavailable_or_wrong_scope')
                continue
            try:
                original = citation(ref, sources[ref.source_id]).model_dump(mode='json')
            except ValueError:
                result['issues'].append('original_material_reference_ungrounded')
                continue
            result['source_refs'].append(original)
            value, reason = material_value(fact.requirement, original['raw_value'], case, envelope.document_type)
            if reason == 'original_material_request_scope_mismatch':
                result['request_scope_matches'] = False
            if fact.requirement == 'pa_form' and isinstance(original['raw_value'], dict):
                body = original['raw_value'].get('form_content')
                if isinstance(body, dict) and (any(body.get(field) != getattr(case.request, field) for field in SCOPE)
                        or 'requested_service' in body and body['requested_service'] != case.request.service_code):
                    result['request_scope_matches'] = False
            if value is None:
                result['issues'].append(reason)
            material_values.append(value)
        if material_values and all(value is fact.assertion and value is not None for value in material_values):
            values.append(fact.assertion)
            result['document_present'] = envelope.document_present
            result['support_method'] = envelope.support_basis
        else:
            result['issues'].append('original_material_does_not_confirm_assertion')
    if values and not result['issues']:
        result.update(status='VERIFIED', effective_assertion=fact.assertion, semantic_supports_requirement=True)
    result['issues'] = sorted(set(result['issues']))
    return result


def documentary_facts(case):
    """Adapt retained original envelopes into deterministic, independently checked facts."""
    facts, decisions = [], []
    for position, source in enumerate(case.sources):
        if not isinstance(source.content, dict) or 'requirement_support' not in source.content:
            continue
        try:
            envelope = RequirementEvidence.model_validate_json(json.dumps(source.content['requirement_support']))
        except (ValueError, TypeError) as exc:
            decisions.append({'source_id': source.source_id, 'status': 'UNVERIFIED', 'issues': [str(exc)]})
            continue
        value = envelope.model_dump(mode='json')
        fact = Fact(fact_id='material-' + digest([VERSION, source_key(source.model_dump(mode='json')), value])[:24],
            **{field: value[field] for field in SCOPE}, requirement=envelope.requirement,
            assertion=envelope.assertion, statement=f'Original typed {envelope.document_type} for {envelope.requirement}.',
            evidence=[EvidenceRef(source_id=source.source_id, field='requirement_support')], interpretation_origin='structured_mapping')
        from .evidence import citation, source_dict
        refs = [citation(fact.evidence[0], source_dict(source, position)).model_dump(mode='json')]
        decision = verify_requirement_support(case, fact, refs)
        decisions.append({'source_id': source.source_id, 'fact_id': fact.fact_id, **decision})
        facts.append(fact)
    return facts, decisions
