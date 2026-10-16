"""Deterministic document projection and reviewer-neutral, versioned corrections.

Local discrepancy checks are prompts to inspect evidence, never clinical adjudication.
No ontology, symptom inference, or relationship-based diagnosis generation.
"""
import re
from collections import defaultdict

from .evidence import ground_fact
from .models import Assertion, Conflict, Issue, Packet, ReviewRecord, SoapAssertion, digest, now


ACTION_CATEGORIES = {'medication', 'procedure', 'treatment'}
VERIFIED_PROJECTION = 'soap/v5'
LAYERED_PROJECTION = 'soap/v6'
PRODUCT_EVIDENCE_USAGE = 'luna-only-product/1'
SOURCE_INTERPRETATION_VERSION = 'bounded-source-grammar/5'
SOURCE_EVENT_SUPPORT_VERSION = 'explicit-source-action/1'
SOURCE_SEMANTICS_CORRECTION_VERSION = 'citation-permutation-preservation/1'
VERIFIED_PROJECTIONS = {VERIFIED_PROJECTION, LAYERED_PROJECTION}
EXTRACTED_EVENT_POLICIES = {'copilot-source-event-projection/3','copilot-source-event-projection/4'}
COURSE_ADOPTION_VERSION = 'source-checked-course-completion/1'
VERIFICATION_VERSION = 'copilot-source-verification/v1'
DOCUMENTATION_GAP = re.compile(r'\b(?:not (?:documented|reported)|no (?:record|documentation|evidence)|unclear (?:if|whether)|unknown (?:if|whether))\b')
NEGATED_ACTION = re.compile(r"\b(?:not|never|[a-z]+n['’]t)(?:\s+(?:actually|currently|yet|ever|been|being|previously|initially|still)){0,3}\s+(?:started|taken|taking|completed|performed|administered)\b")
COMPLETED_ACTION = re.compile(r'\b(?:completed|performed|administered|taken|took)\b')
ONGOING_ACTION = re.compile(r'\b(?:ongoing|taking|currently used|current use)\b')
DECLINED_ACTION = re.compile(r'\b(?:declined|refused|unwilling|cancelled|canceled|not proceeding)\b')
COMMITTED_PLAN = re.compile(r'\b(?:scheduled|will start|will perform|will order|plan to|planned for|now planned)\b')


def event_projection_policy(packet):
    if packet.extraction_metadata.get('soap_projection_version') != LAYERED_PROJECTION:
        return 'copilot-source-event-projection/1'
    stored = packet.extraction_metadata.get('evidence_verification', {}).get('action_projection_policy', {}).get('version')
    if stored is not None and stored not in {'copilot-source-event-projection/1','copilot-source-event-projection/2',*EXTRACTED_EVENT_POLICIES}:
        raise ValueError('Unsupported stored source event projection policy')
    structured=packet.extraction_metadata.get('extraction_task_version')=='clinical-structured-extraction/1'
    if stored in EXTRACTED_EVENT_POLICIES and not structured:
        raise ValueError('Extracted event consumption requires structured extraction')
    if stored=='copilot-source-event-projection/4' and packet.extraction_metadata.get('completion_scope_adoption_version')!=COURSE_ADOPTION_VERSION:
        raise ValueError('Course scope adoption requires its retained version marker')
    if stored is not None:return stored
    if structured:
        return ('copilot-source-event-projection/4' if packet.extraction_metadata.get(
            'completion_scope_adoption_version')==COURSE_ADOPTION_VERSION else 'copilot-source-event-projection/3')
    return stored or 'copilot-source-event-projection/2'


def explicit_disposition(status):
    if DECLINED_ACTION.search(status):
        return 'unknown' if COMMITTED_PLAN.search(status) else 'not_completed'
    if 'hypothetical' in status and not COMMITTED_PLAN.search(status):
        return 'discussed'
    return None


def ambiguous_action_status(status):
    if DOCUMENTATION_GAP.search(status): return True
    negative=list(NEGATED_ACTION.finditer(status))
    remainder=NEGATED_ACTION.sub(' ',status)
    return bool(negative and (COMPLETED_ACTION.search(remainder) or ONGOING_ACTION.search(remainder)))


def action_status(fact, *, prospective_mismatch=False, resolve_intent=False):
    if fact.category not in ACTION_CATEGORIES:
        return 'unknown'
    status = (fact.clinical_status or '').lower()
    if resolve_intent and explicit_disposition(status):
        return explicit_disposition(status)
    if fact.temporality == 'planned' or prospective_mismatch:
        return 'planned'
    if ambiguous_action_status(status):
        return 'unknown'
    if NEGATED_ACTION.search(status) or re.search(r'\b(?:declined|cancelled)\b',status):
        return 'not_completed'
    if re.search(r'\b(discussed|considered|asked about)\b', status):
        return 'discussed'
    if COMPLETED_ACTION.search(status):
        return 'completed'
    if ONGOING_ACTION.search(status):
        return 'ongoing'
    return 'unknown'


def issue(code, facts, question, severity='review'):
    ids = [f.fact_id for f in facts]
    return Issue(issue_id='i-' + digest([code, ids])[:16], code=code, severity=severity,
                 fact_ids=ids, evidence_ids=list(dict.fromkeys(e for f in facts for e in f.evidence_ids)), question=question)


def inspect_semantics(item, *, resolve_intent=False):
    f = item.assertion
    text = ' '.join(p.quote for p in f.provenance).lower()
    findings = []
    if f.experiencer == 'unknown' or f.attribution_confidence == 'uncertain':
        findings.append(issue('uncertain_attribution', [item], 'Who is the subject and who supplied this assertion?'))
    if f.polarity == 'uncertain' or f.temporality == 'unknown' or not f.assertion_basis or f.assertion_basis == 'unknown':
        findings.append(issue('uncertain_assertion', [item], 'Confirm the documented status, time, and assertion basis.'))
    if f.category in ACTION_CATEGORIES and ambiguous_action_status((f.clinical_status or '').lower()):
        findings.append(issue('uncertain_action_completion',[item], 'Distinguish missing documentation or mixed action times from actual execution; no completion is assumed.','high'))
    if resolve_intent and f.category in ACTION_CATEGORIES and f.temporality=='planned' and explicit_disposition((f.clinical_status or '').lower()):
        findings.append(issue('plan_disposition_mismatch',[item], 'Confirm intended treatment separately from refusal, hypothetical discussion or conflicting dispositions. Original planned temporality is retained for review.','high'))
    # Narrow, auditable mismatch prompts. Complex multi-clause passages are not adjudicated.
    concept = (f.concept or '').lower()
    if concept and f.experiencer == 'patient' and len(f.provenance) == 1:
        family = re.search(r'\b(?:my|his|her|the patient\x27s) (?:father|mother|brother|sister|son|daughter) (?:has|had) ([^.]+)', text)
        if family and concept in family.group(1):
            findings.append(issue('subject_mismatch', [item], 'The passage names a family member; verify the experiencer.', 'high'))
    if f.category in ACTION_CATEGORIES and f.temporality != 'planned' and re.search(r'\b(?:we plan|will (?:start|perform|order)|plan to|scheduled for)\b', text):
        findings.append(issue('prospective_action_mismatch', [item], 'The source contains a future action. Has this action actually happened?', 'high'))
    if f.category == 'diagnosis' and f.polarity == 'present' and re.search(r'\b(?:possible|suspected|may be|rule out)\b', (f.clinical_status or '').lower()):
        findings.append(issue('diagnosis_certainty', [item], 'The recorded qualifier is tentative; verify diagnostic certainty.', 'high'))
    if f.polarity == 'present' and f.temporality == 'current' and re.search(r'\b(?:resolved|remote history|historical only)\b', (f.clinical_status or '').lower()):
        findings.append(issue('time_mismatch', [item], 'Is this a current assertion or a resolved/historical event?', 'high'))
    return findings


def section(f, projection_version='soap/v2'):
    if f.experiencer != 'patient':
        return 'S'
    if f.temporality == 'planned':
        return 'P'
    if projection_version in {'soap/v2','soap/v3','soap/v4',*VERIFIED_PROJECTIONS} and f.assertion_basis in {'patient_report','documented_history','discussion'}:
        return 'S'
    if f.assertion_basis == 'clinician_assessment' or f.category == 'diagnosis':
        return 'A'
    if f.assertion_basis == 'clinician_observation':
        return 'O'
    return 'S'


def soap_section(item, projection_version):
    f=item.assertion
    if f.experiencer!='patient':
        return 'S'
    nonplan_action = (item.action_status in {'not_completed','discussed','unknown'} if projection_version in {'soap/v3','soap/v4'}
                      else item.action_status != 'planned' if projection_version in VERIFIED_PROJECTIONS else False)
    if nonplan_action and f.category in ACTION_CATEGORIES and f.temporality=='planned':
        return 'A' if f.assertion_basis=='clinician_assessment' else 'O' if f.assertion_basis=='clinician_observation' else 'S'
    return 'P' if item.action_status=='planned' and f.experiencer=='patient' else section(f,projection_version)


