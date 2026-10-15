"""Opt-in v2 source scopes, using the sealed verifier and original review contract.

Historical results remain frozen. Contextual support is deliberately
limited to explicit symptoms and declared patient turns, not clinical truth.
"""
from __future__ import annotations

import re
from itertools import combinations

from ..models import Calibration, Claim, DimensionCheck, Source, SourceReview, Span, digest
from ..coverage import (ACTION, LITERAL_INTERPRETATION, TEMPORAL_INTERPRETATION, SYMPTOMS, _scope_units, enumerate_source_assertions,
                        inspect_source_context, norm, overlapping, source_units)
from ..verifier import ACTION_REPRESENTATIONS, EvidenceVerifier, _compare, _contradictory_atoms, _known

METHOD = 'contextual-source-symptom/2'
SCOPE = 'contextual-symptom-clause/2'
LABEL = re.compile(r'^\s*(\[(patient|doctor|clinician|nurse|family)\]|(patient|doctor|clinician|nurse|family):)\s*', re.I)
SENTENCE = re.compile(r'^(?P<subject>(?:the\s+)?patient|i)\s+(?P<verb>do not have|don[\'’]t have|have had|have|has|reports|report|denies|deny)\s+(?P<terms>.+?)\.?$',re.I)
DURATION = re.compile(r'\s+for\s+((?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s+(?:days?|weeks?|months?))$',re.I)
WHEN = re.compile(r'\s+(today|currently|now)$',re.I)


def _basis(value):
    return {'patient_reported':'patient_report','reported_by_patient':'patient_report'}.get(value,value)


def _preceding_qualifiers(source, claim):
    units=list(source_units(source));qualifiers=[]
    for index,unit in enumerate(units):
        if not any(span.start<unit.end and unit.start<span.end for span in claim.spans):
            continue
        for prior in units[max(0,index-2):index]:
            historical_heading=re.fullmatch(r'\s*(?:childhood|past|historical|remote|previous)\s+(?:history|symptoms|events|visit|encounter)(?:\s+(?:below|follows|recorded below))?\s*[:.!]?\s*',prior.quote,re.I)
            if historical_heading or (re.search(r'\b(?:following|below|next|example|scenario|quote|quotation)\b',prior.quote,re.I)
                    and re.search(r'\b(?:hypothetical|imagined|conditional|family|mother|father|wife|husband|another|not)\b',prior.quote,re.I)):
                qualifiers.append(prior)
    return qualifiers


def _symptom_atoms(source, source_interpretation_version=None):
    if source_interpretation_version:
        return [a for a in enumerate_source_assertions(source, source_interpretation_version=source_interpretation_version).assertions
                if a.category=='symptom' and a.polarity in {'affirmed','absent'} and a.experiencer!='unknown']
    atoms=[]
    for unit in _scope_units(source):
        label=LABEL.match(unit.quote)
        role=(label.group(2) or label.group(3)).casefold() if label else None
        offset=unit.start+(label.end() if label else 0)
        text=source.text[offset:unit.end].strip().rstrip('.!')
        match=SENTENCE.fullmatch(text)
        if not match or (match['subject'].casefold()=='i' and role!='patient'):
            continue
        # Explicit patient subject is required. A line label alone never resolves
        # a quotation, family subject, or another speaker's first-person statement.
        verb=match['verb'].casefold();body=match['terms'];event_time=None;attributes={}
        when=WHEN.search(body)
        if when:
            event_time='today' if when.group(1).casefold()=='today' else None
            body=body[:when.start()]
        duration=DURATION.search(body)
        if duration:
            attributes={'duration':duration.group(1)};body=body[:duration.start()]
        terms=[re.sub(r'^(?:a|an|any|the)\s+','',term.strip(),flags=re.I)
               for term in re.split(r'\s*(?:,|\band\b)\s*',body)]
        if not terms or any(not SYMPTOMS.fullmatch(re.sub(r'^(?:right|left)\s+','',term,flags=re.I)) for term in terms):
            continue
        if attributes and len(terms)!=1:
            continue  # Quantity attachment to multiple entities is not inferred.
        basis='patient_report' if verb in {'reports','report','denies','deny'} or match['subject'].casefold()=='i' else 'documented_history'
        polarity='absent' if verb in {'denies','deny','do not have',"don't have",'don’t have'} else 'present'
        span=Span(start=offset,end=unit.end,quote=source.text[offset:unit.end],source_id=source.source_id)
        for term in terms:
            atoms.append(Claim(claim_id='context-atom-'+digest([source.sha256,offset,unit.end,term])[:24],
                source_id=source.source_id,patient_id=source.patient_id,encounter_id=source.encounter_id,
                category='symptom',concept=term,spans=[span],experiencer='patient',reporting_basis=basis,
                polarity=polarity,certainty='explicit',temporality='current',event_time=event_time,attributes=attributes))
    return atoms


