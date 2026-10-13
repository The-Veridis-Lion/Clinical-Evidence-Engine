"""Partial source-first enumeration. Not a replacement clinical extractor.

Only bounded explicit grammar is enumerated. Every original unit is retained,
including already-cited units; an unrecognized unit is never evidence of absence.
The vocabulary below names literal symptoms, not a diagnostic ontology or aliases.
"""
from __future__ import annotations
import re
from .models import Claim, CoverageResult, EnumerationResult, Source, Span, digest

# Literal scope anchors, deliberately excluding broad medical synonym inference.
# These do not classify all medical text; outside this boundary completeness is unknown.
SYMPTOMS = re.compile(r'\b(?:cough|fever|dyspnea|breathlessness|shortness of breath|chest pain|knee pain|headache|nausea|vomiting|dizziness|rhinorrhea|nasal congestion|sneezing|tremor|fatigue|rash)\b', re.I)
UNIT = re.compile(r'.+?(?:[.!?](?!\d)(?=\s|$)|\n|$)',re.M)
BOUNDARY = re.compile(r';|\b(?:but|however|whereas)\b', re.I)
UNKNOWN = re.compile(r'\b(?:unclear|unknown|possibly|possible|perhaps|may|might|could|would|if|whether)\b|\?', re.I)
PATIENT = re.compile(r'^(?:(?:patient|pt|he|she|they|i)\s*:\s*)?(?:the\s+)?(?:patient|pt|he|she|they|i)\b', re.I)
FAMILY = re.compile(r'\b(?:mother|father|sister|brother|daughter|son|wife|husband|family)\b', re.I)
ACTION = re.compile(r'\b(?:take|took|taken|taking|administered|prescribed|started|received|receiving|completed|finished|performed|stopped|discontinued|scheduled|order|ordered|request|requested)\b', re.I)
ACTION_STATES = {'took':'completed','taken':'completed','administered':'completed',
    'taking':'ongoing','receiving':'ongoing','prescribed':'planned','started':'ongoing',
    'received':'completed','completed':'completed','finished':'completed','performed':'completed',
    'stopped':'not_completed','discontinued':'not_completed','scheduled':'planned','take':'unknown',
    'order':'planned','ordered':'planned','request':'planned','requested':'planned'}
FREQUENCY=re.compile(r'\b(?:(?:once|twice|three times|two times)\s+(?:daily|weekly|monthly)|(?:once|twice|three times|two times)\s+(?:a|per)\s+(?:day|week|month)|every\s+\d+\s+(?:hours?|days?|weeks?)|daily|weekly|monthly)\b',re.I)
AUTO_SCOPE = 'explicit-symptom-clause/1'
AUTO_CLAUSE = re.compile(r'^(?:(?:patient|pt)\s*:\s*)?(?:the\s+)?(?:patient|pt|i)\s+'
    r'(?:currently\s+)?(?:has|have|reports|report|denies|deny|does\s+not\s+have)\s+'
    r'(?P<objects>[a-z ,]+?)(?:\s+(?:today|currently))?\s*[.!]?$',re.I)


def automatic_symptom_scope(spans):
    """Auto routing has a smaller grammar than candidate source enumeration.

    The guard accepts complete explicit clauses only. A richer but source-supported
    clinical statement can remain reviewable without becoming auto eligible.
    """
    if not spans:
        return False
    for span in spans:
        match=AUTO_CLAUSE.fullmatch(span.quote.strip())
        if not match:
            return False
        items=re.split(r'\s*,\s*|\s+and\s+',match.group('objects'),flags=re.I)
        if not items or not all(SYMPTOMS.fullmatch(item.strip()) for item in items):
            return False
    return True


