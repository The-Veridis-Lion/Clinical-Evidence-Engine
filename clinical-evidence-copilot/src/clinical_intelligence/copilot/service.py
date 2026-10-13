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
VERIFICATION_VERSION = 'copilot-source-verification/v1'
DOCUMENTATION_GAP = re.compile(r'\b(?:not (?:documented|reported)|no (?:record|documentation|evidence)|unclear (?:if|whether)|unknown (?:if|whether))\b')
NEGATED_ACTION = re.compile(r"\b(?:not|never|[a-z]+n['’]t)(?:\s+(?:actually|currently|yet|ever|been|being|previously|initially|still)){0,3}\s+(?:started|taken|taking|completed|performed|administered)\b")
COMPLETED_ACTION = re.compile(r'\b(?:completed|performed|administered|taken|took)\b')
ONGOING_ACTION = re.compile(r'\b(?:ongoing|taking|currently used|current use)\b')
DECLINED_ACTION = re.compile(r'\b(?:declined|refused|unwilling|cancelled|canceled|not proceeding)\b')
COMMITTED_PLAN = re.compile(r'\b(?:scheduled|will start|will perform|will order|plan to|planned for|now planned)\b')


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
    if projection_version in {'soap/v2','soap/v3','soap/v4',VERIFIED_PROJECTION} and f.assertion_basis in {'patient_report','documented_history','discussion'}:
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
                      else item.action_status != 'planned' if projection_version == VERIFIED_PROJECTION else False)
    if nonplan_action and f.category in ACTION_CATEGORIES and f.temporality=='planned':
        return 'A' if f.assertion_basis=='clinician_assessment' else 'O' if f.assertion_basis=='clinician_observation' else 'S'
    return 'P' if item.action_status=='planned' and f.experiencer=='patient' else section(f,projection_version)