def assertion_text(item, projection_version='soap/v1', verification_record=None, presentation_version=None):
    f = item.assertion
    if projection_version == LAYERED_PROJECTION:
        record = verification_record or {}
        components = record.get('components', {})
        main = components.get('main_assertion', {}).get('status', 'INSUFFICIENT_EVIDENCE')
        claim = consumed_claim(record)
        values = [f.concept or 'Unnormalized source assertion',
                  f'polarity={f.polarity}; time={f.temporality}; subject={f.experiencer}; basis={claim.get("reporting_basis", f.assertion_basis or "unknown")}']
        if f.clinical_status:
            values.append('clinical_status_proposal=' + f.clinical_status)
        dimensions = {c['dimension']: c for c in record.get('result', {}).get('dimension_checks', [])}
        attributes = claim.get('attributes', {})
        # Metadata dictionaries may be canonically sorted by an exporter. Their
        # insertion order must not change sealed SOAP text after JSON reload.
        priority = ('severity','value','unit','duration','frequency') if record.get('semantic_proposal') else ('severity','duration','value','unit','frequency')
        ordered_keys = [k for k in priority if k in attributes] + sorted(set(attributes)-set(priority))
        if presentation_version == 'copilot-source-event-projection/1':
            retained_order = [c['dimension'].split('.',1)[1] for c in record.get('result',{}).get('dimension_checks',[])
                if c['dimension'].startswith('attributes.') and c['dimension'].split('.',1)[1] in attributes]
            # This list is preserved across canonical JSON sorting and contains
            # the original verified proposal order, unlike metadata dictionaries.
            ordered_keys = list(dict.fromkeys(retained_order)) + [k for k in ordered_keys if k not in retained_order]
        for key in ordered_keys:
            value = attributes[key]
            if value is not None:
                status = dimensions.get('attributes.' + key, {}).get('status', 'UNVERIFIED')
                values.append(f'{key}={value} [{status}]')
        for key in ('event_time', 'completion_scope'):
            if claim.get(key) is not None:
                values.append(f'{key}={claim[key]} [{dimensions.get(key, {}).get("status", "UNVERIFIED")}]')
        if f.category in ACTION_CATEGORIES:
            if record.get('semantic_proposal',{}).get('normalization_version') == 'clinical-structured-normalization/1':
                semantic=record['semantic_proposal']['semantics']
                for key in ('action_state','action_type'):
                    if key in semantic and semantic[key] is not None:
                        values.append(f'model_extracted_{key}={semantic[key]} [PROPOSAL]')
            elif record.get('semantic_application')=='APPLIED_EXPLICIT_HUMAN_CORRECTION':
                for key in ('action_state','action_type'):
                    if claim.get(key) is not None:
                        values.append(f'human_corrected_{key}={claim[key]} [HUMAN CORRECTION]')
            if presentation_version in EXTRACTED_EVENT_POLICIES:
                values.append(f'extracted_event_state={item.action_status}; source_verified_event_state={layered_action_state(record)}; event_support={components.get("event", {}).get("status", "INSUFFICIENT_EVIDENCE")}')
            else:
                values.append(f'source_event_state={item.action_status}; event_support={components.get("event", {}).get("status", "INSUFFICIENT_EVIDENCE")}')
            if components.get('event',{}).get('modality'):
                values.append('source_modality=' + components['event']['modality'] + '; no committed plan or execution asserted')
        label = 'SOURCE-SUPPORTED ASSERTION' if main == 'SUPPORTED_BY_SOURCE' else 'DRAFT · ORIGINAL PROPOSAL'
        if record.get('adoption',{}).get('not_adopted_dimensions'):
            values.append('Not adopted: '+', '.join(c['dimension'] for c in record['adoption']['not_adopted_dimensions']))
        return label + ' — ' + ' — '.join(values)
    if projection_version == VERIFIED_PROJECTION:
        # The extraction proposal is immutable. In particular, free-form status
        # is not covered by a source check of named clinical dimensions.
        parts = [f.concept or 'Unnormalized source assertion',
                 f'proposed polarity={f.polarity}; time={f.temporality}; subject={f.experiencer}; basis={f.assertion_basis or "unknown"}']
        if f.clinical_status:
            parts.append('clinical_status_proposal=' + f.clinical_status)
        if f.attributes:
            parts.extend(f'proposed {k}={v}' for k, v in f.attributes.model_dump().items() if v is not None)
        if f.category in ACTION_CATEGORIES:
            parts.append(f'proposed_action={action_status(f, resolve_intent=True)}; source_event_state={item.action_status}; whole_fact_support=see_verification')
        return 'DRAFT · ORIGINAL PROPOSAL — ' + ' — '.join(parts)
    parts = [f.concept or 'Unnormalized source assertion',
             f'{f.polarity}; {f.temporality}; subject={f.experiencer}; basis={f.assertion_basis or "unknown"}']
    if f.clinical_status:
        parts.append(f.clinical_status)
    if f.attributes:
        parts.extend(f'{k}={v}' for k, v in f.attributes.model_dump().items() if v is not None)
    if f.category in ACTION_CATEGORIES:
        parts.append(f'action={item.action_status}')
    text = ' — '.join(parts)
    return 'DRAFT · SOURCE SUPPORT UNVERIFIED — '+text if projection_version == 'soap/v4' else text


