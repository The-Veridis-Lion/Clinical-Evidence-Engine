"""Source-grounded omission correction creates a new immutable packet version."""
from .evidence import ground_fact
from .models import Assertion, OmissionCorrectionRequest, ReviewRecord, digest, now
from .service import project
from ..evidence_bridge import verification_package, verify_source_claim


def candidates(packet):
    return packet.extraction_metadata.get('atomic_source_checklist', {}).get(
        'automatic_source_coverage', {}).get('verified_omission_candidates', [])


def candidate_fact_identity(packet, candidate, assertion, spans):
    """Bind an omission's semantic identity and complete source scope at every boundary."""
    atom = candidate['assertion']
    fields = {'category':atom['category'], 'concept':atom['concept'],
              'polarity':{'affirmed':'present'}.get(atom['polarity'],atom['polarity']),
              'experiencer':atom['experiencer'], 'temporality':atom['temporality']}
    if any(str(getattr(assertion,k)).casefold() != str(v).casefold() for k,v in fields.items()):
        raise ValueError('Correction differs from the independently enumerated source assertion')
    if [(s.start,s.end,s.quote) for s in spans] != [
            (s['start'],s['end'],s['quote']) for s in atom['spans']]:
        raise ValueError('Correction must retain the complete candidate source scope')
    return 'f-' + digest(['source-omission',packet.case_id,packet.source.sha256,atom['claim_id']])[:20]


def correct_omission(packet, request: OmissionCorrectionRequest):
    packet.verify()
    if packet.extraction_metadata.get('soap_projection_version') != 'soap/v5':
        raise ValueError('Omission correction requires the versioned source verification workflow')
    if request.base_version != packet.version:
        raise ValueError('Omission correction base version is stale')
    if not request.reason.strip():
        raise ValueError('Omission correction requires a source reason')
    candidate = next((r for r in candidates(packet)
                      if r['assertion']['claim_id'] == request.candidate_claim_id), None)
    if candidate is None:
        raise ValueError('No current source-first omission candidate with that identity')
    p = packet.model_copy(deep=True)
    assertion, spans = ground_fact(request.assertion, p.source)
    atom = candidate['assertion']
    new_id = candidate_fact_identity(p,candidate,assertion,spans)
    if any(f.fact_id == new_id for f in p.facts):
        raise ValueError('Omission already corrected')
    new_item = Assertion(fact_id=new_id, original_fact=assertion.model_dump(), assertion=assertion,
                        evidence_ids=[s.evidence_id for s in spans], review_status='corrected')
    p.facts.append(new_item)
    known = {s.evidence_id for s in p.evidence}
    p.evidence.extend(s for s in spans if s.evidence_id not in known)
    from .atomic import checklist
    from .action_state import inspect_action
    original = p.model_copy(deep=True)
    for item in original.facts:
        item.assertion, _ = ground_fact(item.original_fact, original.source)
    previous = p.extraction_metadata['atomic_source_checklist']
    p.extraction_metadata['atomic_source_checklist'] = checklist(
        original, previous.get('independent_source_assertions', []))
    action = p.extraction_metadata.get('action_state_checklist')
    if action:
        p.extraction_metadata['action_state_checklist'] = {
            **action, 'assertions':[inspect_action(item,original.source,version=action['version'])
                                   for item in original.facts]}
    # Verify all proposed dimensions, not just the candidate's concept and quote.
    projected = project(p)
    proof = next(r for r in projected.extraction_metadata['evidence_verification']['assertions']
                 if r['fact_id'] == new_id)
    if proof['result']['status'] != 'SUPPORTED_BY_SOURCE':
        raise ValueError('Added assertion is not supported in all asserted source dimensions')
    p.version += 1
    p.parent_hash = packet.content_hash
    p.created_at = now()
    p.reviews.append(ReviewRecord(base_version=packet.version, fact_id=new_id, action='correct',
        reason=request.reason, evidence_ids=new_item.evidence_ids, reviewer=request.reviewer,
        replacement=assertion.model_dump(), review_id='review-'+digest([packet.content_hash,new_id])[:20],
        recorded_at=p.created_at, applied_version=p.version, before={}, after=assertion.model_dump()))
    p.extraction_metadata.setdefault('omission_corrections', []).append({
        'candidate_claim_id':atom['claim_id'], 'added_fact_id':new_id, 'version':p.version,
        'original_model_output_unchanged':True, 'source_hash':p.source.sha256})
    return project(p)


def complete_eligible_omissions(packet, *, store=None):
    """Only calibrated low-risk source candidates can be added without user review."""
    core = verification_package()
    configuration = packet.extraction_metadata['evidence_verification']['configuration']
    source = {'source_id':packet.source.document_id,'text':packet.source.text,
              'sha256':packet.source.sha256,'patient_id':packet.patient_id,
              'encounter_id':packet.case_id,'input_kind':packet.source.input_kind}
    result = packet
    for candidate in list(candidates(packet)):
        atom = candidate['assertion']
        proof = verify_source_claim(source, atom, calibrations=configuration['calibrations'])
        if proof['risk_route'] != 'AUTO_ACCEPT_ELIGIBLE':
            continue
        span = atom['spans'][0]
        raw = {'category':atom['category'],'concept':atom['concept'],'original_term':span['quote'],
               'polarity':{'affirmed':'present'}.get(atom['polarity'],atom['polarity']),
               'temporality':atom['temporality'],'experiencer':atom['experiencer'],
               'attributes':None,'assertion_basis':atom['reporting_basis'],
               'attribution_confidence':'context_supported','clinical_status':None,
               'evidence':{k:span[k] for k in ('start','end','quote')}}
        previous_version = result.version
        result = correct_omission(result, OmissionCorrectionRequest(base_version=result.version,
            candidate_claim_id=atom['claim_id'],reason='Calibrated explicit source assertion omitted by extraction.',
            reviewer={'reviewer_id':'evidence-verifier','reviewer_type':'ai','version':core.ENGINE_VERSION},
            assertion=raw))
        if store is not None:
            store.save(result, expected_version=previous_version)
    return result