def _other_actor(unit):
    label=LABEL.match(unit.quote)
    role=(label.group(2) or label.group(3)).casefold() if label else None
    text=unit.quote[label.end():] if label else unit.quote
    # A clinician reporting on the patient is not the symptom experiencer.
    # Such embedded subjects remain outside the direct-actor exclusion grammar.
    if re.search(r'\b(?:patient|someone else|another person)\b',text,re.I):
        return None
    if role and role!='patient' and re.match(r'\s*I\s+',text,re.I):
        return role
    match=re.match(r"\s*(?:the\s+)?(doctor|clinician|mother|father|wife|husband|patient['’]s mother|patient['’]s father)\s+",text,re.I)
    return match.group(1).casefold() if match else None


def _related_unresolved(source,claim,source_interpretation_version=None):
    if claim.category!='symptom':
        return []
    atoms=_symptom_atoms(source,source_interpretation_version);unknown=[]
    for unit in _scope_units(source):
        if not re.search(r'(?<!\w)'+re.escape(norm(claim.concept))+r'(?!\w)',unit.quote,re.I):
            continue
        if _other_actor(unit):
            continue
        resolved=any(norm(atom.concept)==norm(claim.concept) and any(s.start<unit.end and unit.start<s.end for s in atom.spans) for atom in atoms)
        if not resolved:
            unknown.append(unit)
    return unknown


def _distinct_actor_conflict(source,claim):
    atoms=[atom for atom in enumerate_source_assertions(source).assertions if norm(atom.concept)==norm(claim.concept)]
    pairs=[(a,b) for a,b in combinations(atoms,2) if _contradictory_atoms(a,b)]
    return bool(pairs) and all(any(_other_actor(span) for span in [*a.spans,*b.spans]) for a,b in pairs)