def inspect_source_context(source,claim,atom):
    """Locate unresolved scope qualifiers; never manufacture their resolved meaning.

    Local entailment does not establish the referenced subject/event when an
    original unit or its immediately adjacent continuation qualifies it. This
    detector only routes uncertainty; it does not rewrite a fact from keywords.
    Unrelated subsequent assertions retain their separate meanings.
    """
    original=list(source_units(source))
    own=[i for i,unit in enumerate(original) if any(s.start<unit.end and unit.start<s.end for s in atom.spans)]
    reasons=[];evidence=[]
    for index in own:
        unit=original[index]
        report=re.search(r'\b(?:reports?|reported)\b\s+(.+?)\b(?:has|have|had|denies|denied)\b',unit.quote,re.I)
        concept_location=re.search(r'(?<!\w)'+re.escape(norm(atom.concept))+r'(?!\w)',unit.quote,re.I)
        if report and concept_location and report.end()<=concept_location.start():
            reasons.append('source_context_embedded_reported_subject')
            evidence.append(unit)
        dates=re.findall(r'\b(?:today|yesterday|tomorrow|\d{4}-\d{2}-\d{2})\b',unit.quote,re.I)
        if len({v.casefold() for v in dates})>1:
            reasons.append('source_context_multiple_event_times')
            evidence.append(unit)
        for context in original[index:index+2]:
            # Explicitly different symptom nouns in a later clause do not become
            # coreference to the current claim solely because they are adjacent.
            other_concepts={norm(m.group()) for m in SYMPTOMS.finditer(context.quote)}
            if context is not unit and other_concepts and norm(claim.concept) not in other_concepts:
                continue
            reference=re.search(r'\b(?:this|that|these|those|it|its|the symptom|the complaint|the report)\b',context.quote,re.I)
            limiter=re.search(r'\b(?:not|never|no|hypothetical|example|imagined|conditional|denies|denied|refers? to|rather than|belongs? to|someone else|another person)\b|\b(?:her|his|their|my|our|your)\s+\w+|\b\w+[\'’]s\b',context.quote,re.I)
            if reference and limiter:
                reasons.append('source_context_unresolved_attribution_modality_or_negation')
                evidence.append(context)
    unique=[];seen=set()
    for span in evidence:
        identity=(span.start,span.end)
        if identity not in seen:
            seen.add(identity);unique.append(span)
    return list(dict.fromkeys(reasons)),unique


def norm(value):
    return re.sub(r'\s+', ' ', str(value or '').casefold()).strip(' .,:;')


def canonical_dimension(key,value):
    if key=='polarity':
        return {'present':'affirmed','positive':'affirmed','negative':'absent'}.get(value,value)
    if key=='certainty':
        return {'asserted':'explicit'}.get(value,value)
    if key=='action_state':
        return {'not_applicable':'unknown'}.get(value,value)
    if key=='temporality':
        return {'past':'historical','future':'planned','present':'current'}.get(value,value)
    return norm(value) if key=='concept' else value


def _equivalent_source_proposals(a,b):
    if a.source_id!=b.source_id or a.patient_id!=b.patient_id or a.encounter_id!=b.encounter_id or not overlapping(a,b):
        return False
    for field in ('category','concept','experiencer','polarity','temporality','event_time','action_type','action_state','completion_scope'):
        left=canonical_dimension(field,getattr(a,field));right=canonical_dimension(field,getattr(b,field))
        if left not in {None,'','unknown'} and right not in {None,'','unknown'} and left!=right:
            return False
    return all(key not in b.attributes or b.attributes[key]==value for key,value in a.attributes.items() if value is not None)


def source_units(source):
    for match in UNIT.finditer(source.text):
        text = match.group()
        leading = len(text)-len(text.lstrip())
        start, end = match.start()+leading, match.end()
        if start >= end:
            continue
        yield Span(start=start,end=end,quote=source.text[start:end],source_id=source.source_id)


def _scope_units(source):
    for unit in source_units(source):
        begin = 0
        for match in [*BOUNDARY.finditer(unit.quote), None]:
            end = match.start() if match else len(unit.quote)
            text = unit.quote[begin:end]
            left = begin+len(text)-len(text.lstrip())
            right = end-len(text)+len(text.rstrip())
            if left < right:
                start, stop = unit.start+left, unit.start+right
                yield Span(start=start,end=stop,quote=source.text[start:stop],source_id=source.source_id)
            if match:
                begin=match.end()


