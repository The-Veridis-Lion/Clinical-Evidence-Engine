"""Exact entity-bound execution predicates, extending the existing verifier.

This proves only dimensions expressed by a complete bounded predicate. It does
not infer an entire course, clinical success, indication, document presence or
medical category. The entire original source remains available to scope guards.
"""
from __future__ import annotations

import re

from ..coverage import _scope_units, inspect_source_context, norm, overlapping, source_units
from ..models import Claim, Source, Span, digest
from ..verifier import _compare

VERSION = 'explicit-source-action/1'
ROLE = re.compile(r'^\s*(?:\[(patient|doctor|clinician|nurse|family)\]|(patient|doctor|clinician|nurse|family):)\s*',re.I)
ACTIVE = re.compile(r'^(?:yes,\s*)?(?P<actor>(?:the\s+)?patient|he|she|i)\s+(?:further\s+)?(?P<verb>underwent|received)\s+(?P<object>.+)$',re.I)
PASSIVE = re.compile(r'^(?P<object>.+?)\s+(?:was|were|had been)\s+(?P<negative>not\s+)?(?P<verb>performed|administered)(?P<tail>.*)$',re.I)
UNRESOLVED = re.compile(r'\b(?:if|unless|whether|would|could|might|may|possible|possibly|hypothetical|fictional|simulated|simulation|dream|example|planned|scheduled|should|must|supposed|appeared|believed|denied|deny|never)\b|\?',re.I)
OTHER = re.compile(r'\b(?:mother|father|sister|brother|wife|husband|another patient|someone else)\b',re.I)
TAIL = re.compile(r'\s+(?:which\s+(?:showed|revealed)\b|in\s+(?:a|an|the)\s+|(?:\d+|one|two|three|four|six|eight|twelve)\s+(?:day|week|month|year)s?\s+(?:after|before)\b|(?:today|yesterday|previously)\b)',re.I)


def _known_tail(tail):
    return bool(not tail or re.fullmatch(
        r'\s+(?:which\s+(?:showed|revealed)\s+.+|'
        r'in\s+(?:a|an|the)\s+(?:[a-z]+\s+){0,8}(?:clinic|hospital|department|center|centre|office|theatre|theater)|'
        r'(?:\d+|one|two|three|four|six|eight|twelve)\s+(?:day|week|month|year)s?\s+(?:after|before)\s+(?:the\s+)?(?:first|second|previous|prior|last)\s+(?:operation|procedure|visit|encounter)|'
        r'today|yesterday|previously)',tail,re.I))


def _atoms(source):
    for unit in _scope_units(source):
        label=ROLE.match(unit.quote)
        role=(label[1] or label[2]).casefold() if label else None
        text=(unit.quote[label.end():] if label else unit.quote).strip().rstrip('.!')
        if UNRESOLVED.search(text) or OTHER.search(text):
            continue
        # A non-conditional topic adjunct supplies no clinical assertion; the
        # complete following passive predicate must independently name the entity.
        text=re.sub(r'^(?:regarding(?:\s+to)?|concerning)\s+[^,;]+,\s*','',text,flags=re.I)
        active=ACTIVE.fullmatch(text)
        passive=PASSIVE.fullmatch(text)
        if active:
            actor=norm(active['actor'])
            if actor=='i' and role!='patient':
                continue
            if actor in {'he','she'} and (source.input_kind!='note' or OTHER.search(source.text)):
                continue
            body=active['object']
            split=TAIL.search(body)
            if split and not _known_tail(body[split.start():]):
                continue
            entity=body[:split.start()] if split else body
            basis='patient_report' if actor=='i' else 'documented_history'
            state='completed'
            action_type='procedure_event' if active['verb'].casefold()=='underwent' else None
        elif passive:
            # Unlabelled clinical-note patient context is retained, while a
            # dialogue needs an explicit patient actor and remains out of scope.
            if source.input_kind!='note' or role not in {None,'doctor','clinician','nurse'}:
                continue
            if passive['tail'].strip() and not re.fullmatch(r'\s+(?:today|yesterday|previously)',passive['tail'],re.I):
                continue
            entity=passive['object']
            basis='documented_history'
            state='not_completed' if passive['negative'] else 'completed'
            action_type='procedure_event' if passive['verb'].casefold()=='performed' else 'administration_event'
        else:
            continue
        entity=norm(re.sub(r'^(?:a|an|the)\s+','',entity,flags=re.I))
        if (not entity or len(entity.split())>16 or re.search(r'\b(?:and|or|nor|not|no|without|it|them|that|course)\b',entity,re.I)
                or re.search(r'\b(?:\d+\s*(?:mg|mcg|ml|g)|daily|weekly)\b',entity,re.I)):
            continue  # Conjoined, quantified and entire-course events need separate scope.
        when=re.search(r'\b(today|yesterday)\b',text,re.I)
        # Past execution is explicit; an exact event date is not manufactured.
        yield Claim(claim_id='event-'+digest([source.sha256,unit.start,entity])[:24],
            source_id=source.source_id,patient_id=source.patient_id,encounter_id=source.encounter_id,
            category='unknown',concept=entity,spans=[unit],experiencer='patient',
            reporting_basis=basis,polarity='present' if state=='completed' else 'absent',
            certainty='explicit',temporality='historical' if not when or norm(when[1])=='yesterday' else 'unknown',
            event_time=norm(when[1]) if when else None,action_type=action_type,action_state=state,
            completion_scope='single_event' if state=='completed' else None)