def shared_source_verifications(packet):
    """Adapt retained source/facts to the common versioned verification engine.

    Clinical expert validation and reviewer acceptance are deliberately absent
    from this adapter. A source check is an entailment decision, not a diagnosis.
    The lexical Detector is never used as the proposed Claim or as proof.
    """
    from ..evidence_bridge import verification_configuration, verify_source_claim
    previous = packet.extraction_metadata.get('evidence_verification', {})
    configuration = previous.get('configuration')
    if configuration is None:
        if packet.extraction_metadata.get('soap_projection_version') == LAYERED_PROJECTION:
            from ..evidence_bridge import verification_contextual_configuration
            configuration = verification_contextual_configuration()
            configuration['source_event_comparability_version'] = (
                'distinct-source-event-comparability/4' if packet.extraction_metadata.get(
                    'extraction_task_version') in {'clinical-event-assertions/1','clinical-structured-extraction/1'} else
                'distinct-source-event-comparability/2')
            configuration['main_assertion_scope_version'] = 'action-proposition-scope/2'
        else:
            configuration = verification_configuration()
        if packet.extraction_metadata.get('evidence_usage') == PRODUCT_EVIDENCE_USAGE:
            configuration['evidence_usage'] = PRODUCT_EVIDENCE_USAGE
            configuration['source_interpretation_version'] = packet.extraction_metadata.get(
                'source_interpretation_version', SOURCE_INTERPRETATION_VERSION)
            if packet.extraction_metadata.get('source_semantics_correction_version') is not None:
                if packet.extraction_metadata['source_semantics_correction_version'] != SOURCE_SEMANTICS_CORRECTION_VERSION:
                    raise ValueError('Unavailable source semantics correction version')
                configuration['source_semantics_correction_version'] = SOURCE_SEMANTICS_CORRECTION_VERSION
            if packet.extraction_metadata.get('source_event_support_version') is not None:
                from ..evidence_bridge import verification_event_configuration
                event_configuration = verification_event_configuration()
                if packet.extraction_metadata['source_event_support_version'] != event_configuration['event_support_version']:
                    raise ValueError('Unavailable product source event support version')
                configuration.update(event_configuration)
    if not isinstance(configuration, dict) or not isinstance(configuration.get('calibrations'), list):
        raise ValueError('Source verification requires a frozen structured configuration')
    source = dict(source_id=packet.source.document_id, text=packet.source.text,
                  sha256=packet.source.sha256, patient_id=packet.patient_id,
                  encounter_id=packet.case_id, input_kind=packet.source.input_kind)
    results = []
    reviews = packet.extraction_metadata.get('source_verification_reviews', [])
    if not isinstance(reviews, list) or any(not isinstance(review, dict) for review in reviews):
        raise ValueError('Source verification reviews must be retained structured records')
    routed_reviews = {}
    product_only = configuration.get('evidence_usage') == PRODUCT_EVIDENCE_USAGE
    interpretation_options = ({'source_interpretation_version': configuration['source_interpretation_version']}
                              if 'source_interpretation_version' in configuration else {})
    if configuration.get('event_support_version') is not None:
        from ..evidence_bridge import verification_event_configuration
        event_configuration = verification_event_configuration()
        if any(configuration.get(key) != value for key, value in event_configuration.items()):
            raise ValueError('Frozen event support implementation is unavailable')
        interpretation_options['event_support_version'] = configuration['event_support_version']
    if configuration.get('risk_scope_version') is not None:
        interpretation_options.update(risk_scope_version=configuration['risk_scope_version'],
            local_scope_calibrations=configuration.get('local_scope_calibrations', []))
    layered = packet.extraction_metadata.get('soap_projection_version') == LAYERED_PROJECTION
    layered_events = layered and event_projection_policy(packet) in {'copilot-source-event-projection/2',*EXTRACTED_EVENT_POLICIES}
    if layered:
        from .semantics import (apply_semantics, checked_records, split_verification,
                                semantic_subject_changed, citation_preservation_targets,
                                bound_human_semantic_correction)
        semantic_records = checked_records(packet)
        citation_targets = citation_preservation_targets(packet)
    from .event_assertions import checked_anchors, source_annotations
    anchors=checked_anchors(packet)
    for item in packet.facts:
        fact = item.assertion
        proposed_action = action_status(fact, resolve_intent=True)
        if layered_events and fact.category in ACTION_CATEGORIES and (fact.clinical_status or '').strip().casefold() in {'discussed','considered','hypothetical','conditional discussion'}:
            # A proposal's future topic does not make its explicitly proposed
            # discussion a committed plan. This normalizes the proposal only;
            # the independent full-source proof still decides source_event_state.
            proposed_action = 'discussed'
        # These are proposal qualifiers only. The verifier must independently
        # find them in the original source before returning support.
        status_words = set(re.findall(r'\w+', (fact.clinical_status or '').casefold()))
        completion_scope = 'course' if proposed_action == 'completed' and 'course' in status_words else None
        # ClinicalFact does not have an action_type field. Do not invent that
        # assertion from category, or infer a full course from one administration.
        action_type = 'therapy_course' if completion_scope else None
        claim = dict(claim_id=item.fact_id, source_id=packet.source.document_id,
                      patient_id=packet.patient_id, encounter_id=packet.case_id,
                      category=fact.category, concept=fact.concept,
                      spans=[dict(start=p.start, end=p.end, quote=p.quote,
                                  source_id=packet.source.document_id) for p in fact.provenance],
                      experiencer=fact.experiencer, reporting_basis=fact.assertion_basis or 'unknown',
                      polarity=fact.polarity, certainty='unknown',
                      temporality=fact.temporality, event_time=None, action_type=action_type,
                      action_state=proposed_action, completion_scope=completion_scope,
                      attributes={k: v for k, v in (fact.attributes.model_dump() if fact.attributes else {}).items() if v is not None})
        if layered:
            semantic_record = semantic_records.get(item.fact_id)
            human_semantic_active=(event_projection_policy(packet) in EXTRACTED_EVENT_POLICIES
                and bound_human_semantic_correction(packet,item,semantic_record))
            raw_changed = fact.model_dump() != item.original_fact
            changed_semantics = (semantic_subject_changed(fact, item.original_fact)
                if (configuration.get('source_semantics_correction_version') == SOURCE_SEMANTICS_CORRECTION_VERSION
                    or item.fact_id in citation_targets)
                else raw_changed)
            stale_semantics = bool(changed_semantics and semantic_record and semantic_record['origin'] in {
                'original_source_review_claim','original_versioned_extraction','original_structured_extraction','program_source_derivation/1'})
            if (event_projection_policy(packet) in EXTRACTED_EVENT_POLICIES and semantic_record
                    and semantic_record['origin'].startswith('targeted_semantics_correction/') and not human_semantic_active):
                stale_semantics=True
            claim = apply_semantics(claim, None if stale_semantics else semantic_record)
            originals = packet.extraction_metadata.get('source_review_original_claims', [])
            original = next((r for r in originals if r.get('claim_id') == item.fact_id), None)
            if original is not None:
                from ..evidence_bridge import verification_package
                core = verification_package()
                original = core.Claim.model_validate(original).model_dump(mode='json')
                if (original['source_id'] != source['source_id'] or original['patient_id'] != source['patient_id'] or
                        original['encounter_id'] != source['encounter_id'] or
                        not all(0 <= s['start'] < s['end'] <= len(source['text']) and source['text'][s['start']:s['end']]==s['quote'] for s in original['spans'])):
                    raise ValueError('Original source-review claim identity/span binding differs from retained source')
                original_fingerprint = digest(original)
                if not any(r.get('source_hash') == source['sha256'] and r.get('claim_fingerprint') == original_fingerprint and
                        r.get('source_id') == source['source_id'] and r.get('patient_id') == source['patient_id'] and
                        r.get('encounter_id') == source['encounter_id'] for r in reviews):
                    raise ValueError('Original source-review claim requires its original hash-bound review')
                if not raw_changed and semantic_record and semantic_record['origin'] == 'original_source_review_claim':
                    for key, value in claim.items():
                        if key == 'certainty':
                            continue  # Preserved original proposal, not an inferred certainty.
                        expected = original[key]
                        if key == 'polarity':
                            value = {'affirmed':'present'}.get(value,value)
                            expected = {'affirmed':'present'}.get(expected,expected)
                        if value != expected:
                            raise ValueError('Original source-review claim differs from the current typed assertion: ' + key)
                    claim = original
        claim_fingerprint = digest(claim)
        matched_reviews = []
        for index, review in enumerate(reviews):
            # Offline model opinions are retained for audit, never a product
            # entailment oracle. Human review remains an explicit user action.
            if product_only and review.get('reviewer_type') != 'human':
                continue
            if (review.get('source_id') == source['source_id'] and
                    review.get('source_hash') == source['sha256'] and
                    review.get('claim_fingerprint') == claim_fingerprint and
                    review.get('patient_id') == source['patient_id'] and
                    review.get('encounter_id') == source['encounter_id']):
                matched_reviews.append(review)
                routed_reviews[index] = item.fact_id
        # Merely matching this envelope is not validation of the judgment. The
        # shared engine separately verifies all required dimension/citation proofs.
        contextual = layered and 'contextual_calibrations' in configuration
        if contextual:
            from ..evidence_bridge import verify_contextual_source_claim
            result = verify_contextual_source_claim(source, claim, reviews=matched_reviews,
                calibrations=configuration['contextual_calibrations'],
                event_comparability_version=configuration.get('source_event_comparability_version'), **interpretation_options)
        else:
            result = verify_source_claim(source, claim, reviews=matched_reviews,
                                         calibrations=configuration['calibrations'], **interpretation_options)
        if result.get('engine_version') != configuration.get('engine_version'):
            raise ValueError('Frozen source verification engine version is unavailable')
        record = {'fact_id': item.fact_id, 'proposed_claim': claim, 'result': result}
        if layered:
            record['components'] = split_verification(record)
            if not layered_events:
                record['components']['event'].pop('modality',None)
                record['components']['event'].pop('interpretation',None)
            if contextual:
                # The main assertion is independently checked without claiming
                # uncertain attribute or execution dimensions. Full-claim review
                # fingerprints are deliberately not rebound to this subset.
                main_claim = {**claim, 'attributes':{}, 'event_time':None,
                    'action_type':None, 'action_state':'unknown','completion_scope':None}
                if (configuration.get('main_assertion_scope_version') == 'action-proposition-scope/2'
                        and fact.category in ACTION_CATEGORIES):
                    # The event type identifies the proposition: dropping it
                    # would compare prescription presence with administration
                    # absence again. Unknown attributes can still be separated.
                    main_claim['action_type'] = claim['action_type']
                main_result = verify_contextual_source_claim(source,main_claim,
                    calibrations=configuration['contextual_calibrations'],
                    event_comparability_version=configuration.get('source_event_comparability_version'), **interpretation_options)
                record['main_claim'] = main_claim
                record['main_result'] = main_result
                record['components']['main_automatic_eligible'] = main_result['risk_route'] == 'AUTO_ACCEPT_ELIGIBLE'
                if main_result['status'] == 'SUPPORTED_BY_SOURCE' and result['status'] not in {'CONTRADICTED','CONFLICTED'}:
                    from .semantics import component_result, MAIN_DIMENSIONS
                    record['components']['main_assertion'] = component_result(main_result,MAIN_DIMENSIONS)
            if item.fact_id in semantic_records:
                record['semantic_proposal'] = semantic_records[item.fact_id]
                if stale_semantics:
                    record['semantic_application'] = 'UNAPPLIED_AFTER_FACT_CORRECTION'
                elif human_semantic_active:
                    record['semantic_application'] = 'APPLIED_EXPLICIT_HUMAN_CORRECTION'
                invalid=semantic_records[item.fact_id].get('invalid_fields',[])
                if invalid and not stale_semantics:
                    record['components']['automatic_eligible']=False
                    record['components']['review_targets'].extend('mechanical_semantics.'+name for name in invalid)
        if item.fact_id in anchors:
            record.update(source_annotations(packet,item,claim,result,anchors[item.fact_id],record.get('main_result')))
        elif configuration.get('risk_scope_version') is not None or packet.extraction_metadata.get('extraction_task_version') == 'clinical-typed-default/1':
            # A cited question remains a proposal. Only independently supported
            # passages, including any necessary answer context, become proof.
            anchor = {'fact_id': item.fact_id, 'primary_source_id': None,
                      'selected_source_ids': [p.source_id for p in fact.provenance]}
            record.update(source_annotations(packet,item,claim,result,anchor,record.get('main_result')))
        if event_projection_policy(packet)=='copilot-source-event-projection/4':
            record.update(adopt_course_scope(record,packet.source.sha256))
        if event_projection_policy(packet) in EXTRACTED_EVENT_POLICIES:
            record['structured_consumption']={'version':'model-extracted-consumption/1',
                'method':'MODEL_EXTRACTED_NOT_INDEPENDENTLY_SOURCE_VERIFIED',
                'review_targets':structured_review_targets(packet,item,record),
                'source_verification_unchanged':True}
        results.append(record)
    return {'version': VERIFICATION_VERSION, 'source_sha256': packet.source.sha256,
            'patient_id': packet.patient_id, 'encounter_id': packet.case_id, 'assertions': results,
            'configuration': configuration,
            'action_projection_policy': {
                'version': event_projection_policy(packet),
                **({'action_status_semantics':'MODEL_EXTRACTED_UNCONTRADICTED_PROPOSAL',
                    'source_verification_unchanged':True} if event_projection_policy(packet) in EXTRACTED_EVENT_POLICIES else {}),
                'required_supported_dimensions': ['concept', 'action_state'],
                'blocking_contradictions': ['category', 'experiencer', 'polarity', 'temporality',
                                            'event_time', 'action_type', 'action_state', 'completion_scope'],
                'interpretation': ('An independently supported conditional discussion with matched subject/concept is retained as discussed even while clinical/time attributes require review; it never becomes committed plan or execution. '
                    if layered_events else '') + 'A locally supported source event can be projected while whole-fact support remains insufficient. Unknown subject/time/basis are retained for review; no clinical or whole-fact certification.'},
            'source_reviews_application': [
                {'review_id': review.get('review_id'),
                 'fact_id': routed_reviews.get(index),
                 'status': ('OFFLINE_EVALUATION_ONLY' if product_only and review.get('reviewer_type') != 'human'
                            else 'ROUTED_TO_SHARED_VALIDATION' if index in routed_reviews else 'UNAPPLIED_BINDING'),
                 'reason': 'Exact original source/complete claim envelope matches; shared validation still applies.'
                           if index in routed_reviews else 'Offline model review cannot determine product fact adoption.'
                           if product_only and review.get('reviewer_type') != 'human'
                           else 'Original source, patient, encounter or complete claim fingerprint does not match. Original review is retained.'}
                for index, review in enumerate(reviews)],
            'clinical_expert_validation': 'NOT_PERFORMED',
            'interpretation': 'Source support of explicit dimensions is separate from original clinical proposals, reviewer opinion and clinical expert validation.'}