def _identity_and_time(text, *, input_kind):
    # Explicit sentence subject only. Pronoun resolution across turns is not inferred.
    first_predicate=re.search(r'\b(?:has|have|had|reports?|reported|denies|denied|took|taken|taking|administered|completed|finished)\b',text,re.I)
    subject_scope=text[:first_predicate.start()] if first_predicate else text
    family=bool(FAMILY.search(subject_scope))
    experiencer='family' if family else 'patient' if PATIENT.search(text) or input_kind=='note' else 'unknown'
    basis='patient_report' if re.search(r'\b(?:reports?|reported|denies|denied|i)\b',text,re.I) else 'documented_history'
    text=re.sub(r'^(?:Patient|Clinician|Doctor|Pt)\s*:\s*','',text,flags=re.I)
    if re.search(r'\b(?:yesterday|previously|last\s+\w+|history|ago)\b',text,re.I):
        temporality='historical'
    elif re.search(r'\b(?:will|tomorrow|next|scheduled|plans? to)\b',text,re.I):
        temporality='planned'
    else:
        temporality='current'
    when=re.search(r'\b(?:yesterday|today|tomorrow|\d{4}-\d{2}-\d{2})\b',text,re.I)
    return experiencer,basis,temporality,when.group().casefold() if when else None


def _make(source,span,category,concept,**dimensions):
    identity=['source-atom',source.sha256,span.start,span.end,category,norm(concept),dimensions]
    return Claim(claim_id='atom-'+digest(identity)[:24],source_id=source.source_id,
                 patient_id=source.patient_id,encounter_id=source.encounter_id,
                 category=category,concept=norm(concept),spans=[span],**dimensions)


def _symptoms(source,span):
    text=span.quote
    if UNKNOWN.search(text) or re.search(r'\b(?:not only|no doubt|rule out|ruled out|risk of|worsening|improvement|in the event of|in case of|unless)\b',text,re.I):
        return []
    experiencer,basis,time,event_time=_identity_and_time(text,input_kind=source.input_kind)
    # Mere incidental mention, questions and medication indications do not assert symptoms.
    predicate=re.search(r'\b(?:has|have|having|reports?|reported|complains? of|denies|denied|no|without|negative for)\b',text,re.I)
    if not predicate:
        return []
    prefix=text[:predicate.start()]
    if re.search(r'\b(?:prescribed|treatment|medication|for|asked|ask|test|screen|monitor)\b',prefix,re.I):
        return []
    found=[]
    for token in SYMPTOMS.finditer(text,predicate.end()):
        between=text[predicate.end():token.start()]
        # A new subject, reporting modality or action means this predicate no longer governs.
        if re.search(r'\b(?:mother|father|patient|wife|husband|took|taking|prescribed|will|possible|suspected|medication|treatment|therapy|for|lack|absence|evidence|documentation|record|report)\b',between,re.I):
            continue
        # A missing report/chart entry is a statement about documentation, not symptom absence.
        # Restrict the suffix to this noun's bounded segment so a later independent
        # symptom does not acquire another assertion's documentation modifier.
        tail=text[token.end():]
        tail=re.split(r'\b(?:and|but|however|whereas)\b',tail,maxsplit=1,flags=re.I)[0]
        if re.search(r'\b(?:documented|recorded|reported|listed|mentioned)\b',tail,re.I):
            continue
        local=list(re.finditer(r'\b(?:has|have|reports?|reported|denies|denied|no|without|negative for)\b',text[:token.start()],re.I))
        conjunctions=list(re.finditer(r'\b(?:and|but|whereas|however)\b',text[:token.start()],re.I))
        scope_begin=conjunctions[-1].end() if conjunctions else 0
        negative_cues=list(re.finditer(r'\b(?:not|never|no|without|denies|denied|negative for)\b',text[scope_begin:token.start()],re.I))
        if len(negative_cues)>1:
            continue  # Multiple negation does not become an automatically positive assertion.
        cue=local[-1].group().casefold() if local else predicate.group().casefold()
        polarity='absent' if cue in {'denies','denied','no','without','negative for'} else 'affirmed'
        # "not have" and "does not report" are not the same absence proposition.
        if cue in {'have','has'} and re.search(r'\bnot\s*$',text[max(0,local[-1].start()-8):local[-1].start()],re.I):
            polarity='absent'
        elif re.search(r'\bnot\s*$',text[max(0,local[-1].start()-8):local[-1].start()],re.I):
            continue
        found.append(_make(source,span,'symptom',token.group(),experiencer=experiencer,
            reporting_basis=basis,polarity=polarity,certainty='explicit',temporality=time,event_time=event_time))
    return found


