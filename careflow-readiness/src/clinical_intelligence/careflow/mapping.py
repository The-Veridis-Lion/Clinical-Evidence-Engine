"""Versioned clinical existence -> explicit request relevance -> material checks.

No clinical concept vocabulary, source-text pattern or automatic request inference.
Free-form execution states are not guessed: only documented canonical states map.
"""
from ..claims_review.prepare import digest, line_anchors
import hashlib
import json
from pathlib import Path
from .clinical_context import prepared_context
from .contracts import ClinicalBinding, EvidenceRef, Fact
from .evidence import available

_SOURCE_PATH = Path(__file__).resolve()
_LOADED_SOURCE_SHA256 = hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest()
VERSION = 'careflow-clinical-mapping/2'
# This set is used only for therapy completion, never investigation results.
COMPLETED = {'completed', 'finished'}
NOT_COMPLETED = {'not_completed', 'not_performed', 'not_administered'}
PENDING = {'planned', 'proposed', 'ordered', 'pending', 'pending_result', 'ongoing', 'unknown'}
SUPPORTED_REQUIREMENTS = {'referral_reason', 'clinical_summary', 'investigation_result', 'therapy_completed'}


def check_loaded_implementation():
    if hashlib.sha256(_SOURCE_PATH.read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
        raise ValueError('clinical_mapping_implementation_changed: restart before mapping original evidence')


def mapping_manifest(version=VERSION):
    check_loaded_implementation()
    if version not in {VERSION, 'careflow-clinical-mapping/1'}:
        raise ValueError('Unsupported clinical mapping manifest version')
    legacy = version == 'careflow-clinical-mapping/1'
    rules = [
        {'rule_id': 'CF-MAP-SCOPE', 'version': '1.0.0', 'condition': 'Original binding source, patient/request/service/code system and fact IDs match.'},
        {'rule_id': 'CF-MAP-SUBJECT', 'version': '1.0.0', 'condition': 'Patient experiencer; uncertain attribution does not establish a material.'},
        {'rule_id': 'CF-MAP-TIME', 'version': '1.0.0', 'condition': 'Known source-relative current/historical assertion; planned/unknown is insufficient.'},
        {'rule_id': 'CF-MAP-EXECUTION', 'version': '1.0.0' if legacy else '2.0.0',
         'condition': 'Canonical completed execution; procedures additionally require source-declared therapeutic purpose.' if legacy
         else 'Explicit completed/finished requested course plus independently source-confirmed course scope; procedures require therapeutic purpose.'},
        {'rule_id': 'CF-MAP-RESULT', 'version': '1.0.0', 'condition': 'Known patient result, not pending/order; negative findings still document results.'},
        {'rule_id': 'CF-MAP-SUMMARY', 'version': '1.0.0', 'condition': 'Explicitly attached clinical-summary document role and grounded patient facts.'},
        {'rule_id': 'CF-MAP-REASON', 'version': '1.0.0', 'condition': 'Positive clinical assertion explicitly bound as the reason for this service.'},
        {'rule_id': 'CF-MAP-PAPERWORK', 'version': '1.0.0', 'condition': 'Clinical evidence cannot establish provider intent, destination, PA form or payer identifiers.'},
    ]
    value = {'version': version, 'rules': rules,
             'completed_states': sorted({'completed', 'performed', 'administered', 'finished'} if legacy else COMPLETED),
             'explicit_nonperformance_states': sorted(NOT_COMPLETED), 'pending_states': sorted(PENDING),
             'temporal_boundary': 'Relative to original source context; no exact date or lookback period is inferred.'}
    if not legacy:
        value['code_sha256'] = _LOADED_SOURCE_SHA256
        value['required_completion_scope'] = 'course; checked by the versioned source-support gate'
    return {**value, 'sha256': digest(value)}


def normalized_status(value):
    return '_'.join((value or '').strip().casefold().split())


def material_assertion(fact, binding, *, source_support_policy=None):
    # Availability of the declared attachment is a documentary condition, not
    # certification of every clinical statement in that attachment. Scope,
    # exact extraction references and availability are checked by map_clinical.
    if source_support_policy in {'luna-only-source-policy/1', 'luna-only-source-policy/2', 'luna-only-source-policy/3', 'luna-only-source-policy/4', 'luna-only-source-policy/5', 'luna-only-source-policy/6', 'luna-only-source-policy/7'} and binding.requirement == 'clinical_summary':
        if binding.document_role != 'clinical_summary':
            return None, 'document_not_declared_as_request_summary'
        return True, 'available_explicitly_attached_clinical_summary'
    if fact['experiencer'] != 'patient':
        return None, 'clinical_subject_not_patient'
    if fact['attribution_confidence'] == 'uncertain':
        return None, 'clinical_attribution_uncertain'
    if fact['temporality'] not in {'historical', 'current'}:
        return None, 'clinical_time_unknown_or_planned'
    if fact['polarity'] == 'uncertain':
        return None, 'clinical_assertion_uncertain'
    status = normalized_status(fact['clinical_status'])
    structured = fact.get('structured_clinical_proposal') if source_support_policy == 'luna-only-source-policy/7' else None
    if structured and fact['category'] in {'treatment', 'procedure', 'medication'}:
        # The task's canonical field is the proposal, rather than a lossy
        # free-form clinical_status projection. Source support stays separate.
        status = structured['semantics'].get('action_state', 'unknown')
    requirement = binding.requirement
    if requirement == 'therapy_completed':
        if fact['category'] not in {'treatment', 'procedure', 'medication'}:
            return None, 'clinical_category_not_prior_therapy'
        if fact['category'] == 'procedure' and binding.clinical_purpose != 'therapeutic':
            return None, 'procedure_therapeutic_purpose_not_established'
        if status in NOT_COMPLETED:
            return False, 'explicit_documented_nonperformance'
        if fact['polarity'] != 'present' or status not in COMPLETED:
            return None, 'execution_not_explicitly_completed'
        return True, 'documented_completed_patient_therapy'
    if requirement == 'investigation_result':
        if fact['category'] not in {'laboratory_result', 'observation'} or status in (PENDING - {'unknown'} if structured else PENDING):
            return None, 'completed_investigation_result_not_established'
        if not fact['concept']:
            return None, 'result_concept_unknown'
        # Negative findings can be documented results, not missing documents.
        return True, 'source_supported_patient_result'
    if requirement == 'referral_reason':
        if fact['category'] not in {'diagnosis', 'condition', 'symptom', 'observation', 'other'} or fact['polarity'] != 'present':
            return None, 'clinical_reason_not_established'
        if not fact['concept']:
            return None, 'clinical_concept_unknown'
        return True, 'explicitly_request_bound_clinical_reason'
    if requirement == 'clinical_summary':
        if binding.document_role != 'clinical_summary':
            return None, 'document_not_declared_as_request_summary'
        return True, 'available_request_bound_summary_with_clinical_evidence'
    return None, 'clinical_evidence_cannot_establish_request_paperwork'


def map_clinical(case):
    check_loaded_implementation()
    contexts = prepared_context(case)
    clinical = {f['context_fact_id']: (f, c) for c in contexts for f in c['facts']}
    sources = {s.source_id: s for s in case.sources}
    derived, decisions = [], []
    for binding in case.clinical_bindings:
        original = binding.model_dump(mode='json')
        source = sources.get(binding.binding_source_id)
        issues = []
        scope = ('patient_id', 'request_id', 'service_code', 'code_system')
        if any(getattr(binding, field) != getattr(case.request, field) for field in scope):
            issues.append('binding_request_scope_mismatch')
        if len(binding.clinical_fact_ids) != len(set(binding.clinical_fact_ids)):
            issues.append('duplicate_clinical_fact_reference')
        try:
            declared = ClinicalBinding.model_validate_json(json.dumps(source.content.get('clinical_binding'))).model_dump(mode='json')
        except (ValueError, AttributeError, TypeError):
            declared = None
        if not source or not isinstance(source.content, dict) or declared != original:
            issues.append('binding_not_supported_by_original_scope_source')
        elif available(source.model_dump(mode='json'), case):
            issues.append('scope_source_' + available(source.model_dump(mode='json'), case))
        if binding.requirement not in SUPPORTED_REQUIREMENTS:
            issues.append('clinical_evidence_cannot_establish_request_paperwork')
        selected = [clinical.get(fid) for fid in binding.clinical_fact_ids]
        if any(item is None for item in selected):
            issues.append('clinical_fact_identity_unknown')
        values = []
        references = {}
        for item in selected:
            if item is None:
                continue
            fact, context = item
            if context['scope_status'] != 'IN_SCOPE':
                issues.append('clinical_source_' + context['exclusion_reason'])
            value, reason = material_assertion(fact, binding,
                source_support_policy=case.source_support_policy)
            values.append([fact['context_fact_id'], value, reason])
            refs = [EvidenceRef(source_id=binding.binding_source_id, field='clinical_binding')]
            text_source = sources[fact['source_id']]
            anchors = line_anchors(text_source.source_id, text_source.content)
            for span in [fact['evidence'], *fact['supporting_evidence']]:
                refs += [EvidenceRef(source_id=text_source.source_id, span_id=a['span_id']) for a in anchors
                         if a['start'] < span['end'] and a['end'] > span['start']]
            references[fact['context_fact_id']] = list({(r.source_id, r.span_id, r.field): r for r in refs}.values())
        if issues:
            decisions.append({'binding': original, 'mapping_version': VERSION, 'material_state': 'INSUFFICIENT_EVIDENCE',
                              'issues': sorted(set(issues)), 'clinical_checks': values, 'derived_fact_ids': []})
            continue
        ids = []
        for clinical_id, assertion, reason in values:
            identifier = 'mapped-' + digest([VERSION, original, clinical_id, assertion])[:24]
            derived.append(Fact(fact_id=identifier, patient_id=binding.patient_id, request_id=binding.request_id,
                service_code=binding.service_code, code_system=binding.code_system, requirement=binding.requirement,
                assertion=assertion, statement=f'{reason}; clinical fact {clinical_id}; binding {binding.binding_id}.',
                evidence=references[clinical_id], interpretation_origin='structured_mapping'))
            ids.append(identifier)
        candidate_association = source.content.get('association_version') in {
            'careflow-request-reason-association/1', 'careflow-request-clinical-target/1',
            'careflow-selected-clinical-association/1'}
        decisions.append({'binding': original, 'mapping_version': VERSION, 'issues': [],
                          'clinical_checks': values, 'derived_fact_ids': ids,
                          # Automatic relevance candidates do not turn an
                          # independently adequate formal reason into a gap.
                          # Without another proof, their unknown values remain
                          # insufficient under the ordinary five-state rule.
                          'required_target_incomplete': not candidate_association and any(value is None for _, value, _ in values)})
    return derived, decisions