def apply_explicit_action(source,claim,base,*,reviews=()):
    source=Source.model_validate(source);claim=Claim.model_validate(claim)
    if (reviews or base.risk_route=='MISSING_EVIDENCE' or base.status in {'CONTRADICTED','CONFLICTED'}
            or claim.category not in {'procedure','medication','treatment'}
            or claim.experiencer!='patient' or claim.action_state not in {'completed','not_completed'}):
        return base
    atoms=list(_atoms(source))
    own=[atom for atom in atoms if norm(atom.concept)==norm(claim.concept) and overlapping(atom,claim)]
    if len(own)!=1:
        return base
    atom=own[0]
    if (claim.temporality not in {'unknown',atom.temporality} and atom.temporality!='unknown'
            or claim.event_time and atom.event_time and norm(claim.event_time)!=norm(atom.event_time)):
        return base
    unresolved,context=inspect_source_context(source,claim,atom)
    from .local_scope import _preceding_scope
    context.extend(_preceding_scope(source,claim))
    if unresolved or context:
        return base
    # Retain every same-entity mention. A second source event, unresolved
    # question, amendment or temporal relation cannot be erased by local parsing.
    mentions=[unit for unit in source_units(source)
              if re.search(r'(?<!\w)'+re.escape(norm(claim.concept))+r'(?!\w)',unit.quote,re.I)]
    if (len([a for a in atoms if norm(a.concept)==norm(claim.concept)])!=1
            or any(not overlapping(atom,claim.model_copy(update={'spans':[unit]})) for unit in mentions)):
        return base
    checks=_compare(claim,atom,source_interpretation_version='bounded-source-grammar/5')
    # A single execution neither contradicts nor proves a whole course. This
    # extension supplies no new counterclaims when another dimension is unknown.
    for check in checks:
        if check.status=='CONTRADICTED':
            check.status='UNVERIFIED'
            check.reason='The bounded event does not establish this proposed dimension; no complete-source contradiction is inferred.'
    if not all(any(check.dimension==name and check.status=='SUPPORTED' for check in checks)
               for name in ('concept','experiencer','polarity','action_state')):
        return base
    full=Span(start=0,end=len(source.text),quote=source.text,source_id=source.source_id)
    uncertainty=[c.dimension for c in checks if c.status=='UNVERIFIED']
    return base.model_copy(update={'status':'INSUFFICIENT_EVIDENCE' if uncertainty else 'SUPPORTED_BY_SOURCE',
        'dimension_checks':checks,'source_assertion':atom,'supporting_spans':atom.spans,
        'counter_spans':[],'context_spans':[full],'risk_route':'REVIEW_REQUIRED','calibration_id':None,
        'method':VERSION,'uncertainty':uncertainty,
        'reasons':['Complete original predicate and literal entity support the execution dimension. Medical category, unproved attributes and whole-course completion remain independently unverified.']})