def _actions(source,span):
    text=span.quote.rstrip('.!')
    if UNKNOWN.search(text):
        return []
    matches=list(ACTION.finditer(text))
    # More than one action requires independent scope resolution; never select the convenient verb.
    if len(matches)!=1:
        return []
    action=matches[0]
    verb=action.group().casefold()
    before=text[:action.start()].strip()
    after=text[action.end():].strip()
    experiencer,basis,time,event_time=_identity_and_time(text,input_kind=source.input_kind)
    negated=bool(re.search(r"\b(?:not|never|no|neither|denies|denied|didn't|doesn't|hasn't)\b",before,re.I))
    # A no-adverse-effects adjunct is separate from the administration event.
    adjunct=re.search(r'\b(?:yesterday|today|tomorrow|as planned|with|without|for|at|during|after|before)\b',after,re.I)
    obj=(after[:adjunct.start()] if adjunct else after).strip()
    if re.search(r'\b(?:no|neither|not)\b',obj,re.I):
        negated=True
        obj=re.sub(r'\b(?:no|neither|not)\b','',obj,flags=re.I).strip()
    subject=re.sub(r'\b(?:was|is|has been|were|are|being|had been)\s*$','',before,flags=re.I).strip()
    subject=re.sub(r'^(?:Patient|Pt|Clinician|Doctor)\s*:\s*','',subject,flags=re.I).strip()
    subject=re.sub(r'\b(?:was not|is not|has not been|never|not)\s*$','',subject,flags=re.I).strip()
    passive=verb in {'taken','administered','prescribed','performed','discontinued','completed','finished','scheduled','ordered','requested'} and bool(subject) and not PATIENT.match(subject)
    entity=subject if passive else obj
    entity=re.sub(r'^(?:the patient\s+|patient\s+|pt\s+|a\s+|an\s+|the\s+)','',entity,flags=re.I).strip()
    entity=re.sub(r'\b(?:was|is|not|never|no|has been)\b','',entity,flags=re.I).strip()
    # Conjoined medications, causal clauses, and opaque pronouns need a model/human review.
    if not entity or re.search(r'\b(?:and|nor|or|it|them|because|which|that)\b',entity,re.I) or len(entity.split())>8:
        return []
    duration=re.search(r'\b(?:\d+|one|two|three|four|six|eight|twelve)[ -](?:day|week|month)s?\b',entity,re.I)
    dose=re.search(r'\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\b',entity,re.I)
    frequency=FREQUENCY.search(entity)
    attrs={}
    attribute_spans=[]
    for key,value in (('duration',duration),('dosage',dose),('frequency',frequency)):
        if value:
            attrs[key]=value.group()
            attribute_spans.append(value)
    for value in sorted(attribute_spans,key=lambda m:m.start(),reverse=True):
        entity=entity[:value.start()]+entity[value.end():]
    entity=re.sub(r'\s+',' ',entity).strip()
    course=bool(re.search(r'\bcourse\b',entity,re.I))
    therapy=course or bool(re.search(r'\b(?:\w*therapy|treatment|rehabilitation)\b',entity,re.I))
    ordering=verb in {'order','ordered','request','requested'}
    category='treatment' if therapy else 'procedure' if verb=='performed' or ordering else 'medication'
    action_type=('order_placed' if verb in {'ordered','requested'} else 'order_intent') if ordering else 'therapy_course' if course and verb in {'completed','finished'} else 'therapy_event' if therapy else 'prescription' if verb=='prescribed' else 'procedure_event' if category=='procedure' else 'administration_event'
    entity=re.sub(r'\b(?:course|of)\b','',entity,flags=re.I).strip() if course else entity
    state='not_completed' if negated else 'planned' if time=='planned' else ACTION_STATES[verb]
    # The incidental phrase "as planned" is not a second future event.
    if re.search(r'\bas planned\b',text,re.I) and not re.search(r'\b(?:will|tomorrow|scheduled|plans? to)\b',text,re.I):
        time='historical' if event_time=='yesterday' else 'current'
        state='not_completed' if negated else ACTION_STATES[verb]
    if verb in {'completed','finished'} and not therapy:
        return []
    if verb=='take' and time!='planned':
        return []
    return [_make(source,span,category,entity,experiencer=experiencer,reporting_basis=basis,
        polarity='absent' if negated else 'affirmed',certainty='explicit',temporality=time,event_time=event_time,
        action_type=action_type,action_state=state,
        completion_scope=None if ordering else 'course' if action_type=='therapy_course' else None if therapy else 'single_event' if state=='completed' else None,
        attributes=attrs)]