def _context_review(source,claim,source_interpretation_version=None):
    if claim.category!='symptom' or claim.experiencer!='patient':
        return None
    atoms=_symptom_atoms(source,source_interpretation_version)
    own=[atom for atom in atoms if norm(atom.concept)==norm(claim.concept) and overlapping(atom,claim)]
    if len(own)!=1:
        return None
    atom=own[0]
    uncertainties,qualifiers=inspect_source_context(source,claim,atom)
    if uncertainties:
        return None
    units=list(source_units(source))
    indices=[index for index,unit in enumerate(units) if any(span.start<unit.end and unit.start<span.end for span in atom.spans)]
    # A preceding heading/continuation can qualify a following clinical sentence.
    # It is never discarded by considering only the quoted sentence.
    for index in indices:
        for prior in units[max(0,index-2):index]:
            if (re.search(r'\b(?:following|below|next|example|scenario|quote|quotation)\b',prior.quote,re.I)
                    and re.search(r'\b(?:hypothetical|imagined|conditional|family|mother|father|wife|husband|another|not)\b',prior.quote,re.I)):
                return None
    proposed=claim.model_copy(update={'reporting_basis':_basis(claim.reporting_basis)})
    checks=_compare(proposed,atom,source_interpretation_version=source_interpretation_version)
    # Canonical aliases are an explicit representation map, not a new opinion.
    for check in checks:
        if check.dimension=='reporting_basis':
            check.proposed=claim.reporting_basis
            if check.status=='SUPPORTED':
                check.source_value=claim.reporting_basis
                check.reason='Original explicit reporting predicate; predeclared patient-report representation equivalence.'
    related=[item for item in atoms if norm(item.concept)==norm(atom.concept) and item.temporality==atom.temporality and item.event_time==atom.event_time]
    conflicted=any(left.polarity!=right.polarity for left,right in combinations(related,2))
    bad=[item for item in checks if item.status=='CONTRADICTED'];unknown=[item for item in checks if item.status=='UNVERIFIED']
    status='CONFLICTED' if conflicted else 'CONTRADICTED' if bad else 'INSUFFICIENT_EVIDENCE' if unknown else 'SUPPORTED_BY_SOURCE'
    full=Span(start=0,end=len(source.text),quote=source.text,source_id=source.source_id)
    checks.append(DimensionCheck(dimension='source_context',status='SUPPORTED',proposed='full_source_scope_resolved',
        source_value='full_source_scope_resolved',reason='Complete original source inspected; declared speaker, adjacent qualifiers, same-event contradictory clauses retained.',spans=[full]))
    return SourceReview(review_id='context-review-'+claim.fingerprint()[:24],source_id=source.source_id,
        source_hash=source.sha256,claim_fingerprint=claim.fingerprint(),patient_id=source.patient_id,
        encounter_id=source.encounter_id,status=status,dimension_checks=checks,
        supporting_spans=atom.spans if status=='SUPPORTED_BY_SOURCE' else [],
        counter_spans=[span for item in related for span in item.spans] if conflicted else atom.spans if bad else [],
        reason='Opt-in bounded explicit symptom clause with original declared speaker and complete source scope.',
        method=METHOD,reviewer_type='deterministic_source_scope',uncertainty=[item.dimension for item in unknown])


def _discussion_review(source,claim):
    if claim.action_state!='discussed' or not claim.concept:
        return None
    for unit in _scope_units(source):
        label=LABEL.match(unit.quote)
        role=(label.group(2) or label.group(3)).casefold() if label else None
        offset=unit.start+(label.end() if label else 0)
        text=source.text[offset:unit.end].strip().rstrip('.!')
        match=re.fullmatch(r'(?P<subject>(?:the\s+)?patient|i|we|(?:the\s+)?clinician)\s+(?P<modal>would|might|may|could)\s+(?:consider|discuss)\s+(?P<object>.+)',text,re.I)
        if not match or (match['subject'].casefold()=='i' and role!='patient'):
            continue
        entity=re.split(r'\s+if\s+',match['object'],maxsplit=1,flags=re.I)[0].strip()
        if norm(entity)!=norm(claim.concept) or not any(span.start<unit.end and unit.start<span.end for span in claim.spans):
            continue
        span=Span(start=offset,end=unit.end,quote=source.text[offset:unit.end],source_id=source.source_id)
        scoped=claim.model_copy(update={'spans':[span]})
        unresolved,_=inspect_source_context(source,claim,scoped)
        if unresolved or _preceding_qualifiers(source,claim):
            continue
        # The source supports conditional consideration, not a committed plan,
        # an executed therapy, or an assertion's missing clinical reporting basis.
        checks=[]
        for name in ('category','concept','experiencer','polarity','temporality','reporting_basis','certainty','event_time','action_type','action_state','completion_scope'):
            value=getattr(claim,name)
            supported=name in {'concept','action_state'} or (name=='experiencer' and match['subject'].casefold() in {'patient','the patient','i'} and value=='patient')
            checks.append(DimensionCheck(dimension=name,status='SUPPORTED' if supported else 'NOT_ASSERTED' if value in {None,'unknown'} else 'UNVERIFIED',
                proposed=value,source_value=value if supported else None,
                reason='Explicit source conditional consideration.' if supported else 'Conditional topic does not supply a committed plan, execution or clinical assessment.',spans=[span]))
        for key,value in claim.attributes.items():
            if value is not None:
                checks.append(DimensionCheck(dimension='attributes.'+key,status='UNVERIFIED',proposed=value,
                    reason='Conditional discussion does not establish this attribute.',spans=[span]))
        return SourceReview(review_id='discussion-review-'+claim.fingerprint()[:24],source_id=source.source_id,
            source_hash=source.sha256,claim_fingerprint=claim.fingerprint(),patient_id=source.patient_id,
            encounter_id=source.encounter_id,status='INSUFFICIENT_EVIDENCE',dimension_checks=checks,
            supporting_spans=[span],reason='Explicit hypothetical discussion; full clinical proposition remains unverified.',
            method='conditional-source-discussion/2',reviewer_type='deterministic_source_scope',
            uncertainty=['hypothetical_discussion_not_committed_plan'])
    return None


