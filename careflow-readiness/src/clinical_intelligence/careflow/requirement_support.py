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
REVIEWED_CLAIM_VERSION = 'careflow-atomic-support-review/3'
CLINICAL_ASSOCIATION_VERSION = 'careflow-reviewed-clinical-association/1'
CLINICAL_SUPPORT_VERSION = 'careflow-clinical-source-support/3'
PRODUCT_SUPPORT_POLICY = 'luna-only-source-policy/7'
PRODUCT_SOURCE_INTERPRETATIONS = {
    'luna-only-source-policy/1': 'bounded-source-grammar/2',
    'luna-only-source-policy/2': 'bounded-source-grammar/4',
    'luna-only-source-policy/3': 'bounded-source-grammar/4',
    'luna-only-source-policy/4': 'bounded-source-grammar/4',
    'luna-only-source-policy/5': 'bounded-source-grammar/4',
    'luna-only-source-policy/6': 'bounded-source-grammar/5',
    'luna-only-source-policy/7': 'bounded-source-grammar/5',
}
PRODUCT_EVENT_COMPARABILITY = {
    'luna-only-source-policy/1': 'distinct-source-event-comparability/2',
    'luna-only-source-policy/2': 'distinct-source-event-comparability/2',
    'luna-only-source-policy/3': 'distinct-source-event-comparability/3',
    'luna-only-source-policy/4': 'distinct-source-event-comparability/4',
    'luna-only-source-policy/5': 'distinct-source-event-comparability/4',
    'luna-only-source-policy/6': 'distinct-source-event-comparability/4',
    'luna-only-source-policy/7': 'distinct-source-event-comparability/4',
}
INVENTORY_REVIEW_VERSION = 'careflow-negative-document-inventory/1'
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


class NegativeDocumentInventory(Contract):
    """Source-supported absence, separate from document content sufficiency.

    The complete original request header is pinned independently of text support.
    The raw note and external SourceReview are retained, never re-labelled as a
    nonexistent document or positive clinical fact. This path accepts only False.
    """
    schema_version: Literal['careflow-negative-document-inventory/1'] = INVENTORY_REVIEW_VERSION
    patient_id: Identifier
    request_id: Identifier
    service_code: Identifier
    code_system: Identifier
    request_header_sha256: Identifier
    requirement: Requirement
    assertion: Literal[False] = False
    source_id: Identifier
    source_sha256: Identifier
    claim: dict
    independent_reviews: list[dict] = Field(min_length=1)


def check_loaded_implementation():
    if hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
        raise ValueError('requirement_support_implementation_changed: restart before evaluating original materials')