def enumerate_source_assertions(source: Source | dict, *, independent_assertions=()) -> EnumerationResult:
    source=Source.model_validate(source)
    atoms=[];proposals=[];origins=[]
    unresolved=[]
    for span in _scope_units(source):
        found=[*_symptoms(source,span),*_actions(source,span)]
        atoms.extend(found)
        proposals.extend({'origin':'native_bounded_grammar','assertion':a.model_dump(mode='json')} for a in found)
        unresolved.append({'unit_id':'unit-'+digest([source.sha256,span.start,span.end])[:20],
            'span':span.model_dump(mode='json'),'enumerated_assertion_ids':[a.claim_id for a in found],
            'status':'PARTIALLY_ENUMERATED' if found else 'UNVERIFIED',
            'reason':'Bounded grammar cannot establish exhaustive meanings even in recognized units.'})
    for raw in independent_assertions:
        atom=Claim.model_validate(raw)
        if (atom.source_id!=source.source_id or atom.patient_id!=source.patient_id or
            atom.encounter_id!=source.encounter_id or not all(source.check_span(s) for s in atom.spans)):
            raise ValueError('Independent source assertion identity/span mismatch')
        atoms.append(atom)
        proposals.append({'origin':'independent_source_enumerator','assertion':atom.model_dump(mode='json')})
    # Duplicate extraction of the same atom is removed, independent source events remain separate.
    selected=[]
    for atom in atoms:
        prior=next((a for a in selected if _equivalent_source_proposals(a,atom)),None)
        if prior is None:
            selected.append(atom)
            origins.append({'assertion_id':atom.claim_id,'proposal_ids':[atom.claim_id]})
        else:
            next(group for group in origins if group['assertion_id']==prior.claim_id)['proposal_ids'].append(atom.claim_id)
    return EnumerationResult(source_hash=source.sha256,assertions=selected,assertion_proposals=proposals,
        assertion_origins=origins,unresolved_units=unresolved)


def overlapping(a,b):
    return any(x.start<y.end and y.start<x.end and x.source_id in {None,b.source_id} and y.source_id in {None,a.source_id}
               for x in a.spans for y in b.spans)


def semantic_key(atom):
    return (atom.source_id,atom.patient_id,atom.encounter_id,atom.category,norm(atom.concept),
        atom.experiencer,atom.polarity,atom.temporality,atom.event_time,atom.action_state,atom.completion_scope,
        digest(atom.attributes))