def assertion_text(item, projection_version='soap/v1'):
    f = item.assertion
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
        configuration = verification_configuration()
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
    for item in packet.facts:
        fact = item.assertion
        proposed_action = action_status(fact, resolve_intent=True)
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
        claim_fingerprint = digest(claim)
        matched_reviews = []
        for index, review in enumerate(reviews):
            if (review.get('source_id') == source['source_id'] and
                    review.get('source_hash') == source['sha256'] and
                    review.get('claim_fingerprint') == claim_fingerprint and
                    review.get('patient_id') == source['patient_id'] and
                    review.get('encounter_id') == source['encounter_id']):
                matched_reviews.append(review)
                routed_reviews[index] = item.fact_id
        # Merely matching this envelope is not validation of the judgment. The
        # shared engine separately verifies all required dimension/citation proofs.
        result = verify_source_claim(source, claim, reviews=matched_reviews,
                                     calibrations=configuration['calibrations'])
        if result.get('engine_version') != configuration.get('engine_version'):
            raise ValueError('Frozen source verification engine version is unavailable')
        results.append({'fact_id': item.fact_id, 'proposed_claim': claim,
                        'result': result})
    return {'version': VERIFICATION_VERSION, 'source_sha256': packet.source.sha256,
            'patient_id': packet.patient_id, 'encounter_id': packet.case_id, 'assertions': results,
            'configuration': configuration,
            'action_projection_policy': {
                'version': 'copilot-source-event-projection/1',
                'required_supported_dimensions': ['concept', 'action_state'],
                'blocking_contradictions': ['category', 'experiencer', 'polarity', 'temporality',
                                            'event_time', 'action_type', 'action_state', 'completion_scope'],
                'interpretation': 'A locally supported source event can be projected while whole-fact support remains insufficient. Unknown subject/time/basis are retained for review; no clinical or whole-fact certification.'},
            'source_reviews_application': [
                {'review_id': review.get('review_id'),
                 'fact_id': routed_reviews.get(index),
                 'status': 'ROUTED_TO_SHARED_VALIDATION' if index in routed_reviews else 'UNAPPLIED_BINDING',
                 'reason': 'Exact original source/complete claim envelope matches; shared validation still applies.'
                           if index in routed_reviews else 'Original source, patient, encounter or complete claim fingerprint does not match. Original review is retained.'}
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


def validate_v5_projection(packet):
    """Integrity check for the new contract, leaving v1-v4 readers unchanged."""
    expected = shared_source_verifications(packet)
    if packet.extraction_metadata.get('evidence_verification') != expected:
        raise ValueError('Versioned source verification differs from retained source/facts')
    records = {row['fact_id']: row for row in expected['assertions']}
    for item in packet.facts:
        if item.action_status != verified_action_state(records[item.fact_id]):
            raise ValueError('Action state differs from independently source-verified projection')
        if records[item.fact_id]['result']['status'] != 'SUPPORTED_BY_SOURCE' and item.fact_id not in packet.review_required_fact_ids:
            raise ValueError('Unresolved source judgment cannot be closed by reviewer opinion')
    expected_candidates = [{'fact_id': item.fact_id,
                            'candidates': [finding.model_dump() for finding in inspect_semantics(item, resolve_intent=True)]}
                           for item in packet.facts]
    if packet.extraction_metadata.get('semantic_detector_candidates') != expected_candidates:
        raise ValueError('Lexical semantic candidates differ from retained proposals/source')
    return expected


def project(packet):
    # Recompute derived views after corrections; historical review records remain intact.
    packet.issues = [i for i in packet.issues if not i.fact_ids]
    packet.conflicts = []
    projection_version=packet.extraction_metadata.get('soap_projection_version','soap/v1')
    verification_records = {}
    if projection_version == VERIFIED_PROJECTION:
        verified = shared_source_verifications(packet)
        packet.extraction_metadata['evidence_verification'] = verified
        verification_records = {row['fact_id']: row for row in verified['assertions']}
        packet.extraction_metadata['semantic_detector_candidates'] = []
    grouped = defaultdict(list)
    for item in packet.facts:
        findings = inspect_semantics(item,resolve_intent=projection_version in {'soap/v3','soap/v4',VERIFIED_PROJECTION})
        if projection_version == VERIFIED_PROJECTION:
            packet.extraction_metadata['semantic_detector_candidates'].append({
                'fact_id': item.fact_id, 'candidates': [finding.model_dump() for finding in findings]})
            findings = []
        if projection_version in {'soap/v4', VERIFIED_PROJECTION}:
            from .action_state import inspect_action, attribute_scope_warnings, VERSION as action_version
            detector_version = packet.extraction_metadata.get('action_state_checklist',{}).get('version',action_version)
            detected = inspect_action(item, packet.source,version=detector_version)
            if projection_version == 'soap/v4':
                item.action_status = detected['action_state']
            else:
                record = verification_records[item.fact_id]
                result = record['result']
                item.action_status = verified_action_state(record)
                status = result['status']
                if status != 'SUPPORTED_BY_SOURCE' or result['risk_route'] != 'AUTO_ACCEPT_ELIGIBLE':
                    findings.append(issue('source_' + status.lower(), [item],
                        'Inspect targeted source verification: ' + '; '.join(result.get('reasons', [])),
                        'high' if status in {'CONTRADICTED', 'CONFLICTED'} else 'review'))
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
        if projection_version not in {'soap/v4', VERIFIED_PROJECTION}:
            item.action_status = action_status(item.assertion, prospective_mismatch=any(i.code == 'prospective_action_mismatch' for i in findings),resolve_intent=projection_version=='soap/v3')
        f = item.assertion
        if f.concept:
            grouped[(f.concept.casefold(), f.experiencer, f.temporality)].append(item)
    for group in grouped.values():
        if {'present', 'absent'} <= {f.assertion.polarity for f in group}:
            ids = [f.fact_id for f in group]
            packet.conflicts.append(Conflict(conflict_id='c-' + digest(ids)[:16], fact_ids=ids,
                reason='Opposing polarities in the same documented subject and time scope; no automatic winner.'))
            packet.issues.append(issue('conflicting_assertions', group, 'Do these assertions describe different events, or a real unresolved conflict?', 'high'))
    flagged = {f for i in packet.issues if i.severity != 'info' for f in i.fact_ids}
    source_blocked = {identity for identity, row in verification_records.items()
                      if row['result']['status'] != 'SUPPORTED_BY_SOURCE'}
    packet.review_required_fact_ids = [f.fact_id for f in packet.facts if
        f.fact_id in source_blocked or f.review_status in {'questioned', 'escalated'} or
        (f.fact_id in flagged and f.review_status != 'accepted')]
    # Human/AI acceptance is a recorded decision, never a clinical certification.
    packet.soap = {s: [] for s in 'SOAP'}
    for item in packet.facts:
        s = soap_section(item,projection_version)
        packet.soap[s].append(SoapAssertion(text=assertion_text(item,projection_version), fact_ids=[item.fact_id],
            evidence_ids=item.evidence_ids, review_status=item.review_status,
            requires_review=item.fact_id in packet.review_required_fact_ids))
    return packet.seal()


def build_packet(case_id, patient_id, source, extraction, *, extraction_error=None, metadata=None, projection_version=None):
    source.verify()
    projection_version = projection_version or (metadata or {}).get('soap_projection_version', 'soap/v4')
    if projection_version not in {'soap/v1','soap/v2','soap/v3','soap/v4',VERIFIED_PROJECTION}:
        raise ValueError('Unsupported SOAP projection version')
    p = Packet(case_id=case_id, patient_id=patient_id, source=source, extraction_status='valid',
               extraction_metadata={**(metadata or {}), 'soap_projection_version': projection_version})
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
    for index, raw in enumerate(extraction['facts']):
        try:
            f, spans = ground_fact(raw, source)
        except (ValueError, TypeError) as exc:
            p.rejected_facts.append({'original_index': index, 'raw_fact': raw, 'reason': str(exc)})
            continue
        item = Assertion(fact_id='f-' + digest([case_id, source.sha256, index, f.model_dump()])[:20],
            original_fact=f.model_dump(), assertion=f, evidence_ids=[e.evidence_id for e in spans])
        p.facts.append(item)
        seen = {e.evidence_id for e in p.evidence}
        for e in spans:
            if e.evidence_id not in seen:
                p.evidence.append(e)
                seen.add(e.evidence_id)
    if p.rejected_facts:
        p.extraction_status = 'partial' if p.facts else 'invalid'
        p.issues.append(issue('rejected_evidence', [], 'Some proposed facts failed validation. Inspect rejected_facts; they are excluded from SOAP.', 'high'))
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
    valid_ids = {e.evidence_id for e in p.evidence}
    if not request.evidence_ids or not set(request.evidence_ids) <= valid_ids or not set(request.evidence_ids) & set(item.evidence_ids):
        raise ValueError('Review must cite existing evidence supporting the target fact')
    before = item.assertion.model_dump()
    if request.action == 'correct':
        if request.replacement is None:
            raise ValueError('Correction requires replacement fact')
        replacement, spans = ground_fact(request.replacement, p.source)
        item.assertion = replacement
        item.evidence_ids = [e.evidence_id for e in spans]
        seen = {e.evidence_id for e in p.evidence}
        for e in spans:
            if e.evidence_id not in seen:
                p.evidence.append(e)
                seen.add(e.evidence_id)
    elif request.replacement is not None:
        raise ValueError('Only correct can replace an assertion')
    previous = next((r.review_id for r in reversed(p.reviews) if r.fact_id == item.fact_id), None)
    item.review_status = {'accept': 'accepted', 'question': 'questioned', 'correct': 'corrected', 'escalate': 'escalated'}[request.action]
    p.version += 1
    p.parent_hash = packet.content_hash
    p.created_at = now()
    p.reviews.append(ReviewRecord(**request.model_dump(), review_id='review-' + digest([packet.content_hash, request.model_dump(), p.version])[:20],
        recorded_at=p.created_at, applied_version=p.version, before=before, after=item.assertion.model_dump(), supersedes_review_id=previous))
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


def compare_packets(before, after, *, comparison_version=None):
    before.verify()
    after.verify()
    if before.patient_id != after.patient_id:
        raise ValueError('Cannot compare different patient identities')
    comparison_version = comparison_version or ('clinical-evidence-comparison/v3' if any(
        packet.extraction_metadata.get('soap_projection_version') == VERIFIED_PROJECTION
        for packet in (before, after)) else 'clinical-evidence-comparison/v2')
    if comparison_version not in {'clinical-evidence-comparison/v2', 'clinical-evidence-comparison/v3'}:
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
        if comparison_version == 'clinical-evidence-comparison/v3':
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
        changes.append(row)
    return {'schema_version': comparison_version, 'patient_id': before.patient_id,
        'before': {'case_id': before.case_id, 'version': before.version, 'hash': before.content_hash, 'encounter_time': before.source.encounter_time},
        'after': {'case_id': after.case_id, 'version': after.version, 'hash': after.content_hash, 'encounter_time': after.source.encounter_time},
        'interpretation': ('Source proof and subject/time scope are retained for both documents. Supported documentation differences '
                          'remain distinct from clinical event transitions. A later negative report does not establish cure, and '
                          'missing mention does not establish resolution. Encounter date is document metadata, not an inferred event date.'
                          if comparison_version == 'clinical-evidence-comparison/v3' else
                          'Ordered document comparison of source-linked proposals, with support explicitly unverified. '
                          'No clinical event transition is automatically confirmed. Missing mention does not establish '
                          'resolution; encounter time is source metadata, not event time.'),
        'changes': changes}


def json_state(item):
    f = item.assertion
    return str((f.polarity, f.temporality, f.clinical_status, f.assertion_basis,
                f.attributes.model_dump() if f.attributes else None, item.action_status))