def verified_action_state(record):
    """Project a supported event dimension, retaining incomplete fact verification.

    For example a quoted administration can be explicit even when the note does
    not establish whether it was observed by a clinician or reported by a patient.
    The missing reporting basis still prevents whole-fact source confirmation.
    """
    result = record['result']
    original = record['proposed_claim']
    source_assertion = result.get('source_assertion')
    if result.get('status') == 'CONFLICTED':
        return 'unknown'
    if source_assertion and any(source_assertion.get(key) != original.get(key) for key in ('source_id', 'patient_id', 'encounter_id')):
        return 'unknown'
    checks = {check['dimension']: check for check in result.get('dimension_checks', [])}
    if any(checks.get(name, {}).get('status') != 'SUPPORTED' for name in ('concept', 'action_state')):
        return 'unknown'
    blocking = {'category','experiencer','polarity','temporality','event_time',
                'action_type','action_state','completion_scope'}
    if any(check.get('status') == 'CONTRADICTED' for name, check in checks.items() if name in blocking):
        return 'unknown'
    # A properly bound independent SourceReview can establish the required
    # dimensions beyond the bounded grammar. Its opinion/method/risk stay visible.
    # Missing review proof never falls back to the unverified lexical Detector.
    if not source_assertion and result.get('status') != 'SUPPORTED_BY_SOURCE':
        return 'unknown'
    state = checks['action_state'].get('source_value', 'unknown')
    if source_assertion and state != source_assertion.get('action_state', 'unknown'):
        return 'unknown'
    return state if state in {'planned','completed','not_completed','ongoing','discussed'} else 'unknown'


def layered_action_state(record):
    """Retain a proved conditional discussion without claiming plan/execution."""
    state = verified_action_state(record)
    if state != 'unknown':
        return state
    result = record['result']
    checks = {c['dimension']:c for c in result.get('dimension_checks',[])}
    if result['status'] == 'CONFLICTED':
        return 'unknown'
    if all(checks.get(k,{}).get('status') == 'SUPPORTED' for k in ('concept','action_state','experiencer')) and checks['action_state'].get('source_value') == 'discussed':
        if not any(checks.get(k,{}).get('status') == 'CONTRADICTED' for k in ('category','concept','experiencer','polarity')):
            return 'discussed'
    return 'unknown'


def extracted_action_state(record):
    """Use a valid Luna event proposal without relabeling parser gaps as proof."""
    proposal=record.get('semantic_proposal',{})
    if ((proposal.get('origin')!='original_structured_extraction'
            and record.get('semantic_application')!='APPLIED_EXPLICIT_HUMAN_CORRECTION')
            or record.get('semantic_application')=='UNAPPLIED_AFTER_FACT_CORRECTION'):
        return 'unknown'
    result=record['result']
    if result['status']=='CONFLICTED':return 'unknown'
    blocking={'category','concept','experiencer','polarity','temporality','event_time',
        'action_type','action_state','completion_scope'}
    if any(d['dimension']=='completion_scope' for d in record.get('adoption',{}).get('not_adopted_dimensions',[])):
        # Refuting a proposed course boundary does not refute administration.
        # Policy/4 has already excluded that boundary from the adopted claim.
        blocking.discard('completion_scope')
    if any(c['status']=='CONTRADICTED' and c['dimension'] in blocking for c in result.get('dimension_checks',[])):
        return 'unknown'
    return proposal['semantics'].get('action_state','unknown')


def projected_action_state(packet, record):
    policy=event_projection_policy(packet)
    if policy in EXTRACTED_EVENT_POLICIES:return extracted_action_state(record)
    return layered_action_state(record) if policy=='copilot-source-event-projection/2' else verified_action_state(record)


def consumed_claim(record):
    """The proposed claim and independent source result remain immutable audit."""
    return record.get('adopted_claim',record.get('proposed_claim',{}))


def adopt_course_scope(record, source_sha256):
    proposal=record['proposed_claim'];adopted={**proposal};not_adopted=[]
    scope=proposal.get('completion_scope')
    if proposal.get('action_state')=='completed' and scope in {'course','full_course'}:
        check=next((c for c in record['result'].get('dimension_checks',[])
            if c['dimension']=='completion_scope'),{})
        if check.get('status')!='SUPPORTED' or check.get('source_value')!=scope:
            adopted['completion_scope']=None
            not_adopted.append({'dimension':'completion_scope','proposed_value':scope,
                'source_check_status':check.get('status','UNVERIFIED'),
                'source_value':check.get('source_value'),
                'reason':'Existing source check does not establish this course-completion scope; this is not a finding that the proposal is false.'})
    return {'adopted_claim':adopted,'adoption':{'version':COURSE_ADOPTION_VERSION,
        'source_sha256':source_sha256,'proposed_claim_fingerprint':digest(proposal),
        'adopted_claim_fingerprint':digest(adopted),'not_adopted_dimensions':not_adopted}}


def structured_review_targets(packet,item,record):
    """Extraction usability is separate from independent rule coverage."""
    targets=[];result=record['result'];fact=item.assertion
    if result['status']=='CONFLICTED':targets.append('source_conflict')
    targets.extend('source_contradiction.'+c['dimension'] for c in result.get('dimension_checks',[])
        if c['status']=='CONTRADICTED')
    contract=packet.extraction_metadata.get('structured_extraction_contract',{})
    identity=next((a for a in contract.get('assertions',[]) if a['fact_id']==item.fact_id),None)
    if identity:
        dense=next(i for i,a in enumerate(contract['assertions']) if a['fact_id']==item.fact_id)
        raw_index=contract['accepted_original_indices'][dense]
        targets.extend('mechanical.'+q['field'] for q in contract.get('field_quarantine',[])
            if q['original_fact_index']==raw_index and not (
                record.get('semantic_application')=='APPLIED_EXPLICIT_HUMAN_CORRECTION'
                and q['field'].startswith('semantics.')
                and q['field'].split('.',1)[1] in record['semantic_proposal']['semantics']))
    if fact.attribution_confidence=='uncertain' or fact.experiencer=='unknown':
        targets.append('explicit_attribution_uncertainty')
    proposal=record.get('semantic_proposal',{})
    if record.get('semantic_application')=='UNAPPLIED_AFTER_FACT_CORRECTION':
        targets.append('stale_extracted_semantics')
    semantic=proposal.get('semantics',{})
    if fact.category in ACTION_CATEGORIES and semantic.get('action_state')=='completed':
        if layered_action_state(record)!='completed':targets.append('unverified_high_risk_execution')
        if semantic.get('completion_scope') in {'course','full_course'}:
            check=next((c for c in result.get('dimension_checks',[]) if c['dimension']=='completion_scope'),{})
            if check.get('status')!='SUPPORTED':targets.append('unverified_course_completion')
    return list(dict.fromkeys(targets))