def align_coverage(atoms: EnumerationResult | list[Claim], claims) -> CoverageResult:
    enum=atoms if isinstance(atoms,EnumerationResult) else EnumerationResult(
        source_hash='',assertions=[Claim.model_validate(a) for a in atoms],unresolved_units=[],semantic_completeness='UNVERIFIED')
    claims=[Claim.model_validate(c) for c in claims]
    aligned=[];missing=[];unsupported=[];unmatched=[];misaligned=[];attribute_gaps=[];unresolved_attributes=[]
    for atom in enum.assertions:
        candidates=[c for c in claims if c.source_id==atom.source_id and c.patient_id==atom.patient_id and
            c.encounter_id==atom.encounter_id and c.category==atom.category and norm(c.concept)==norm(atom.concept) and overlapping(c,atom)]
        matched=[];attribute_checks=[]
        for claim in candidates:
            exact=all(getattr(claim,k) in {'unknown',None,''} or
                      (canonical_dimension(k,getattr(claim,k))==canonical_dimension(k,getattr(atom,k)))
                      for k in ('experiencer','polarity','temporality','event_time','action_state','completion_scope'))
            # An unrepresentable/unverified attribute is not an omitted entity.
            # It remains a separate discrepancy, never an automatically correct value.
            for key,value in claim.attributes.items():
                if value is None:
                    continue
                source_value=atom.attributes.get(key)
                check={'source_assertion_id':atom.claim_id,'claim_id':claim.claim_id,'attribute':key,
                    'proposed_value':value,'source_value':source_value,
                    'status':'SUPPORTED' if source_value==value else 'NOT_COMPARABLE' if source_value is None else 'UNVERIFIED_REPRESENTATION',
                    'reason':'Attributes require an independently represented value; string/structure differences are not a proven clinical omission.'}
                attribute_checks.append(check)
                if check['status']!='SUPPORTED':
                    unresolved_attributes.append(check)
            if exact:
                matched.append(claim.claim_id)
            else:
                misaligned.append(claim.claim_id)
                if any(getattr(claim,k) not in {'unknown',None,''} and
                       getattr(atom,k) not in {'unknown',None,''} and
                       canonical_dimension(k,getattr(claim,k))!=canonical_dimension(k,getattr(atom,k))
                       for k in ('experiencer','polarity','temporality','event_time','action_state','completion_scope')):
                    unsupported.append(claim.claim_id)
        aligned.append({'source_assertion_id':atom.claim_id,'claim_ids':matched,
            'status':('ALIGNED_ATTRIBUTES_UNVERIFIED' if any(c['status']!='SUPPORTED' for c in attribute_checks) else 'ALIGNED') if matched else 'MISALIGNED' if candidates else 'OMISSION_CANDIDATE',
            'candidate_claim_ids':[c.claim_id for c in candidates],
            'attribute_checks':attribute_checks,
            'method':'exact_dimensions_with_unknowns_preserved/1'})
        if matched:
            for key,value in atom.attributes.items():
                if value is not None and not any(c.attributes.get(key)==value for c in candidates if c.claim_id in matched):
                    attribute_gaps.append({'source_assertion_id':atom.claim_id,'claim_ids':matched,
                        'attribute':key,'source_value':value,'status':'NOT_REPRESENTED_IN_TYPED_CLAIM',
                        'reason':'A source attribute without a corresponding typed proposal field is not a missing entity or proven clinical omission.'})
        if not matched:
            missing.append(atom)
    linked={identity for row in aligned for identity in row['claim_ids']}
    for claim in claims:
        if claim.claim_id not in linked and claim.claim_id not in misaligned:
            unmatched.append(claim.claim_id)  # Not enumerated is not proven unsupported.
    aligned_by_id={a['source_assertion_id']:a for a in aligned}
    proposal_groups={p:group['assertion_id'] for group in enum.assertion_origins for p in group['proposal_ids']}
    for proposal in enum.assertion_proposals:
        if proposal['origin']!='independent_source_enumerator':
            continue
        original=Claim.model_validate(proposal['assertion'])
        selected=proposal_groups.get(original.claim_id,original.claim_id)
        linked_ids=aligned_by_id.get(selected,{}).get('claim_ids',[])
        for key,value in original.attributes.items():
            if value is None or not linked_ids:
                continue
            if not any(c.claim_id in linked_ids and c.attributes.get(key)==value for c in claims):
                attribute_gaps.append({'source_assertion_id':selected,'source_proposal_id':original.claim_id,
                    'claim_ids':linked_ids,'attribute':key,'source_value':value,
                    'status':'UNVERIFIED_MODEL_ATTRIBUTE_NOT_REPRESENTED_IN_TYPED_CLAIM',
                    'source_proposal_origin':proposal['origin'],
                    'reason':'Independent model proposals are retained; this attribute is not source confirmed or a proven missing entity.'})
    groups=[];seen=set()
    for claim in claims:
        if claim.claim_id in seen:
            continue
        group=[other.claim_id for other in claims if semantic_key(other)==semantic_key(claim) and overlapping(claim,other)]
        if len(group)>1:
            groups.append(group);seen.update(group)
    return CoverageResult(enumeration=enum,alignments=aligned,omission_candidates=missing,
        duplicate_claim_groups=groups,unsupported_claim_ids=unsupported,
        unmatched_claim_ids=unmatched,
        unrepresented_attributes=attribute_gaps,
        unresolved_attributes=unresolved_attributes,
        misaligned_claim_ids=list(dict.fromkeys(misaligned)),semantic_completeness=enum.semantic_completeness)