def _distinct_event_conflict(source,claim):
    atoms=[atom for atom in enumerate_source_assertions(source).assertions if norm(atom.concept)==norm(claim.concept)]
    conflicting=[(a,b) for a,b in combinations(atoms,2) if _contradictory_atoms(a,b)]
    if not conflicting:
        return False
    # Known prescription/order, administration and whole-course events do not
    # become a single event merely because a medication/entity name matches.
    return all(a.action_type and b.action_type and a.action_type!=b.action_type for a,b in conflicting)


def _recognized_action_prefix(atom):
    """Only identify the bounded parser's scope; never infer an alternative state.

    An action verb found after an unparsed report, time clause or aspect modifier
    cannot independently refute a proposal. Literal auxiliary/subject scaffolding
    is deliberately narrow. This guard grants no source support or calibration.
    """
    for span in atom.spans:
        actions = list(ACTION.finditer(span.quote))
        if len(actions) != 1:
            return False
        prefix = norm(LABEL.sub('', span.quote[:actions[0].start()]))
        prefix = re.sub(r'(?<!\w)' + re.escape(norm(atom.concept)) + r'(?!\w)', 'entity', prefix)
        if not re.fullmatch(
                r'(?:the )?(?:patient(?: [a-z0-9])?|pt|i|we|entity)'
                r'(?: (?:was|were|is|are|am|has|have|had|been|being|did|do|does|not|never|will|to|plan|plans|currently|previously))*',
                prefix):
            return False
    return bool(atom.spans)