def explicit_human_acceptance(packet, item, record):
    """A user's supported-fact review is distinct from automatic eligibility.

    Historical packets retain their original supported-only workflow. Explicit
    new human workflow records can complete a parser-gap task while preserving
    every unresolved machine dimension; source conflicts are never cleared.
    """
    if packet.extraction_metadata.get('review_workflow') is not None:
        from .reviewer import human_review_completion
        return human_review_completion(packet,item,record)
    if (packet.extraction_metadata.get('evidence_usage') != PRODUCT_EVIDENCE_USAGE or
            item.review_status != 'accepted' or record['result']['status'] != 'SUPPORTED_BY_SOURCE' or
            record['result'].get('source_hash') != packet.source.sha256):
        return False
    review = next((r for r in reversed(packet.reviews) if r.fact_id == item.fact_id), None)
    return bool(review and review.action == 'accept' and review.reviewer.reviewer_type == 'human' and
        review.after == item.assertion.model_dump() and set(review.evidence_ids) <= set(item.evidence_ids) and
        review.applied_version <= packet.version)


def validate_v5_projection(packet):
    """Integrity check for the new contract, leaving v1-v4 readers unchanged."""
    from .reviewer import validate_review_workflow
    validate_review_workflow(packet)
    expected = shared_source_verifications(packet)
    if packet.extraction_metadata.get('evidence_verification') != expected:
        raise ValueError('Versioned source verification differs from retained source/facts')
    records = {row['fact_id']: row for row in expected['assertions']}
    for item in packet.facts:
        if item.action_status != verified_action_state(records[item.fact_id]):
            raise ValueError('Action state differs from independently source-verified projection')
        if (records[item.fact_id]['result']['status'] != 'SUPPORTED_BY_SOURCE'
                and not explicit_human_acceptance(packet,item,records[item.fact_id])
                and item.fact_id not in packet.review_required_fact_ids):
            raise ValueError('Unresolved source judgment cannot be closed by reviewer opinion')
    expected_candidates = [{'fact_id': item.fact_id,
                            'candidates': [finding.model_dump() for finding in inspect_semantics(item, resolve_intent=True)]}
                           for item in packet.facts]
    if packet.extraction_metadata.get('semantic_detector_candidates') != expected_candidates:
        raise ValueError('Lexical semantic candidates differ from retained proposals/source')
    return expected


def validate_v6_projection(packet):
    """Only the opt-in layered packet contract can carry new semantic proposals."""
    from .reviewer import validate_review_workflow
    validate_review_workflow(packet)
    expected = shared_source_verifications(packet)
    if packet.extraction_metadata.get('evidence_verification') != expected:
        raise ValueError('Layered source verification differs from retained source/facts')
    from .atomic import validate_checklist
    validate_checklist(packet.extraction_metadata.get('atomic_source_checklist', {}),packet)
    records = {r['fact_id']: r for r in expected['assertions']}
    for item in packet.facts:
        record = records[item.fact_id]
        state = projected_action_state(packet,record)
        if item.action_status != state:
            raise ValueError('Action state differs from layered source-verified projection')
        needs_review=(bool(record['structured_consumption']['review_targets']) if event_projection_policy(packet) in EXTRACTED_EVENT_POLICIES
            else not record['components']['automatic_eligible'])
        if (needs_review and not explicit_human_acceptance(packet,item,record)
                and item.fact_id not in packet.review_required_fact_ids):
            raise ValueError('Uncalibrated or unresolved source judgment requires targeted review')
    return expected


def project(packet):
    # Recompute derived views after corrections; historical review records remain intact.
    packet.issues = [i for i in packet.issues if not i.fact_ids]
    packet.conflicts = []
    projection_version=packet.extraction_metadata.get('soap_projection_version','soap/v1')
    verification_records = {}
    if projection_version in VERIFIED_PROJECTIONS:
        verified = shared_source_verifications(packet)
        packet.extraction_metadata['evidence_verification'] = verified
        verification_records = {row['fact_id']: row for row in verified['assertions']}
        packet.extraction_metadata['semantic_detector_candidates'] = []
    grouped = defaultdict(list)
    for item in packet.facts:
        findings = inspect_semantics(item,resolve_intent=projection_version in {'soap/v3','soap/v4',*VERIFIED_PROJECTIONS})
        if projection_version in VERIFIED_PROJECTIONS:
            packet.extraction_metadata['semantic_detector_candidates'].append({
                'fact_id': item.fact_id, 'candidates': [finding.model_dump() for finding in findings]})
            findings = []
        if projection_version in {'soap/v4', *VERIFIED_PROJECTIONS}:
            from .action_state import inspect_action, attribute_scope_warnings, VERSION as action_version
            detector_version = packet.extraction_metadata.get('action_state_checklist',{}).get('version',action_version)
            detected = inspect_action(item, packet.source,version=detector_version)
            if projection_version == 'soap/v4':
                item.action_status = detected['action_state']
            else:
                record = verification_records[item.fact_id]
                result = record['result']
                item.action_status = projected_action_state(packet,record) if projection_version == LAYERED_PROJECTION else verified_action_state(record)
                status = result['status']
                candidate=projection_version==LAYERED_PROJECTION and event_projection_policy(packet) in EXTRACTED_EVENT_POLICIES
                targets=record.get('structured_consumption',{}).get('review_targets',[])
                if (bool(targets) if candidate else status != 'SUPPORTED_BY_SOURCE' or result['risk_route'] != 'AUTO_ACCEPT_ELIGIBLE'):
                    human_accepted = explicit_human_acceptance(packet,item,record)
                    findings.append(issue('source_human_reviewed' if human_accepted else 'source_' + status.lower(), [item],
                        ('Targeted dimensions: ' + ', '.join(targets if candidate else record['components']['review_targets']) + '. '
                         if projection_version == LAYERED_PROJECTION else '') +
                        ('Human review completed; machine source support remains unchanged. '
                         if human_accepted and packet.extraction_metadata.get('review_workflow') else
                         'Inspect targeted source verification: ') + '; '.join(result.get('reasons', [])),
                        'info' if human_accepted else 'high' if status in {'CONTRADICTED', 'CONFLICTED'} else 'review'))
                if status == 'CONFLICTED':
                    packet.conflicts.append(Conflict(
                        conflict_id='source-conflict-' + digest([item.fact_id, result.get('counter_spans', [])])[:16],
                        fact_ids=[item.fact_id],
                        reason='Unresolved original source statements or independent source judgments disagree; see retained counter spans. No automatic winner.'))
            for code in (detected['warnings'] + attribute_scope_warnings(item,packet.facts) if projection_version == 'soap/v4' else []):
                if not any(finding.code == code for finding in findings):
                    findings.append(issue(code, [item], 'Source-scoped detector found unresolved action/attribute support. Inspect the exact scopes and independent evidence; the original proposal is retained.', 'high'))
            annotations = packet.extraction_metadata.get('atomic_source_checklist',{}).get('speaker_annotations', [])
            if any(a['boundary_discrepancy'] and any(p.start < a['end'] and a['start'] < p.end for p in item.assertion.provenance) for a in annotations):
                findings.append(issue('source_speaker_boundary_unverified',[item], 'Preserve the raw source label. The legacy source index assigns another turn label; speaker role and experiencer require independent review.', 'high'))
        packet.issues.extend(findings)
        if projection_version not in {'soap/v4', *VERIFIED_PROJECTIONS}:
            item.action_status = action_status(item.assertion, prospective_mismatch=any(i.code == 'prospective_action_mismatch' for i in findings),resolve_intent=projection_version=='soap/v3')
        f = item.assertion
        if f.concept:
            event_scope = None
            if packet.extraction_metadata.get('evidence_usage') == PRODUCT_EVIDENCE_USAGE:
                record = verification_records.get(item.fact_id, {})
                checks = {c['dimension']: c for c in record.get('result', {}).get('dimension_checks', [])}
                event_check = checks.get('event_time', {})
                # Different source-confirmed times describe separate events.
                # Unverified time proposals cannot conceal a real conflict.
                if event_check.get('status') == 'SUPPORTED':
                    event_scope = event_check.get('source_value')
            grouped[(f.concept.casefold(), f.experiencer, f.temporality, event_scope)].append(item)
    for group in grouped.values():
        if {'present', 'absent'} <= {f.assertion.polarity for f in group}:
            ids = [f.fact_id for f in group]
            if packet.extraction_metadata.get('evidence_usage') == PRODUCT_EVIDENCE_USAGE:
                proved = []
                for f in group:
                    checks = {c['dimension']: c for c in verification_records[f.fact_id]['result']['dimension_checks']}
                    proved.append(all(checks.get(k, {}).get('status') == 'SUPPORTED'
                                      for k in ('concept', 'experiencer', 'polarity', 'temporality')))
                if not all(proved):
                    packet.conflicts.append(Conflict(conflict_id='proposal-conflict-' + digest(ids)[:16], fact_ids=ids,
                        reason='Unresolved opposition between extracted proposals; source conflict is NOT_CONFIRMED. Incomplete program interpretations are not source counterevidence.'))
                    packet.issues.append(issue('opposing_proposals_scope_review', group,
                        'The extracted proposals have opposing polarities. Verify each complete predicate and event scope; incomplete program interpretations are not confirmed source conflict.', 'review'))
                    continue
            packet.conflicts.append(Conflict(conflict_id='c-' + digest(ids)[:16], fact_ids=ids,
                reason='Opposing polarities in the same documented subject and time scope; no automatic winner.'))
            packet.issues.append(issue('conflicting_assertions', group, 'Do these assertions describe different events, or a real unresolved conflict?', 'high'))
    flagged = {f for i in packet.issues if i.severity != 'info' for f in i.fact_ids}
    source_blocked = {identity for identity, row in verification_records.items()
                      if ((bool(row['structured_consumption']['review_targets']) if event_projection_policy(packet) in EXTRACTED_EVENT_POLICIES
                           else not row['components']['automatic_eligible']) and not explicit_human_acceptance(packet,
                          next(f for f in packet.facts if f.fact_id==identity),row) if projection_version == LAYERED_PROJECTION
                          else row['result']['status'] != 'SUPPORTED_BY_SOURCE' and not explicit_human_acceptance(packet,
                              next(f for f in packet.facts if f.fact_id==identity),row))}
    packet.review_required_fact_ids = [f.fact_id for f in packet.facts if
        f.fact_id in source_blocked or f.review_status in {'questioned', 'escalated'} or
        (f.fact_id in flagged and f.review_status != 'accepted')]
    # Human/AI acceptance is a recorded decision, never a clinical certification.
    packet.soap = {s: [] for s in 'SOAP'}
    for item in packet.facts:
        s = soap_section(item,projection_version)
        packet.soap[s].append(SoapAssertion(text=assertion_text(item,projection_version,verification_records.get(item.fact_id),event_projection_policy(packet)), fact_ids=[item.fact_id],
            evidence_ids=item.evidence_ids, review_status=item.review_status,
            requires_review=item.fact_id in packet.review_required_fact_ids))
    return packet.seal()