def support_manifest():
    check_loaded_implementation()
    from ..evidence_bridge import verification_identity
    from .material_intake import adapter_identity
    value = {'version': VERSION, 'code_sha256': _LOADED_SOURCE_SHA256,
        'document_types': {k: sorted(v) for k, v in DOCUMENT_TYPES.items()},
        'therapy_completed': {'action_states': ['completed', 'finished'], 'completion_scope': 'course'},
        'rules': ['Exact original fields plus complete request scope.',
            'Typed material, actual form content and identifiers; a boolean is insufficient.',
            'Unknown, disputed, unavailable, planned and other-subject evidence cannot support readiness.',
            'An administered dose or performed event does not establish completion of the requested course.',
            'Historical mapped assertions retain their original source review contract.',
            'Luna-only product inputs recompute bounded source checks without external AI opinions.',
            'Available clinical-summary attachment is separate from clinical assertion correctness.'],
        'clinical_support_version': CLINICAL_SUPPORT_VERSION,
        'structured_model_support_version':'careflow-structured-model-support/2',
        'completed_course_object_contract':'careflow-completed-course-object/1',
        'model_context_evidence_bundle_version':'careflow-model-context-evidence-bundle/1',
        'received_form_adapter': adapter_identity(),
        'product_support_policy': PRODUCT_SUPPORT_POLICY,
        'product_source_interpretations': PRODUCT_SOURCE_INTERPRETATIONS,
        'product_event_comparability': PRODUCT_EVENT_COMPARABILITY,
        'semantic_evidence_binding_version': 'careflow-semantic-evidence-binding/1',
        'atomic_review_version': ATOMIC_REVIEW_VERSION,
        'reviewed_claim_version': REVIEWED_CLAIM_VERSION,
        'negative_inventory_review_version': INVENTORY_REVIEW_VERSION,
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


def negative_inventory_support(request, original_source, claim, reviews):
    """Retain a negative inventory claim and complete review, without certifying it.

    ``claim`` must be the exact Claim submitted to the independent source reviewer;
    this constructor never changes its ID, polarity, scope, spans or fingerprint.
    Put the returned object in an original structured request-association source's
    ``document_inventory_support`` field, and cite that field plus the raw note.
    The evaluator recomputes every source/review check before it affects rules.
    """
    from .contracts import Request, Source
    header_raw = request.model_dump(mode='json') if hasattr(request, 'model_dump') else request
    source_raw = original_source.model_dump(mode='json') if hasattr(original_source, 'model_dump') else original_source
    header = Request.model_validate_json(json.dumps(header_raw)).model_dump(mode='json')
    source = Source.model_validate_json(json.dumps(source_raw)).model_dump(mode='json')
    original_claim = claim.model_dump(mode='json') if hasattr(claim, 'model_dump') else claim
    return NegativeDocumentInventory.model_validate_json(json.dumps({
        **{field: header[field] for field in SCOPE}, 'request_header_sha256': digest(header),
        'requirement': original_claim['concept'], 'source_id': source['source_id'],
        'source_sha256': source_key(source), 'claim': original_claim,
        'independent_reviews': [r.model_dump(mode='json') if hasattr(r, 'model_dump') else r for r in reviews],
    })).model_dump(mode='json')


def _negative_inventory_value(case, fact, sources):
    if case.source_support_policy in PRODUCT_SOURCE_INTERPRETATIONS:
        # Retained external semantic opinions are not product input evidence.
        # Explicit structured missing-document attestations use material_value.
        return None
    if fact.assertion is not False or fact.requirement in {'investigation_required', 'therapy_required'}:
        return None
    from ..evidence_bridge import verify_source_claim
    from .evidence import available
    selected = []
    for ref in fact.evidence:
        holder = sources.get(ref.source_id)
        if ref.field != 'document_inventory_support' or holder is None or not isinstance(holder['content'], dict):
            continue
        try:
            proof = NegativeDocumentInventory.model_validate_json(json.dumps(holder['content'][ref.field]))
        except (KeyError, ValueError, TypeError):
            return {'value': None, 'status': 'UNVERIFIED', 'issues': ['negative_inventory_proof_invalid']}
        selected.append(proof)
    if len(selected) != 1:
        return None
    proof = selected[0]
    original = sources.get(proof.source_id)
    identity = (original is not None and isinstance(original['content'], str)
        and available(original, case) is None
        and proof.source_sha256 == source_key(original)
        and all(getattr(proof, f) == getattr(case.request, f) for f in SCOPE)
        and proof.request_header_sha256 == digest(case.request.model_dump(mode='json'))
        and proof.requirement == fact.requirement)
    claim = proof.claim
    # Clinical absence, no mention, no record, planned absence and document
    # inventory are different claims. Only explicit current inventory absence
    # can use this negative path; positive inventory never verifies an attachment.
    identity = identity and (claim.get('source_id') == proof.source_id
        and claim.get('patient_id') == case.request.patient_id
        and claim.get('encounter_id') == original['encounter_id']
        and claim.get('category') == 'document_inventory' and claim.get('concept') == fact.requirement
        and claim.get('polarity') == 'absent' and claim.get('temporality') == 'current'
        and claim.get('action_type') is None and claim.get('action_state') == 'unknown'
        and claim.get('completion_scope') is None)
    try:
        if not identity:
            raise ValueError('Original request/source/negative inventory identity differs')
        raw_refs = [r for r in fact.evidence if r.source_id == proof.source_id]
        from .evidence import citation
        raw_citations = [citation(r, original).model_dump(mode='json') for r in raw_refs]
        if not raw_citations or not all(any(c['start'] <= s['start'] < s['end'] <= c['end']
            and original['content'][s['start']:s['end']] == s['quote'] for c in raw_citations)
            for s in claim.get('spans', [])):
            raise ValueError('Negative inventory proof lacks original fact citations')
        source = {'source_id': proof.source_id, 'text': original['content'],
            'sha256': hashlib.sha256(original['content'].encode('utf-8')).hexdigest(),
            'patient_id': original['patient_id'], 'encounter_id': original['encounter_id'],
            'available_at': original['available_at'], 'input_kind': 'note'}
        result = verify_source_claim(source, claim, reviews=proof.independent_reviews)
    except (ValueError, TypeError, KeyError):
        return {'value': None, 'status': 'UNVERIFIED', 'issues': ['negative_inventory_identity_or_source_invalid']}
    status = result['status']
    supported = status == 'SUPPORTED_BY_SOURCE'
    return {'value': False if supported else None,
        'status': 'VERIFIED' if supported else 'DISPUTED' if status in {'CONTRADICTED', 'CONFLICTED'} else 'UNVERIFIED',
        'issues': [] if supported else ['negative_inventory_' + status.lower()],
        'source_verification': result, 'source_review': proof.model_dump(mode='json'),
        'support_method': INVENTORY_REVIEW_VERSION, 'clinical_expert_validation': 'NOT_ESTABLISHED',
        'risk_route': result['risk_route'], 'auto_accept_eligible': False,
        'inventory_absence_supported': supported, 'document_content_satisfaction': False}


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def clinical_verification_input(source, clinical, *, completion_scope=None, semantics=None):
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
    if semantics is not None:
        # The source-hash/index validator has already checked this typed/2
        # sidecar. These remain Luna proposals; independent source proof below
        # decides support and course/requirement satisfaction separately.
        claim['attributes'] = {key: value for key, value in claim['attributes'].items() if key != 'duration'}
        for key in ('duration', 'frequency'):
            if semantics.get(key) is not None:
                claim['attributes'][key] = semantics[key]
        for key in ('event_time', 'action_type', 'action_state', 'completion_scope'):
            if key in semantics:
                value = semantics[key]
                claim[key] = None if key == 'completion_scope' and value == 'unknown' else value
        claim['reporting_basis'] = semantics.get('assertion_basis', claim['reporting_basis'])
    return source_value, claim


def reviewed_clinical_association(source, clinical, reviewed_claim):
    """Relate a clinical projection to an immutable independently reviewed Claim.

    A reviewed Claim can express event time/action/course qualifiers missing from
    the old ClinicalFact schema. Those qualifiers stay on that exact Claim; no
    SourceReview fingerprint, original fact or span is edited to make it fit.
    Only explicit representation aliases are accepted, not medical synonyms.
    """
    from ..evidence_bridge import verification_package
    core = verification_package()
    original_claim = reviewed_claim.model_dump(mode='json') if hasattr(reviewed_claim, 'model_dump') else json.loads(json.dumps(reviewed_claim))
    claim = core.Claim.model_validate(original_claim).model_dump(mode='json')
    raw_source = source.model_dump(mode='json') if hasattr(source, 'model_dump') else source
    raw = clinical.model_dump(mode='json') if hasattr(clinical, 'model_dump') else clinical
    original_source, projection = clinical_verification_input(raw_source, raw)
    issues = []
    for field in ('source_id', 'patient_id', 'encounter_id'):
        if claim[field] != original_source[field]:
            issues.append('reviewed_claim_' + field + '_mismatch')

    def canonical(field, value):
        if field == 'polarity':
            return {'present': 'affirmed', 'positive': 'affirmed', 'negative': 'absent'}.get(value, value)
        if field == 'reporting_basis':
            return {'patient_reported': 'patient_report'}.get(value, value)
        if field == 'concept' and isinstance(value, str):
            return ' '.join(value.casefold().split())
        return value

    for field in ('category', 'concept', 'experiencer', 'polarity', 'temporality'):
        if canonical(field, claim[field]) != canonical(field, projection[field]):
            issues.append('reviewed_claim_' + field + '_differs_from_clinical_projection')
    for field in ('reporting_basis', 'action_state'):
        proposed = projection[field]
        if proposed not in {None, '', 'unknown', 'unspecified', 'uncertain'} and canonical(field, claim[field]) != canonical(field, proposed):
            issues.append('reviewed_claim_' + field + '_differs_from_clinical_projection')
    for field, value in projection['attributes'].items():
        if field not in claim['attributes'] or claim['attributes'][field] != value:
            issues.append('reviewed_claim_attribute_' + field + '_differs_from_clinical_projection')
    original_text = raw_source['content']
    clinical_spans = projection['spans']
    reviewed_spans = claim['spans']
    exact = all(0 <= span['start'] < span['end'] <= len(original_text)
        and original_text[span['start']:span['end']] == span['quote']
        and span.get('source_id') in {None, raw_source['source_id']} for span in reviewed_spans)
    # A clinical quote can be broader than the exact atomic supporting span, but
    # cannot point to a different source unit or silently discard a disjoint quote.
    same_units = (all(any(c['start'] <= span['start'] < span['end'] <= c['end'] for c in clinical_spans)
                      for span in reviewed_spans)
        and all(any(c['start'] < span['end'] and c['end'] > span['start'] for span in reviewed_spans)
                for c in clinical_spans))
    if not exact or not same_units:
        issues.append('reviewed_claim_spans_not_bound_to_clinical_projection')
    return {'version': CLINICAL_ASSOCIATION_VERSION, 'matched': not issues, 'issues': sorted(issues),
        'clinical_fact_id': raw['context_fact_id'], 'clinical_projection': projection,
        'clinical_projection_sha256': digest(raw), 'original_reviewed_claim': original_claim,
        'reviewed_claim_fingerprint': core.Claim.model_validate(claim).fingerprint(),
        'preserved_additional_dimensions': {key: claim[key] for key in ('event_time', 'action_type', 'completion_scope', 'certainty')},
        'boundary': 'Projection association only; source support and requirement satisfaction are computed independently.'}


def _verify_retained_reviewed_claim(source, claim, reviews, contract=None):
    """Explicitly opt in to the versioned contextual verifier for new proof3.

    Legacy proof2 uses its original verifier. A saved proof cannot silently switch
    verification contracts after upgrade; an unavailable retained contract fails.
    """
    from .. import evidence_bridge
    contextual = getattr(evidence_bridge, 'verify_contextual_source_claim', None)
    if contract is None:
        contract = 'contextual-source-configuration/2' if contextual is not None else 'evidence-verifier/1'
    if contract == 'contextual-source-configuration/2':
        if contextual is None:
            raise ValueError('Retained contextual source verifier is unavailable')
        result = contextual(source, claim, reviews=reviews)
    elif contract == 'evidence-verifier/1':
        result = evidence_bridge.verify_source_claim(source, claim, reviews=reviews)
    else:
        raise ValueError('Unknown retained reviewed-claim verification contract')
    return result, contract


def _reviewed_claim_configuration(contract):
    from .. import evidence_bridge
    if contract == 'contextual-source-configuration/2':
        return evidence_bridge.verification_contextual_configuration()
    if contract == 'evidence-verifier/1':
        return evidence_bridge.verification_configuration()
    raise ValueError('Unknown reviewed-claim configuration')


def atomic_support_review(source, clinical, *, requirement, reviews=(), reviewed_claim=None):
    """Retain an independently computed source result, not a reviewer stamp.

    The shared verifier is recomputed on consumption. Caller-supplied status,
    confidence, source locations or a model name cannot authenticate this proof.
    """
    from ..evidence_bridge import verify_source_claim
    completion_scope = 'course' if requirement == 'therapy_completed' else None
    original_source, claim = clinical_verification_input(source, clinical, completion_scope=completion_scope)
    association = None
    if reviewed_claim is not None:
        association = reviewed_clinical_association(source, clinical, reviewed_claim)
        if not association['matched']:
            raise ValueError('Independent reviewed Claim cannot be reassigned: ' + ', '.join(association['issues']))
        claim = association['original_reviewed_claim']
    contract = None
    if association is not None:
        result, contract = _verify_retained_reviewed_claim(original_source, claim, reviews)
    else:
        result = verify_source_claim(original_source, claim, reviews=reviews)
    raw = source.model_dump(mode='json') if hasattr(source, 'model_dump') else source
    value = {'schema_version': REVIEWED_CLAIM_VERSION if association is not None else ATOMIC_REVIEW_VERSION,
        'clinical_fact_id': clinical['context_fact_id'], 'source_id': raw['source_id'],
        'source_sha256': source_key(raw), 'source_text_sha256': original_source['sha256'],
        'patient_id': original_source['patient_id'], 'encounter_id': original_source['encounter_id'],
        'claim': claim, 'source_verification': result, 'independent_reviews': list(reviews),
        'clinical_expert_validation': 'NOT_ESTABLISHED',
        'boundary': 'Source support is distinct from clinical truth, material authenticity and request relevance.'}
    if association is not None:
        value.update(original_reviewed_claim=claim, clinical_association=association,
                     clinical_projection_sha256=association['clinical_projection_sha256'],
                     source_verification_contract=contract,
                     source_verification_configuration=_reviewed_claim_configuration(contract))
    return value


def _shared_clinical_value(source, clinical, fact, review, source_ref):
    """Separate source entailment, requirement satisfaction and risk routing."""
    from ..evidence_bridge import verify_source_claim
    source_value, claim = clinical_verification_input(source, clinical,
        completion_scope='course' if fact.requirement == 'therapy_completed' else None)
    association = None
    if review.get('schema_version') == REVIEWED_CLAIM_VERSION:
        try:
            association = reviewed_clinical_association(source, clinical, review['original_reviewed_claim'])
            claim = association['original_reviewed_claim']
        except (ValueError, TypeError, KeyError):
            association = {'matched': False, 'issues': ['reviewed_claim_association_invalid']}
    identity = (review.get('clinical_fact_id') == clinical['context_fact_id']
        and review.get('source_id') == source.source_id
        and review.get('source_sha256') == source_key(source.model_dump(mode='json'))
        and review.get('source_text_sha256') == source_value['sha256']
        and review.get('patient_id') == source.patient_id
        and review.get('encounter_id') == source.encounter_id
        and review.get('claim') == claim
        and isinstance(review.get('independent_reviews'), list))
    if association is not None:
        try:
            current_configuration = _reviewed_claim_configuration(review.get('source_verification_contract'))
        except (ValueError, AttributeError):
            current_configuration = None
        identity = (identity and association['matched'] and review.get('clinical_association') == association
                    and review.get('clinical_projection_sha256') == association['clinical_projection_sha256']
                    and current_configuration is not None
                    and review.get('source_verification_configuration') == current_configuration)
    result = None
    if identity:
        try:
            if association is not None:
                result, _ = _verify_retained_reviewed_claim(source_value, claim,
                    review['independent_reviews'], review.get('source_verification_contract'))
            else:
                result = verify_source_claim(source_value, claim, reviews=review['independent_reviews'])
            identity = digest(result) == digest(review.get('source_verification'))
        except (ValueError, TypeError, KeyError):
            identity = False
    status = result.get('status') if result and identity else None
    requirement_issues = []
    if (identity and association is not None and fact.requirement == 'therapy_completed' and fact.assertion is True
            and (claim.get('completion_scope') not in {'course', 'full_course'}
                 or claim.get('action_state') not in {'completed', 'finished'})):
        requirement_issues.append('reviewed_source_does_not_establish_completed_course')
    supported = status == 'SUPPORTED_BY_SOURCE' and fact.assertion is not None and not requirement_issues
    risk_route = result.get('risk_route', 'REVIEW_REQUIRED') if result and identity else 'REVIEW_REQUIRED'
    automatic = (supported and risk_route == 'AUTO_ACCEPT_ELIGIBLE'
                 and nonempty(result.get('calibration_id')))
    # A positive source relation is neither a clinical expert opinion nor an
    # automatic readiness certificate. The engine consumes this routing field.
    return {'value': fact.assertion if supported else None,
        'status': 'VERIFIED' if supported else 'DISPUTED' if status in {'CONTRADICTED', 'CONFLICTED'} else 'UNVERIFIED',
        'issues': [] if supported else requirement_issues or ['clinical_source_proof_invalid' if not identity else 'clinical_source_' + str(status).lower()],
        'refs': [source_ref], 'method': 'shared_atomic_source_verifier', 'review': review,
        'source_verification': result if identity else None,
        'clinical_source_support': status or 'INSUFFICIENT_EVIDENCE',
        'clinical_expert_validation': 'NOT_ESTABLISHED', 'auto_accept_eligible': automatic,
        'risk_route': risk_route, 'readiness_review_required': supported and not automatic,
        'clinical_support_version': CLINICAL_SUPPORT_VERSION,
        **({'clinical_association': association, 'requirement_qualifier_issues': requirement_issues}
           if association is not None else {})}


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
    source = sources[clinical['source_id']]
    if case.source_support_policy in PRODUCT_SOURCE_INTERPRETATIONS:
        return _product_clinical_value(case, fact, clinical, source, binding_source)
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
    if review.get('schema_version') in {ATOMIC_REVIEW_VERSION, REVIEWED_CLAIM_VERSION}:
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


def _structured_model_support(clinical, source, fact, source_check):
    """Use the new task's grounded proposal with an honest model evidence type.

    Mechanical reconstruction is checked in ClinicalContext. A legacy typed/2
    sidecar alone never enters here. No caller boolean or model confidence is a
    source check. Unknown parser coverage cannot discard an extracted assertion.
    """
    proposal = clinical['structured_clinical_proposal']
    anchor = proposal['anchor']
    primary_id = anchor.get('primary_source_id')
    spans = [item for item in clinical.get('provenance', []) if item['source_id'] == primary_id]
    issues = []
    if len(spans) != 1 or proposal['source_sha256'] != hashlib.sha256(source.content.encode('utf-8')).hexdigest():
        issues.append('structured_primary_support_not_established')
    required_dimensions = {'concept','experiencer','polarity'}
    if fact.requirement == 'therapy_completed':
        required_dimensions.update({'action_type','action_state','completion_scope'})
    contrary_dimensions = [row['dimension'] for row in source_check.get('dimension_checks', [])
        if row['status'] == 'CONTRADICTED' and row['dimension'] in required_dimensions]
    if source_check['status'] == 'CONFLICTED' or contrary_dimensions:
        issues.append('source_counterevidence_' + source_check['status'].lower())
    if fact.assertion is None:
        issues.append('clinical_mapping_target_unknown')
    semantics = proposal['semantics']
    completion = None
    if fact.requirement == 'therapy_completed' and fact.assertion is True:
        event = source_check.get('source_assertion') or {}
        dimensions = {row['dimension']:row['status'] for row in source_check.get('dimension_checks', [])}
        # These are object/representation checks over an already located source
        # event, not another reading of the note. A model may name the treatment
        # in action_type; that is acceptable only for the same source-established
        # object and an independently explicit whole-course completion event.
        norm = lambda value:' '.join((value or '').casefold().split())
        action_representation = ('source_action_type' if dimensions.get('action_type')=='SUPPORTED' else
            'same_treatment_object' if norm(semantics.get('action_type'))==norm(clinical.get('concept'))
            and norm(clinical.get('concept')) else 'unresolved')
        same_primary_event = bool(spans) and any(
            original['start'] < selected['end'] and original['end'] > selected['start']
            for original in event.get('spans', []) for selected in spans)
        course_equivalent = (semantics.get('completion_scope') in {'course','full_course'}
            and event.get('completion_scope') in {'course','full_course'})
        if (semantics.get('action_state') != 'completed'
                or not course_equivalent or action_representation=='unresolved' or not same_primary_event
                or not clinical.get('concept')
                or event.get('action_state') not in {'completed','finished'}
                or any(dimensions.get(key) != 'SUPPORTED' for key in
                    ('concept','experiencer','polarity','action_state'))):
            issues.append('requested_therapy_completed_course_object_not_source_established')
        completion = {'concept':clinical['concept'], 'category':clinical['category'],
            'action_type':semantics.get('action_type'), 'action_state':semantics.get('action_state'),
            'completion_scope':semantics.get('completion_scope'), 'primary_support':spans,
            'source_event':event,'course_object_contract':'careflow-completed-course-object/1',
            'same_primary_source_event':same_primary_event,'whole_course_scope_equivalent':course_equivalent,
            'action_representation':action_representation}
    retained = [{**{k:span[k] for k in ('start','end','quote')}, 'source_id':source.source_id,
        'source_text_sha256':proposal['source_sha256'],
        'source_provenance_sha256':source_key(source.model_dump(mode='json'))} for span in spans]
    context_bundle = [{**{k:span[k] for k in ('start','end','quote')},'source_id':source.source_id,
        'original_source_unit_id':span['source_id'],'source_text_sha256':proposal['source_sha256'],
        'source_provenance_sha256':source_key(source.model_dump(mode='json'))}
        for span in clinical.get('provenance', [])]
    return {'version':'careflow-structured-model-support/2', 'supported':not issues,
        'method':'model_extracted', 'independently_source_verified':False,
        'task_version':proposal['task_version'], 'source_sha256':proposal['source_sha256'],
        'raw_response_sha256':proposal['raw_response_sha256'], 'wire_fact_id':anchor['wire_fact_id'],
        'issues':issues,'supporting_spans':retained, 'completion_object':completion,
        'evidence_bundle':{'version':'careflow-model-context-evidence-bundle/1',
            'primary_source_unit_id':primary_id,'primary_spans':retained,'context_spans':context_bundle,
            'interpretation':'Joint model-selected context, including question/answer units. Individual passages are not independently asserted to support the claim.'},
        'required_counterevidence_dimensions':contrary_dimensions,
        'quarantined_typed_fields':proposal['invalid_fields'],
        'boundary':'Source-located Luna extraction consumed by documentation rules; not deterministic entailment or clinical expert certification.'}


def _product_clinical_value(case, fact, clinical, source, binding_source):
    """Consume the original Luna proposal; external assessments are audit only.

    This does not invoke a model. Finite calibrated source grammars may support
    simple assertions. An incomplete parser supplies uncertainty, never a new
    clinical answer or a substitute approval. Document availability is checked
    independently of clinical truth under the existing project checklist.
    """
    from ..evidence_bridge import verify_contextual_source_claim
    from .evidence import citation, source_dict
    source_value, claim = clinical_verification_input(source, clinical,
        semantics=(clinical.get('structured_clinical_proposal') or {}).get('semantics')
            if case.source_support_policy == 'luna-only-source-policy/7' else
            clinical.get('clinical_semantics_v2') if case.source_support_policy == 'luna-only-source-policy/5' else None)
    interpretation = PRODUCT_SOURCE_INTERPRETATIONS[case.source_support_policy]
    local_options = ({'risk_scope_version': 'source-local-proof/1'}
                     if case.source_support_policy == 'luna-only-source-policy/5' else {})
    verification = verify_contextual_source_claim(source_value, claim, reviews=(),
        source_interpretation_version=interpretation,
        event_comparability_version=PRODUCT_EVENT_COMPARABILITY[case.source_support_policy], **local_options)
    main = verification
    # Duration/severity are optional for the current clinical-reason checklist.
    # The original values and their uncertain dimensions stay on the full result.
    if fact.requirement == 'referral_reason' and claim['attributes']:
        main = verify_contextual_source_claim(source_value, {**claim, 'attributes': {}}, reviews=(),
            source_interpretation_version=interpretation,
            event_comparability_version=PRODUCT_EVENT_COMPARABILITY[case.source_support_policy], **local_options)
    status = main['status']
    extracted = None
    if case.source_support_policy == 'luna-only-source-policy/7' and clinical.get('structured_clinical_proposal'):
        extracted = _structured_model_support(clinical, source, fact, main)
    pos = next(i for i, item in enumerate(case.sources) if item.source_id == binding_source.source_id)
    ref = citation(EvidenceRef(source_id=binding_source.source_id, field='clinical_binding'),
        source_dict(binding_source, pos)).model_dump(mode='json')
    documentary = fact.requirement == 'clinical_summary' and fact.assertion is True
    requirement_issues = []
    if fact.requirement == 'therapy_completed' and fact.assertion is True and status == 'SUPPORTED_BY_SOURCE':
        event = main.get('source_assertion') or {}
        if (event.get('completion_scope') not in {'course', 'full_course'}
                or event.get('action_state') not in {'completed', 'finished'}):
            requirement_issues.append('requested_therapy_course_scope_not_established')
    if extracted is not None:
        requirement_issues = extracted['issues']
    supported = documentary or status == 'SUPPORTED_BY_SOURCE' and fact.assertion is not None and not requirement_issues
    if extracted is not None and not documentary:
        supported = extracted['supported']
    risk = main['risk_route']
    automatic = supported and (documentary or risk == 'AUTO_ACCEPT_ELIGIBLE' and nonempty(main.get('calibration_id')))
    if extracted is not None:
        automatic = supported
    preferred = []
    for span in main.get('supporting_spans', []) if main['status'] == 'SUPPORTED_BY_SOURCE' else []:
        if (0 <= span['start'] < span['end'] <= len(source.content)
                and source.content[span['start']:span['end']] == span['quote']
                and span.get('source_id') in {None, source.source_id}):
            preferred.append({**span, 'source_id': source.source_id,
                'source_text_sha256': source_value['sha256'],
                'source_provenance_sha256': source_key(source.model_dump(mode='json'))})
    if extracted is not None and extracted['supported']:
        preferred = extracted['supporting_spans']
    primary = clinical['evidence']
    primary_status = ('SUPPORTED_BY_SOURCE' if any(primary['start'] == s['start']
        and primary['end'] == s['end'] for s in preferred) else
        'CONTAINS_SOURCE_SUPPORT' if any(primary['start'] <= s['start'] < s['end'] <= primary['end']
        for s in preferred) else 'NOT_ESTABLISHED_AS_SUPPORTING_SPAN')
    if extracted is not None and extracted['supported']:
        primary_status = ('MODEL_SELECTED_SUPPORT' if any(primary['start']==s['start'] and primary['end']==s['end']
            for s in preferred) else 'CONTAINS_MODEL_SELECTED_SUPPORT')
    # Actual rule evidence is bound to verified supporting spans, rather than
    # merely displaying a preferred passage while retaining an unrelated first
    # extraction quote as its proof. Original selections remain immutable.
    from ..claims_review.prepare import line_anchors
    source_position = next(i for i, item in enumerate(case.sources) if item.source_id == source.source_id)
    source_dict_value = source_dict(source, source_position)
    semantic_refs = []
    semantic_citations = []
    consumed_spans = (extracted['evidence_bundle']['context_spans']
        if extracted is not None and extracted['supported'] else preferred)
    for anchor in line_anchors(source.source_id, source.content):
        if not any(anchor['start'] < span['end'] and anchor['end'] > span['start'] for span in consumed_spans):
            continue
        selected = EvidenceRef(source_id=source.source_id, span_id=anchor['span_id'])
        semantic_refs.append(selected.model_dump(mode='json'))
        semantic_citations.append(citation(selected, source_dict_value).model_dump(mode='json'))
    record = {'schema_version': 'careflow-product-source-check/1',
        'source_support_policy': case.source_support_policy, 'original_luna_proposal': claim,
        'source_verification': verification, 'main_assertion_verification': main,
        'external_review_consumed': False, 'product_model_calls': 0,
        'retained_offline_review_count': (len(binding_source.content['atomic_support_reviews'])
            if isinstance(binding_source.content.get('atomic_support_reviews'), list) else 0),
        'boundary': 'Program source checks and declared documentary scope; no external AI approval or clinical expert certification.'}
    if extracted is not None:
        record['model_extraction_support'] = extracted
    # A contradictory fact does not disprove that its source document exists.
    # It remains visible as a clinical review issue rather than a false gap.
    issues = ([] if supported else requirement_issues or (
        ['clinical_mapping_target_unknown'] if fact.assertion is None else ['clinical_source_' + status.lower()]))
    return {'value': fact.assertion if supported else None,
        'status': 'MODEL_EXTRACTED' if supported and extracted is not None and not documentary else
            'VERIFIED' if supported else 'DISPUTED' if status == 'CONFLICTED' else 'UNVERIFIED',
        'issues': issues, 'refs': [ref, *semantic_citations], 'method': case.source_support_policy, 'review': record,
        'source_verification': verification, 'clinical_source_support': status,
        'clinical_expert_validation': 'NOT_ESTABLISHED', 'auto_accept_eligible': automatic,
        'risk_route': 'MODEL_EXTRACTED' if supported and extracted is not None and not documentary else
            'AUTO_ACCEPT_ELIGIBLE' if documentary else risk,
        'readiness_review_required': supported and not automatic,
        'clinical_support_version': CLINICAL_SUPPORT_VERSION,
        'document_content_satisfaction': documentary,
        'preferred_source_evidence': preferred, 'primary_evidence_semantic_status': primary_status,
        'semantic_support_refs': semantic_refs, 'semantic_evidence_binding_version': 'careflow-semantic-evidence-binding/1',
        **({'clinical_evidence_method':'model_extracted', 'independent_source_verification':False,
            'model_extraction_support':extracted,'semantic_evidence_bundle':extracted['evidence_bundle']}
            if extracted is not None else {}),
        'clinical_review_dimensions': [d['dimension'] for d in verification['dimension_checks']
            if d['status'] in {'UNVERIFIED', 'CONTRADICTED'}]}


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
    inventory = _negative_inventory_value(case, fact, sources)
    if inventory is not None:
        result.update(status=inventory['status'], effective_assertion=inventory['value'],
            semantic_supports_requirement=inventory['status'] == 'VERIFIED',
            document_present=False if inventory['value'] is False else None,
            issues=inventory['issues'], source_refs=citations,
            source_reviews=[inventory['source_review']] if 'source_review' in inventory else [],
            support_method=inventory.get('support_method'))
        for key in ('source_verification', 'clinical_expert_validation', 'risk_route',
                    'auto_accept_eligible', 'inventory_absence_supported', 'document_content_satisfaction'):
            if key in inventory:
                result[key] = inventory[key]
        return result
    clinical = _reviewed_clinical_value(case, fact, derived_facts) if case.clinical_bindings else None
    if clinical is not None:
        result.update(status=clinical['status'], effective_assertion=clinical['value'],
            semantic_supports_requirement=clinical['status'] in {'VERIFIED','MODEL_EXTRACTED'}, document_present=True,
            issues=clinical['issues'], source_refs=clinical['refs'], source_reviews=[clinical['review']],
            support_method=clinical['method'])
        for key in ('source_verification', 'clinical_source_support', 'clinical_expert_validation',
                    'auto_accept_eligible', 'risk_route', 'readiness_review_required', 'clinical_support_version',
                    'clinical_association', 'requirement_qualifier_issues',
                    'document_content_satisfaction', 'clinical_review_dimensions',
                    'preferred_source_evidence', 'primary_evidence_semantic_status',
                    'semantic_support_refs', 'semantic_evidence_binding_version'):
            if key in clinical:
                result[key] = clinical[key]
        for key in ('clinical_evidence_method','independent_source_verification','model_extraction_support','semantic_evidence_bundle'):
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
        # The ordinary form adapter retains an original text, not a caller's
        # truth vote. Reconstruct its fields before trusting a derived object.
        holder = sources[support_source]
        if holder['content'].get('adapter_version') == 'careflow-received-form/1':
            from .material_intake import ReceivedMaterial, received_material_sources
            try:
                raw_document = holder['content']['original_document']
                original = sources[raw_document['source_id']]
                if available(original, case) or not isinstance(original['content'], str):
                    raise ValueError('Original received form is unavailable')
                document = ReceivedMaterial.model_validate_json(json.dumps({
                    'document_id': original['source_id'], 'document_type': envelope.document_type,
                    'received_at': original['available_at'], 'text': original['content']}))
                rebuilt = next(s for s in received_material_sources(document, case.request) if s.source_id == support_source)
                if rebuilt.content != holder['content'] or rebuilt.patient_id != holder['patient_id']:
                    raise ValueError('Received form fields differ from original text')
                result['document_present'] = True
                if rebuilt.content['unparsed_document_lines']:
                    result['issues'].append('received_form_contains_unparsed_content')
                    result['unparsed_document_lines'] = rebuilt.content['unparsed_document_lines']
                    continue
                from ..claims_review.prepare import line_anchors
                for anchor in line_anchors(original['source_id'], original['content']):
                    if any(anchor['start'] == field['start'] and anchor['end'] == field['end']
                           for field in holder['content']['original_field_evidence'].values()):
                        result['source_refs'].append(citation(EvidenceRef(source_id=original['source_id'],
                            span_id=anchor['span_id']), original).model_dump(mode='json'))
            except (ValueError, TypeError, KeyError, StopIteration):
                result['issues'].append('received_form_fields_not_bound_to_original_text')
                continue
        if (any(getattr(envelope, field) != getattr(case.request, field) for field in SCOPE)
                or envelope.requirement != fact.requirement or envelope.assertion is not fact.assertion):
            if any(getattr(envelope, field) != getattr(case.request, field) for field in SCOPE):
                result['request_scope_matches'] = False
            result['issues'].append('support_envelope_scope_or_assertion_mismatch')
            continue
        if envelope.review_status != 'source_confirmed':
            if case.source_support_policy in {'luna-only-source-policy/3', 'luna-only-source-policy/4', 'luna-only-source-policy/5', 'luna-only-source-policy/6', 'luna-only-source-policy/7'}:
                # A retained opinion is neither counterevidence nor a missing
                # document. Evaluate the original fields before deciding truth.
                # Unknown original material stays unverified below; adequate
                # positive/negative material retains its independently checked
                # value, while the opinion remains available for targeted review.
                result.setdefault('reviewer_opinions', []).append({
                    'source_id': support_source, 'review_status': envelope.review_status,
                    'reviewer_id': envelope.reviewer_id, 'reviewer_type': envelope.reviewer_type,
                    'effect_on_source_truth': 'NONE',
                    'question': 'Review the stated documentary concern against the original material; the flag alone is not counterevidence.'})
            else:
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
        if not isinstance(source.content, dict):
            continue
        if 'document_inventory_support' in source.content:
            try:
                inventory = NegativeDocumentInventory.model_validate_json(json.dumps(source.content['document_inventory_support']))
                original = next(s for s in case.sources if s.source_id == inventory.source_id)
                from ..claims_review.prepare import line_anchors
                if not isinstance(original.content, str):
                    raise ValueError('Negative inventory requires original note text')
                spans = inventory.claim.get('spans', [])
                refs = [EvidenceRef(source_id=source.source_id, field='document_inventory_support')]
                refs += [EvidenceRef(source_id=original.source_id, span_id=a['span_id'])
                    for a in line_anchors(original.source_id, original.content)
                    if any(a['start'] < span['end'] and a['end'] > span['start'] for span in spans)]
                fact = Fact(fact_id='inventory-' + digest([INVENTORY_REVIEW_VERSION,
                    source_key(source.model_dump(mode='json')), inventory.model_dump(mode='json')])[:24],
                    **{field: getattr(inventory, field) for field in SCOPE}, requirement=inventory.requirement,
                    assertion=False, statement='Retained independent negative document inventory source judgment.',
                    evidence=refs, interpretation_origin='advanced_ai')
            except (ValueError, TypeError, KeyError, StopIteration) as exc:
                decisions.append({'source_id': source.source_id, 'status': 'UNVERIFIED', 'issues': [str(exc)]})
                continue
            from .evidence import citation, source_dict
            sources = {s.source_id: source_dict(s, i) for i, s in enumerate(case.sources)}
            citations = [citation(r, sources[r.source_id]).model_dump(mode='json') for r in fact.evidence]
            decision = verify_requirement_support(case, fact, citations)
            decisions.append({'source_id': source.source_id, 'fact_id': fact.fact_id, **decision})
            facts.append(fact)
            continue
        if 'requirement_support' not in source.content:
            continue
        try:
            envelope = RequirementEvidence.model_validate_json(json.dumps(source.content['requirement_support']))
        except (ValueError, TypeError) as exc:
            decisions.append({'source_id': source.source_id, 'status': 'UNVERIFIED', 'issues': [str(exc)]})
            continue
        value = envelope.model_dump(mode='json')
        amendment = {}
        # Preserve an original, explicitly scoped correction association during
        # raw material intake. Authority is NOT accepted here: prepare/reconcile
        # still checks its exact original field, availability and target scope.
        # Omitting this association previously turned two adequate correction
        # documents into an unexplained contradictory pair.
        if 'amends_fact_id' in source.content:
            if not nonempty(source.content['amends_fact_id']):
                decisions.append({'source_id': source.source_id, 'status': 'UNVERIFIED',
                                  'issues': ['original_amendment_target_invalid']})
                continue
            amendment = {'amends_fact_id': source.content['amends_fact_id'],
                         'authority_ref': EvidenceRef(source_id=source.source_id,
                                                      field='amendment_authority_confirmed')}
        fact = Fact(fact_id='material-' + digest([VERSION, source_key(source.model_dump(mode='json')), value])[:24],
            **{field: value[field] for field in SCOPE}, requirement=envelope.requirement,
            assertion=envelope.assertion, statement=f'Original typed {envelope.document_type} for {envelope.requirement}.',
            evidence=[EvidenceRef(source_id=source.source_id, field='requirement_support')],
            interpretation_origin='structured_mapping', **amendment)
        from .evidence import citation, source_dict
        refs = [citation(fact.evidence[0], source_dict(source, position)).model_dump(mode='json')]
        decision = verify_requirement_support(case, fact, refs)
        decisions.append({'source_id': source.source_id, 'fact_id': fact.fact_id, **decision})
        facts.append(fact)
    return facts, decisions


def prepare_material_update(current_case, basis_packet, sources, *, review=None, intake=None):
    """Adapt original partial materials using an explicit persisted-case basis.

    Standalone ``build_case`` correctly rejects an amendment whose old fact is
    absent. An update is a different operation: resolve targets against the saved
    case, validate the complete resulting Case, and return only new sources/facts.
    The service still owns the transaction and optimistic revision check. There
    is no flag to trust proposed booleans or override source verification.
    """
    from .contracts import Case, EvidenceUpdate, Source
    raw_case = current_case.model_dump(mode='json') if hasattr(current_case, 'model_dump') else current_case
    case = Case.model_validate_json(json.dumps(raw_case))
    raw_case = case.model_dump(mode='json')
    if (basis_packet.get('case_id') != case.case_id
            or basis_packet.get('input_sha256') != digest(raw_case)
            or basis_packet.get('packet_sha256') != digest({k: v for k, v in basis_packet.items() if k != 'packet_sha256'})):
        raise ValueError('Original material update must reference the exact persisted case/packet basis')
    new_sources = [Source.model_validate_json(json.dumps(s.model_dump(mode='json') if hasattr(s, 'model_dump') else s)) for s in sources]
    new_ids = {s.source_id for s in new_sources}
    if not new_sources or len(new_ids) != len(new_sources) or new_ids & {s.source_id for s in case.sources}:
        raise ValueError('Original material update requires new unique source identities')
    augmented = {**raw_case, 'sources': [*raw_case['sources'], *[s.model_dump(mode='json') for s in new_sources]]}
    # Existing targets remain present here; candidates are not misrepresented as
    # a new standalone request. Their authority/scope is evaluated after mapping.
    complete_basis = Case.model_validate_json(json.dumps(augmented))
    candidates, decisions = documentary_facts(complete_basis)
    new_facts = [fact for fact in candidates if any(ref.source_id in new_ids for ref in fact.evidence)]
    if any(any(ref.source_id not in new_ids for ref in fact.evidence) for fact in new_facts):
        raise ValueError('Material-update assertions require genuinely new source evidence; use clinical bindings for retained clinical sources')
    augmented['facts'] = [*raw_case['facts'], *[f.model_dump(mode='json') for f in new_facts]]
    Case.model_validate_json(json.dumps(augmented))
    value = {'expected_revision': basis_packet['revision'], 'sources': [s.model_dump(mode='json') for s in new_sources],
             'facts': [f.model_dump(mode='json') for f in new_facts]}
    if review is not None:
        value['review'] = review.model_dump(mode='json') if hasattr(review, 'model_dump') else review
    if intake is not None:
        value['intake'] = intake.model_dump(mode='json') if hasattr(intake, 'model_dump') else intake
    update = EvidenceUpdate.model_validate_json(json.dumps(value))
    receipt = {'schema_version': 'careflow-material-update-intake/1', 'case_id': case.case_id,
        'basis_revision': basis_packet['revision'], 'basis_packet_sha256': basis_packet['packet_sha256'],
        'existing_target_resolution': 'explicit_persisted_case', 'new_source_count': len(new_sources),
        'new_fact_count': len(new_facts), 'material_decisions': [d for d in decisions if d.get('source_id') in new_ids],
        'new_model_calls': 0, 'boundary': 'Original partial-material adaptation; no reviewer opinion, caller boolean or gold label becomes verification.'}
    return update, receipt