def verify_contextual_claim(source,claim,*,reviews=(),calibrations=(),event_comparability_version=None,source_interpretation_version=None):
    """v6-only adapter to the same EvidenceVerifier, with versioned local scope."""
    source=Source.model_validate(source);claim=Claim.model_validate(claim)
    if event_comparability_version not in {None, 'distinct-source-event-comparability/2', 'distinct-source-event-comparability/3', 'distinct-source-event-comparability/4'}:
        raise ValueError('Unavailable source event comparability version')
    core=EvidenceVerifier(source_interpretation_version=source_interpretation_version)
    base=core.verify(source,claim,reviews=reviews)
    original_reviews=[SourceReview.model_validate(review) for review in reviews]
    # A future arrangement and a current execution state can both be true.
    # A bounded parser that found only one of those events cannot use it as
    # counterevidence for the other. This opt-in rule only withdraws an invalid
    # counterclaim; it does not establish or adopt the proposed event.
    atom = base.source_assertion
    times = {'current', 'historical', 'planned'}
    states = {'planned', 'completed', 'not_completed', 'ongoing', 'discussed'}
    if (event_comparability_version == 'distinct-source-event-comparability/4'
            and base.status == 'CONTRADICTED' and not original_reviews and atom is not None
            and atom.action_state in states and not _recognized_action_prefix(atom)):
        checks = [check.model_copy(update={'status':'UNVERIFIED',
            'reason':'The action parser did not resolve its complete subject/auxiliary/aspect prefix.'})
            if check.status == 'CONTRADICTED' else check for check in base.dimension_checks]
        return base.model_copy(update={'status':'INSUFFICIENT_EVIDENCE', 'dimension_checks':checks,
            'supporting_spans':[], 'counter_spans':[],
            'context_spans':list({(s.start,s.end):s for s in [*base.context_spans,*base.counter_spans]}.values()),
            'risk_route':'REVIEW_REQUIRED', 'calibration_id':None, 'method':'unparsed-action-prefix/4',
            'uncertainty':[*base.uncertainty,'unparsed_action_prefix'],
            'reasons':['Retained earlier partial-parse opinion: '+r for r in base.reasons]
                      + ['An isolated action verb with an unresolved prefix cannot establish counterevidence.']})
    if (event_comparability_version in {'distinct-source-event-comparability/3', 'distinct-source-event-comparability/4'}
            and base.status == 'CONTRADICTED' and not original_reviews and atom is not None
            and norm(atom.concept) == norm(claim.concept)
            and atom.experiencer == claim.experiencer != 'unknown'
            and atom.temporality in times and claim.temporality in times
            and atom.temporality != claim.temporality
            and atom.action_state in states and _known(claim.action_state)):
        checks = [check.model_copy(update={
            'status': 'UNVERIFIED',
            'reason': 'A different temporal action proposition is not independent counterevidence.'})
            if check.status == 'CONTRADICTED' else check for check in base.dimension_checks]
        context = list({(s.start, s.end): s for s in
                        [*base.context_spans, *base.counter_spans]}.values())
        return base.model_copy(update={'status': 'INSUFFICIENT_EVIDENCE',
            'dimension_checks': checks, 'supporting_spans': [], 'counter_spans': [],
            'context_spans': context, 'risk_route': 'REVIEW_REQUIRED', 'calibration_id': None,
            'method': 'distinct-source-event-comparability/3',
            'uncertainty': [*base.uncertainty, 'distinct_temporal_action_proposition'],
            'reasons': ['Retained earlier unscoped opinion: ' + reason for reason in base.reasons]
                       + ['The located event has a different time scope; the proposed event remains unverified.']})
    # An explicit prescription proposal and a negative administration event are
    # different propositions. A parser that cannot resolve the prescription's
    # multi-action sentence must report uncertainty, not borrow the other event
    # as a contradiction. Preserve the complete context and original checks.
    action_aliases = {'prescribed': 'prescription', 'prescription': 'prescription',
                      'administration_event': 'administration_event',
                      'therapy_course': 'therapy_course', 'therapy_event': 'therapy_event',
                      'procedure_event': 'procedure_event', 'order_placed': 'order_placed'}
    if source_interpretation_version in {LITERAL_INTERPRETATION,TEMPORAL_INTERPRETATION}:
        action_aliases.update(ACTION_REPRESENTATIONS)
    wanted = action_aliases.get(claim.action_type)
    observed = action_aliases.get(base.source_assertion.action_type) if base.source_assertion else None
    same_event_atoms = [a for a in enumerate_source_assertions(source).assertions
                        if norm(a.concept) == norm(claim.concept)
                        and action_aliases.get(a.action_type) == wanted] if wanted else []
    if (event_comparability_version in {'distinct-source-event-comparability/2', 'distinct-source-event-comparability/3', 'distinct-source-event-comparability/4'}
            and base.status == 'CONTRADICTED' and not original_reviews and wanted and observed
            and wanted != observed and not same_event_atoms):
        checks = [check.model_copy(update={
            'status': 'UNVERIFIED',
            'reason': 'Different known source action type cannot contradict this proposed event.'})
            if check.status == 'CONTRADICTED' else check for check in base.dimension_checks]
        return base.model_copy(update={'status': 'INSUFFICIENT_EVIDENCE',
            'dimension_checks': checks, 'supporting_spans': [], 'counter_spans': [],
            'context_spans': list({(s.start, s.end): s for s in [*base.context_spans, *base.counter_spans]}.values()),
            'risk_route': 'REVIEW_REQUIRED', 'calibration_id': None,
            'method': 'distinct-source-event-comparability/2',
            'uncertainty': [*base.uncertainty, 'proposed_action_event_not_independently_resolved'],
            'reasons': [*base.reasons, 'Retained earlier comparison belongs to a different action event; it is not counterevidence for this event.']})
    # Two versioned representations of an explicitly completed whole course;
    # this is never an equivalence between one administration/session and a course.
    atom=base.source_assertion
    contradicted=[check.dimension for check in base.dimension_checks if check.status=='CONTRADICTED']
    same_entity=[a for a in enumerate_source_assertions(source).assertions if norm(a.concept)==norm(claim.concept)]
    if (base.status=='CONFLICTED' and original_reviews and atom is not None
            and claim.completion_scope=='full_course' and atom.completion_scope=='course'
            and claim.action_state==atom.action_state=='completed'
            and atom.action_type=='therapy_course' and contradicted==['completion_scope']
            and all(review.status=='SUPPORTED_BY_SOURCE' for review in original_reviews)
            and not any(_contradictory_atoms(a,b) for a,b in combinations(same_entity,2))):
        for review in original_reviews:
            core._validate_review(source,claim,review,context_spans=base.context_spans)
        review=original_reviews[0]
        return base.model_copy(update={'status':'SUPPORTED_BY_SOURCE','dimension_checks':review.dimension_checks,
            'supporting_spans':review.supporting_spans,'counter_spans':[],
            'risk_route':'REVIEW_REQUIRED','calibration_id':None,'uncertainty':review.uncertainty,
            'method':'completed-course-representation/2','model_version':review.model_version,
            'reasons':[*base.reasons,'Explicit completed therapy course and independent complete-source review support the declared course/full_course representation equivalence.']})
    if (base.status=='CONFLICTED' and not original_reviews and _distinct_event_conflict(source,claim)
            and base.source_assertion is not None and claim.action_type
            and base.source_assertion.action_type==claim.action_type
            and not base.context_spans and not base.uncertainty
            and all(check.status in {'SUPPORTED','NOT_ASSERTED'} for check in base.dimension_checks)):
        return base.model_copy(update={'status':'SUPPORTED_BY_SOURCE','counter_spans':[],
            'supporting_spans':base.source_assertion.spans,'risk_route':'REVIEW_REQUIRED','calibration_id':None,
            'method':'event-scoped-native/2',
            'reasons':[*base.reasons,'Exact quoted assertion and known action type identify a different event from the other source action.']})
    related_unknown=_related_unresolved(source,claim,source_interpretation_version)
    if related_unknown and base.status in {'CONTRADICTED','CONFLICTED'}:
        return base  # Unparsed context never erases already explicit counterevidence.
    if related_unknown and original_reviews:
        if base.status in {'CONTRADICTED','CONFLICTED'}:
            return base
        resolved=False
        for review in original_reviews:
            try:
                core._validate_review(source,claim,review,context_spans=[*base.context_spans,*related_unknown])
                resolved=resolved or review.status=='SUPPORTED_BY_SOURCE'
            except (ValueError,TypeError):
                pass
        if resolved:
            return base  # Independent complete-source review, outside native AUTO calibration.
    if related_unknown and base.status=='SUPPORTED_BY_SOURCE' and not original_reviews:
        return base.model_copy(update={'status':'INSUFFICIENT_EVIDENCE','supporting_spans':[],
            'context_spans':[*base.context_spans,*related_unknown], 'risk_route':'REVIEW_REQUIRED','calibration_id':None,
            'method':'related-source-scope/2','uncertainty':[*base.uncertainty,'unparsed_related_source_assertion'],
            'reasons':[*base.reasons,'Another original unit mentions this entity without a resolved subject, polarity or event.']})
    preceding=_preceding_qualifiers(source,claim)
    if preceding:
        resolved=False
        for review in original_reviews:
            try:
                core._validate_review(source,claim,review,context_spans=[*base.context_spans,*preceding])
                resolved=resolved or review.status=='SUPPORTED_BY_SOURCE'
            except (ValueError,TypeError):
                pass
        if not resolved and base.status=='SUPPORTED_BY_SOURCE':
            return base.model_copy(update={'status':'INSUFFICIENT_EVIDENCE','supporting_spans':[],
                'context_spans':[*base.context_spans,*preceding],'risk_route':'REVIEW_REQUIRED','calibration_id':None,
                'method':'original-preceding-scope/2','uncertainty':[*base.uncertainty,'preceding_source_scope_unresolved'],
                'reasons':[*base.reasons,'Original preceding heading changes subject or modality; local sentence is insufficient.']})
    # Resolve only a proved false native cross-event conflict; independently
    # conflicting reviews, unclear event types, and true same-event conflicts stay.
    if (base.status=='CONFLICTED' and original_reviews and _distinct_event_conflict(source,claim)
            and len({review.status for review in original_reviews})==1
            and original_reviews[0].status!='CONFLICTED'):
        review=original_reviews[0]
        for retained in original_reviews:
            core._validate_review(source,claim,retained,context_spans=base.context_spans)
        route='CORRECTION_CANDIDATE' if review.status=='CONTRADICTED' else 'REVIEW_REQUIRED'
        return base.model_copy(update={'status':review.status,'dimension_checks':review.dimension_checks,
            'supporting_spans':review.supporting_spans,'counter_spans':review.counter_spans,
            'method':'event-scoped-source-review/2','model_version':review.model_version,
            'uncertainty':review.uncertainty,'risk_route':route,'calibration_id':None,
            'reasons':[*base.reasons,'Known distinct source action types are not a same-event conflict.',review.reason]})
    if base.risk_route=='MISSING_EVIDENCE':
        return base
    own=_context_review(source,claim,source_interpretation_version)
    if own is not None and related_unknown:
        return base.model_copy(update={'status':'INSUFFICIENT_EVIDENCE','supporting_spans':[],
            'context_spans':[*base.context_spans,*related_unknown], 'risk_route':'REVIEW_REQUIRED','calibration_id':None,
            'method':'related-source-scope/2','uncertainty':[*base.uncertainty,'unparsed_related_source_assertion'],
            'reasons':[*base.reasons,'Full original source includes unresolved same-entity assertions; no automatic local winner.']})
    if own is None:
        own=_discussion_review(source,claim)
        if own is None:
            return base
    result=core.verify(source,claim,reviews=[own,*original_reviews])
    if (own.status=='SUPPORTED_BY_SOURCE' and result.status=='CONFLICTED'
            and _distinct_actor_conflict(source,claim)
            and all(review.status==own.status for review in original_reviews)):
        for retained in [own,*original_reviews]:
            core._validate_review(source,claim,retained,context_spans=base.context_spans)
        result=result.model_copy(update={'status':own.status,'dimension_checks':own.dimension_checks,
            'supporting_spans':own.supporting_spans,'counter_spans':[], 'risk_route':'REVIEW_REQUIRED','calibration_id':None,
            'method':METHOD,'uncertainty':own.uncertainty,
            'reasons':[*result.reasons,'Explicit different source actors are not one patient event.']})
    if result.status=='SUPPORTED_BY_SOURCE' and own.status=='SUPPORTED_BY_SOURCE':
        resolved={check.dimension for check in own.dimension_checks if check.status=='SUPPORTED'}
        result=result.model_copy(update={'uncertainty':[reason for reason in result.uncertainty
            if reason not in resolved and reason not in {'unrecognized_source_semantics','source_subject_unresolved'}]})
    # Never borrow a model's method identity or use confidence as calibration.
    legacy_scope = (not source_interpretation_version or any(
        norm(atom.concept)==norm(claim.concept) and overlapping(atom,claim)
        for atom in _symptom_atoms(source)))
    if (result.status=='SUPPORTED_BY_SOURCE' and own.status=='SUPPORTED_BY_SOURCE' and legacy_scope
            and not result.uncertainty and claim.temporality=='current'
            and claim.action_state in {'unknown',''} and claim.action_type is None
            and set(claim.attributes)<= {'duration'}):
        for raw in calibrations:
            calibration=Calibration.model_validate(raw)
            if (calibration.method==METHOD and calibration.scope==SCOPE and 'symptom' in calibration.categories
                    and calibration.measured_precision>=calibration.minimum_precision):
                result=result.model_copy(update={'risk_route':'AUTO_ACCEPT_ELIGIBLE',
                    'calibration_id':calibration.calibration_id,'method':METHOD})
                break
    return result