def build_packet(case_id, patient_id, source, extraction, *, extraction_error=None, metadata=None, projection_version=None):
    source.verify()
    projection_version = projection_version or (metadata or {}).get('soap_projection_version', 'soap/v4')
    if projection_version not in {'soap/v1','soap/v2','soap/v3','soap/v4',*VERIFIED_PROJECTIONS}:
        raise ValueError('Unsupported SOAP projection version')
    p = Packet(case_id=case_id, patient_id=patient_id, source=source, extraction_status='valid',
               extraction_metadata={**(metadata or {}), 'soap_projection_version': projection_version})
    if projection_version == LAYERED_PROJECTION and p.extraction_metadata.get('evidence_usage') != 'offline-evaluation/1':
        p.extraction_metadata.setdefault('evidence_usage', PRODUCT_EVIDENCE_USAGE)
        p.extraction_metadata.setdefault('source_interpretation_version', SOURCE_INTERPRETATION_VERSION)
        p.extraction_metadata.setdefault('coverage_alignment_version', 'copilot-source-alignment-triage/2')
    if extraction_error is not None or extraction is None:
        p.extraction_status = 'failed'
        p.issues.append(issue('extraction_failure', [], extraction_error or 'No extraction received.', 'high'))
        from .atomic import checklist
        p.extraction_metadata['atomic_source_checklist'] = checklist(p)
        return project(p)
    if extraction.get('document_id') != source.document_id:
        raise ValueError('Extraction document_id differs from source')
    if not isinstance(extraction.get('facts'), list):
        raise ValueError('Expected extraction facts list')
    accepted_indices = []
    for index, raw in enumerate(extraction['facts']):
        try:
            f, spans = ground_fact(raw, source)
        except (ValueError, TypeError) as exc:
            p.rejected_facts.append({'original_index': index, 'raw_fact': raw, 'reason': str(exc)})
            continue
        item = Assertion(fact_id='f-' + digest([case_id, source.sha256, index, f.model_dump()])[:20],
            original_fact=f.model_dump(), assertion=f, evidence_ids=[e.evidence_id for e in spans])
        p.facts.append(item)
        accepted_indices.append(index)
        seen = {e.evidence_id for e in p.evidence}
        for e in spans:
            if e.evidence_id not in seen:
                p.evidence.append(e)
                seen.add(e.evidence_id)
    if p.rejected_facts:
        p.extraction_status = 'partial' if p.facts else 'invalid'
        p.issues.append(issue('rejected_evidence', [], 'Some proposed facts failed validation. Inspect rejected_facts; they are excluded from SOAP.', 'high'))
    if extraction.get('clinical_semantics') is not None:
        if projection_version != LAYERED_PROJECTION:
            raise ValueError('New clinical semantics requires explicit soap/v6')
        from .semantics import SemanticsRecord
        proposals = extraction['clinical_semantics']
        if not isinstance(proposals,list) or len(proposals) != len(extraction['facts']):
            raise ValueError('Every input v2 fact needs an explicit semantic proposal')
        records = []
        seen_indices = set()
        accepted_by_index = dict(zip(accepted_indices, p.facts))
        for proposal in proposals:
            if (not isinstance(proposal, dict) or set(proposal) != {'fact_index','semantics'} or
                    type(proposal['fact_index']) is not int or
                    not 0 <= proposal['fact_index'] < len(extraction['facts']) or
                    proposal['fact_index'] in seen_indices):
                raise ValueError('Clinical semantics index differs from input fact or is duplicated')
            seen_indices.add(proposal['fact_index'])
            from .semantics import ClinicalSemanticsV2
            semantics = ClinicalSemanticsV2.model_validate(proposal['semantics'])
            item = accepted_by_index.get(proposal['fact_index'])
            if item is None:
                continue  # Rejected raw facts cannot donate attributes to a neighbor.
            records.append(SemanticsRecord(fact_id=item.fact_id,
                source_sha256=source.sha256,semantics=semantics,
                origin='original_versioned_extraction').model_dump(mode='json'))
        p.extraction_metadata['clinical_semantics_v2'] = records
    if extraction.get('relationship_quarantine') is not None:
        if p.extraction_metadata.get('extraction_task_version') != 'clinical-typed-default/1':
            raise ValueError('Relationship quarantine requires its versioned extraction task')
        p.extraction_metadata['relationship_quarantine'] = extraction['relationship_quarantine']
    structured=extraction.get('structured_extraction_contract')
    if structured is not None:
        from .source_adapter import STRUCTURED_TASK_VERSION
        from .semantics import StructuredSemanticsRecord
        if (projection_version!=LAYERED_PROJECTION or not isinstance(structured,dict)
                or structured.get('version')!=STRUCTURED_TASK_VERSION
                or structured.get('source_sha256')!=source.sha256
                or structured.get('normalization_version')!='clinical-structured-normalization/1'
                or len(structured.get('assertions',[]))!=len(extraction['facts'])):
            raise ValueError('Structured extraction requires its exact typed source contract')
        by_index=dict(zip(accepted_indices,p.facts));records=[];anchors=[];identities=[];seen=set()
        for proposal in structured['assertions']:
            index=proposal['fact_index']
            if type(index) is not int or index in seen or not 0<=index<len(extraction['facts']):
                raise ValueError('Invalid structured fact identity mapping')
            seen.add(index)
            if index not in by_index:continue
            item=by_index[index]
            records.append(StructuredSemanticsRecord(fact_id=item.fact_id,source_sha256=source.sha256,
                semantics=proposal['semantics'],invalid_fields=proposal['invalid_fields'],
                normalization_version=structured['normalization_version'],origin='original_structured_extraction').model_dump(mode='json'))
            anchors.append({'fact_id':item.fact_id,'primary_source_id':proposal['primary_source_id'],
                'selected_source_ids':proposal['selected_source_ids']})
            identities.append({**{k:v for k,v in proposal.items() if k!='fact_index'},'fact_id':item.fact_id})
        p.extraction_metadata['clinical_semantics_v2']=records
        p.extraction_metadata['structured_extraction_contract']={**structured,'assertions':identities}
        p.extraction_metadata['event_assertion_contract']={'version':STRUCTURED_TASK_VERSION,
            'source_sha256':source.sha256,'assertions':anchors}
        p.extraction_metadata['extraction_task_version']=STRUCTURED_TASK_VERSION
        p.extraction_metadata['completion_scope_adoption_version']=COURSE_ADOPTION_VERSION
        p.extraction_metadata['relationship_quarantine']=structured['relationship_quarantine']
        p.rejected_facts.extend(structured['rejected_facts'])
        if structured['field_quarantine'] or structured['rejected_facts'] or structured['relationship_quarantine']['items']:
            p.extraction_status='partial' if p.facts else 'invalid'
            p.issues.append(issue('structured_extraction_quarantine',[],
                'Invalid fields or relationships are retained separately; valid clinical proposals remain available.'))
    contract=extraction.get('event_assertion_contract')
    if contract is not None:
        from .source_adapter import TASK_VERSION
        if (projection_version!=LAYERED_PROJECTION or not isinstance(contract,dict) or
                set(contract)!={'version','source_sha256','assertions'} or contract['version']!=TASK_VERSION or
                contract['source_sha256']!=source.sha256 or not isinstance(contract['assertions'],list) or
                len(contract['assertions'])!=len(extraction['facts'])):
            raise ValueError('Event assertion proposals require the exact typed source contract')
        by_index=dict(zip(accepted_indices,p.facts));records=[];seen=set()
        for proposal in contract['assertions']:
            if (set(proposal)!={'fact_index','primary_source_id','selected_source_ids'} or
                    type(proposal['fact_index']) is not int or proposal['fact_index'] in seen or
                    not 0<=proposal['fact_index']<len(extraction['facts'])):
                raise ValueError('Event assertion proposal has invalid input fact identity')
            seen.add(proposal['fact_index'])
            if proposal['fact_index'] in by_index:
                records.append({'fact_id':by_index[proposal['fact_index']].fact_id,
                    'primary_source_id':proposal['primary_source_id'],'selected_source_ids':proposal['selected_source_ids']})
        p.extraction_metadata['event_assertion_contract']={**contract,'assertions':records}
        p.extraction_metadata['extraction_task_version']=TASK_VERSION
    for index, relationship in enumerate(extraction.get('relationships', [])):
        # Preserve the source proposal, but do not infer new clinical prose from it.
        p.relationships.append({'relationship_id': f'r-{index:04d}', 'original': relationship,
            'status': 'unreviewed', 'adopted_in_soap': False,
            'reason': 'Endpoint and quotation validity do not establish clinical interpretation.'})
    from .atomic import checklist
    from .action_state import inspect_action, VERSION as action_version
    supplied_atoms = p.extraction_metadata.pop('atomic_source_assertions', [])
    p.extraction_metadata['atomic_source_checklist'] = checklist(p,supplied_atoms)
    p.extraction_metadata['action_state_checklist'] = {'version': action_version,
        'assertions': [inspect_action(item,p.source) for item in p.facts],
        'interpretation': 'Lexical detector candidates are unverified; no clinical accuracy claim.'}
    return project(p)


def review_packet(packet, request):
    packet.verify()
    if request.base_version != packet.version:
        raise ValueError('Review base version is stale')
    if not request.reason.strip():
        raise ValueError('Review requires a nonblank reason')
    p = packet.model_copy(deep=True)
    item = next((f for f in p.facts if f.fact_id == request.fact_id), None)
    if item is None:
        raise ValueError('Unknown fact_id')
    if not request.evidence_ids or len(request.evidence_ids) != len(set(request.evidence_ids)):
        raise ValueError('Review must cite unique evidence for the target fact')
    before = item.assertion.model_dump()
    record_evidence_ids = list(request.evidence_ids)
    if request.action == 'correct':
        if request.replacement is None:
            raise ValueError('Correction requires replacement fact')
        replacement, spans = ground_fact(request.replacement, p.source)
        resulting_ids = [e.evidence_id for e in spans]
        if not set(request.evidence_ids) <= set(item.evidence_ids + resulting_ids):
            raise ValueError('Correction must cite evidence for the old or resulting target fact')
        item.assertion = replacement
        item.evidence_ids = resulting_ids
        # Input selections are retained separately. The resulting statement is
        # never endorsed by a stale citation merely because it existed before.
        record_evidence_ids = resulting_ids
        seen = {e.evidence_id for e in p.evidence}
        for e in spans:
            if e.evidence_id not in seen:
                p.evidence.append(e)
                seen.add(e.evidence_id)
    elif request.replacement is not None:
        raise ValueError('Only correct can replace an assertion')
    elif not set(request.evidence_ids) <= set(item.evidence_ids):
        raise ValueError('Review must cite evidence belonging to the target fact')
    previous = next((r.review_id for r in reversed(p.reviews) if r.fact_id == item.fact_id), None)
    item.review_status = {'accept': 'accepted', 'question': 'questioned', 'correct': 'corrected', 'escalate': 'escalated'}[request.action]
    p.version += 1
    p.parent_hash = packet.content_hash
    p.created_at = now()
    recorded_request = {**request.model_dump(), 'evidence_ids': record_evidence_ids}
    p.reviews.append(ReviewRecord(**recorded_request, review_id='review-' + digest([packet.content_hash, request.model_dump(), p.version])[:20],
        evidence_binding_version='review-resulting-evidence/1',
        requested_evidence_ids=list(request.evidence_ids) if request.action == 'correct' else None,
        recorded_at=p.created_at, applied_version=p.version, before=before, after=item.assertion.model_dump(), supersedes_review_id=previous))
    if (p.extraction_metadata.get('evidence_verification', {}).get('configuration', {}).get(
            'source_semantics_correction_version') != SOURCE_SEMANTICS_CORRECTION_VERSION):
        from .semantics import citation_preservation_review
        if citation_preservation_review(packet, p.reviews[-1]):
            p.reviews[-1].correction_contract_version = SOURCE_SEMANTICS_CORRECTION_VERSION
    if (request.action == 'accept' and request.reviewer.reviewer_type == 'human'
            and p.extraction_metadata.get('evidence_usage') == PRODUCT_EVIDENCE_USAGE
            and p.extraction_metadata.get('soap_projection_version') in VERIFIED_PROJECTIONS
            and 'review_workflow' not in p.extraction_metadata):
        from .reviewer import workflow_marker
        p.extraction_metadata['review_workflow'] = workflow_marker(p.reviews[-1])
    return project(p)


def comparison_source_evidence(packet, group):
    """Retain the source proof for each linked fact, without inventing a transition."""
    envelope = packet.extraction_metadata.get('evidence_verification', {})
    records = {row['fact_id']: row for row in envelope.get('assertions', [])}
    evidence = []
    for item in group:
        record = records.get(item.fact_id)
        claim = record.get('proposed_claim', {}) if record else {}
        result = record.get('result', {}) if record else {}
        bound = bool(record and envelope.get('source_sha256') == packet.source.sha256 and
            result.get('source_hash') == packet.source.sha256 and result.get('claim_id') == item.fact_id and
            result.get('claim_fingerprint') == digest(claim) and claim.get('claim_id') == item.fact_id and
            claim.get('patient_id') == packet.patient_id and claim.get('encounter_id') == packet.case_id and
            claim.get('source_id') == packet.source.document_id)
        evidence.append({'fact_id': item.fact_id, 'source_id': packet.source.document_id,
            'source_sha256': packet.source.sha256,
            'source_spans': [{'start': span.start, 'end': span.end, 'quote': span.quote,
                              'source_id': span.source_id} for span in item.assertion.provenance],
            'proof_binding': 'VALID' if bound else 'UNAVAILABLE_OR_INVALID',
            'verification': result if bound else {'status': 'UNVERIFIED', 'risk_route': 'REVIEW_REQUIRED',
                'dimension_checks': [], 'uncertainty': ['No valid retained source proof for this fact.']}})
    return evidence


def comparison_document_order(before, after):
    """Document order is explicit metadata; it never becomes a clinical event date."""
    from datetime import datetime
    if (before.case_id == after.case_id and before.source.sha256 == after.source.sha256 and
            after.version > before.version and after.parent_hash == before.content_hash):
        return 'APPEND_ONLY_SOURCE_REVISION'
    if before.source.encounter_time is None or after.source.encounter_time is None:
        return 'UNVERIFIED_DOCUMENT_ORDER'
    try:
        first = datetime.fromisoformat(before.source.encounter_time.replace('Z', '+00:00'))
        second = datetime.fromisoformat(after.source.encounter_time.replace('Z', '+00:00'))
        return 'ORDERED_SOURCE_DOCUMENTS' if first < second else 'UNVERIFIED_DOCUMENT_ORDER'
    except (ValueError, TypeError):
        return 'UNVERIFIED_DOCUMENT_ORDER'


def comparison_supported_state(group):
    # Free-text clinical_status is a retained proposal, not a verified dimension.
    # Case/fact identities and quotation wording are provenance, not state changes.
    return sorted(digest({'category': item.assertion.category,
        'concept': (item.assertion.concept or '').casefold(), 'experiencer': item.assertion.experiencer,
        'polarity': item.assertion.polarity, 'temporality': item.assertion.temporality,
        'attributes': item.assertion.attributes.model_dump() if item.assertion.attributes else None,
        'source_event_state': item.action_status}) for item in group)


def comparison_effective_proposals(packet, group):
    """Read current bound proposals, not a possibly superseded raw sidecar."""
    records = {r['fact_id']: r for r in packet.extraction_metadata.get(
        'evidence_verification', {}).get('assertions', [])}
    proofs = {p['fact_id']: p for p in comparison_source_evidence(packet, group)}
    rows = []
    for item in group:
        fact = item.assertion
        bound = proofs[item.fact_id]['proof_binding'] == 'VALID'
        proposal = consumed_claim(records[item.fact_id]) if bound else {}
        values = dict(category=fact.category, concept=(fact.concept or '').casefold(),
            experiencer=fact.experiencer, polarity=fact.polarity,
            temporality=fact.temporality, reporting_basis=proposal.get('reporting_basis', fact.assertion_basis),
            event_time=proposal.get('event_time'), action_type=proposal.get('action_type'),
            action_state=proposal.get('action_state'), completion_scope=proposal.get('completion_scope'))
        attributes = proposal.get('attributes', fact.attributes.model_dump() if fact.attributes else {})
        values.update({'attributes.' + key: attributes.get(key)
                       for key in ('severity', 'duration', 'frequency', 'value', 'unit')})
        rows.append({'fact_id': item.fact_id, 'evidence_ids': list(item.evidence_ids),
                     'proposal_binding': proofs[item.fact_id]['proof_binding'], 'values': values})
    return rows


def comparison_v4_row(row, before, after, left, right, document_order):
    """Distinguish changed documentation fields from a proved clinical transition."""
    old = comparison_effective_proposals(before, left)
    new = comparison_effective_proposals(after, right)
    equal = sorted(digest(r['values']) for r in old) == sorted(digest(r['values']) for r in new)
    change = ('newly_documented' if not left else 'not_documented_in_later' if not right else
              'unchanged_documented' if equal else 'documented_change')
    fields = sorted({key for r in old + new for key in r['values']})
    def field_values(rows, key):
        # Keep duplicate event occurrences; never collapse all same-concept facts.
        return sorted((r['values'][key] for r in rows), key=lambda value: repr(value))
    changes = [{'dimension': key, 'before': field_values(old, key), 'after': field_values(new, key)}
               for key in fields if field_values(old, key) != field_values(new, key)] if left and right else []
    source_revision = before.case_id == after.case_id and before.source.sha256 == after.source.sha256
    qualified = row['source_support_status'] == 'SUPPORTED_BY_SOURCE'
    row.update(change=change, before_effective_proposals=old, after_effective_proposals=new,
        dimension_changes=changes,
        change_kind=('SOURCE_REVISION' if source_revision else
                     'MISSING_LATER_MENTION' if not right else 'NEW_DOCUMENTATION' if not left else
                     'DOCUMENTED_ASSERTION_DIFFERENCE' if not equal else 'UNCHANGED_DOCUMENTATION'),
        clinical_event_transition=None,
        documentation_comparison_status=(
            'SOURCE_SUPPORTED_DOCUMENTATION_CHANGE' if qualified and change == 'documented_change' else
            'SOURCE_SUPPORTED_UNCHANGED_DOCUMENTATION' if qualified else
            'MISSING_DOCUMENTATION_SIDE' if not left or not right else 'UNVERIFIED_COMPARISON_SCOPE'))
    if source_revision:
        row['comparison_scope']['uncertainty'].append(
            'This is a saved correction of the same source, not a new encounter or a clinical change.')
    row['documentation_transition'] = ({
        'type': 'documented_assertion_change', 'changed_dimensions': [c['dimension'] for c in changes],
        'before_polarities': sorted({f.assertion.polarity for f in left}),
        'after_polarities': sorted({f.assertion.polarity for f in right}),
        'interpretation': 'The retained source-supported assertions differ. Event identity and clinical causation are not established.'}
        if qualified and change == 'documented_change' else None)
    return row


def compare_packets(before, after, *, comparison_version=None):
    before.verify()
    after.verify()
    if before.patient_id != after.patient_id:
        raise ValueError('Cannot compare different patient identities')
    comparison_version = comparison_version or ('clinical-evidence-comparison/v4' if any(
        packet.extraction_metadata.get('soap_projection_version') in VERIFIED_PROJECTIONS
        for packet in (before, after)) else 'clinical-evidence-comparison/v2')
    if comparison_version not in {'clinical-evidence-comparison/v2', 'clinical-evidence-comparison/v3', 'clinical-evidence-comparison/v4'}:
        raise ValueError('Unsupported document comparison version')
    document_order = comparison_document_order(before, after)
    def index(packet):
        result = defaultdict(list)
        for f in packet.facts:
            result[(f.assertion.concept or f.assertion.original_term).casefold(), f.assertion.experiencer].append(f)
        return result
    left, right = index(before), index(after)
    changes = []
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key, []), right.get(key, [])
        def state(group):
            return sorted(json_state(f) for f in group)
        change = 'newly_documented' if not a else 'not_documented_in_later' if not b else 'unchanged_documented' if state(a) == state(b) else 'documented_change'
        row = dict(concept=key[0], experiencer=key[1], change=change,
            comparison_basis='source_linked_document_proposals', source_support_status='UNVERIFIED',
            clinical_event_transition=None,
            before_fact_ids=[f.fact_id for f in a], after_fact_ids=[f.fact_id for f in b],
            before_evidence_ids=list(dict.fromkeys(e for f in a for e in f.evidence_ids)),
            after_evidence_ids=list(dict.fromkeys(e for f in b for e in f.evidence_ids)),
            before=[f.assertion.model_dump() for f in a], after=[f.assertion.model_dump() for f in b])
        if comparison_version in {'clinical-evidence-comparison/v3', 'clinical-evidence-comparison/v4'}:
            proposal_change = change
            change = ('newly_documented' if not a else 'not_documented_in_later' if not b else
                      'unchanged_documented' if comparison_supported_state(a) == comparison_supported_state(b) else 'documented_change')
            row.update(change=change, proposal_change=proposal_change)
            left_proofs, right_proofs = comparison_source_evidence(before, a), comparison_source_evidence(after, b)
            proofs = left_proofs + right_proofs
            states = {proof['verification']['status'] for proof in proofs}
            scope_reasons = []
            if not a or not b:
                scope_reasons.append('Missing mention is missing documentation, never explicit absence or resolution.')
            if key[1] != 'patient':
                scope_reasons.append('Family/other/unknown subject identity is not linked across encounters.')
            if document_order == 'UNVERIFIED_DOCUMENT_ORDER':
                scope_reasons.append('Document chronology is unknown or not increasing; no event date is inferred.')
            if any(f.assertion.temporality == 'unknown' for f in a + b):
                scope_reasons.append('Assertion time is unknown; document date does not supply the missing assertion time.')
            for proof in proofs:
                dimensions = {entry['dimension']: entry['status'] for entry in proof['verification'].get('dimension_checks', [])}
                if proof['proof_binding'] != 'VALID' or any(dimensions.get(name) != 'SUPPORTED' for name in ('experiencer', 'temporality')):
                    scope_reasons.append('Source binding, assertion subject or time scope is not independently supported.')
                    break
            qualified = bool(a and b and not scope_reasons and states == {'SUPPORTED_BY_SOURCE'})
            support_status = ('CONFLICTED' if 'CONFLICTED' in states else 'CONTRADICTED' if 'CONTRADICTED' in states else
                              'SUPPORTED_BY_SOURCE' if qualified else 'INSUFFICIENT_EVIDENCE')
            documentation_status = ('SOURCE_SUPPORTED_DOCUMENTATION_CHANGE' if qualified and change == 'documented_change' else
                                    'SOURCE_SUPPORTED_UNCHANGED_DOCUMENTATION' if qualified else
                                    'MISSING_DOCUMENTATION_SIDE' if not a or not b else 'UNVERIFIED_COMPARISON_SCOPE')
            row.update(comparison_basis='source_verified_document_assertions', source_support_status=support_status,
                before_source_evidence=left_proofs, after_source_evidence=right_proofs,
                documentation_comparison_status=documentation_status,
                comparison_scope={'patient_match': True, 'document_order': document_order,
                                  'event_dates_inferred': False, 'uncertainty': scope_reasons},
                documentation_transition={'type': 'documented_assertion_change',
                    'before_polarities': sorted({f.assertion.polarity for f in a}),
                    'after_polarities': sorted({f.assertion.polarity for f in b}),
                    'before_temporal_scopes': sorted({f.assertion.temporality for f in a}),
                    'after_temporal_scopes': sorted({f.assertion.temporality for f in b}),
                    'interpretation': 'These supported documents differ; this does not establish clinical improvement, resolution, cure, or an executed treatment.'}
                    if qualified and change == 'documented_change' else None)
        if comparison_version == 'clinical-evidence-comparison/v4':
            row = comparison_v4_row(row, before, after, a, b, document_order)
        changes.append(row)
    return {'schema_version': comparison_version, 'patient_id': before.patient_id,
        'before': {'case_id': before.case_id, 'version': before.version, 'hash': before.content_hash, 'encounter_time': before.source.encounter_time},
        'after': {'case_id': after.case_id, 'version': after.version, 'hash': after.content_hash, 'encounter_time': after.source.encounter_time},
        'interpretation': ('Source proof and subject/time scope are retained for both documents. Supported documentation differences '
                          'remain distinct from clinical event transitions. A later negative report does not establish cure, and '
                          'missing mention does not establish resolution. Encounter date is document metadata, not an inferred event date.'
                          if comparison_version in {'clinical-evidence-comparison/v3', 'clinical-evidence-comparison/v4'} else
                          'Ordered document comparison of source-linked proposals, with support explicitly unverified. '
                          'No clinical event transition is automatically confirmed. Missing mention does not establish '
                          'resolution; encounter time is source metadata, not event time.'),
        'changes': changes}


def json_state(item):
    f = item.assertion
    return str((f.polarity, f.temporality, f.clinical_status, f.assertion_basis,
                f.attributes.model_dump() if f.attributes else None, item.action_status))
