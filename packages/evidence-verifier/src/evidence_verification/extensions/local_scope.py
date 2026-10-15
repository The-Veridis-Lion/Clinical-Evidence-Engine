"""Small source proofs for local clauses, retaining the complete original context.

This is an extension of the existing verifier, not a clinical extractor. Literal
symptom clauses and numeric measurements have a declared, independently testable
boundary. No diagnosis, severity interpretation, event completion or document
existence is inferred here. Unknown surrounding uses of the same entity prevent
automatic handling rather than being cropped away.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..models import Calibration, Claim, DimensionCheck, Source, Span, digest
from ..coverage import _scope_units, canonical_dimension, inspect_source_context, norm, overlapping, source_units
from ..verifier import _compare, _contradictory_atoms

VERSION = 'source-local-proof/1'
METHOD = 'literal-local-source-proof/1'
SCOPE = 'explicit-patient-symptom-or-numeric-measurement/1'
LABEL = re.compile(r'^\s*(?:\[(?P<bracket>patient|doctor|clinician|nurse|family)\]|(?P<plain>patient|doctor|clinician|nurse|family):)\s*', re.I)
SYMPTOMS = {'cough', 'fever', 'dyspnea', 'breathlessness', 'shortness of breath',
            'chest pain', 'knee pain', 'headache', 'nausea', 'vomiting', 'dizziness',
            'rhinorrhea', 'nasal congestion', 'sneezing', 'tremor', 'fatigue', 'rash',
            'abdominal pain', 'lower abdominal pain', 'palpitations', 'constipation'}
SYMPTOM_CLAUSE = re.compile(
    r'^(?P<subject>(?:the\s+)?patient|I)\s+'
    r'(?P<verb>have been having|has been having|have|has|reports|report|denies|deny|do not have|does not have|don[\'’]t have)\s+'
    r'(?P<body>.+?)\s*[.!]?$', re.I)
DURATION = re.compile(r'\s+for\s+(?P<duration>(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|\d+)\s+(?:days?|weeks?|months?|years?))(?:\s+now)?$', re.I)
MEASUREMENTS = {
    'blood pressure': ('observation', {'blood pressure', 'bp'}, {'mmhg'}),
    'oxygen saturation': ('observation', {'oxygen saturation', 'spo2'}, {'%', 'percent'}),
    'heart rate': ('observation', {'heart rate', 'pulse'}, {'bpm', 'beats/min', 'beats per minute'}),
    'respiratory rate': ('observation', {'respiratory rate'}, {'breaths/min', 'breaths per minute'}),
    'temperature': ('observation', {'temperature', 'body temperature'}, {'c', '°c', 'f', '°f'}),
    'serum white blood cell count': ('laboratory_result', {'serum white blood cell count', 'white blood cell count'}, {'/mm3', '/mm³'}),
    'serum creatinine': ('laboratory_result', {'serum creatinine'}, {'mg/dl'}),
    'serum blood urea nitrogen': ('laboratory_result', {'serum blood urea nitrogen'}, {'mg/dl'}),
}
NUMBER = r'\d+(?:,\d{3})*(?:\.\d+)?(?:/\d+(?:\.\d+)?)?'
MEASUREMENT_CLAUSE = re.compile(
    r"^(?P<subject>(?:the\s+)?patient['’]s\s+|your\s+)?(?P<concept>[a-z0-9 ]+?)\s+"
    r'(?P<verb>is|was)\s+(?P<value>' + NUMBER + r')\s*(?P<unit>[^.!?]+?)(?:\s+(?P<when>today|yesterday))?\s*[.]?$', re.I)
UNKNOWN = {None, '', 'unknown', 'uncertain', 'unspecified', 'not_applicable'}


def _role_text(unit):
    label = LABEL.match(unit.quote)
    return ((label.group('bracket') or label.group('plain')).casefold() if label else None,
            unit.quote[label.end():].strip() if label else unit.quote.strip())


def _atoms(source):
    atoms = []
    for unit in _scope_units(source):
        role, text = _role_text(unit)
        match = SYMPTOM_CLAUSE.fullmatch(text)
        if match and not (norm(match['subject']) == 'i' and role != 'patient'):
            body = match['body'].rstrip('.!')
            when = re.search(r'\s+(today|currently|now)$', body, re.I)
            event_time = 'today' if when and norm(when.group(1)) == 'today' else None
            # 'for a year now' belongs to duration; the source explicitly asserts
            # a continuing present symptom, without inventing an onset date.
            if when and norm(when.group(1)) != 'now':
                body = body[:when.start()]
            duration = DURATION.search(body)
            attrs = {'duration': norm(duration['duration'])} if duration else {}
            if duration:
                body = body[:duration.start()]
            elif when:
                body = body[:when.start()]
            terms = [norm(re.sub(r'^(?:a|an|any|the)\s+', '', term.strip(), flags=re.I))
                     for term in re.split(r'\s*,\s*|\s+and\s+', body, flags=re.I)]
            if terms and all(term in SYMPTOMS for term in terms):
                verb = norm(match['verb'])
                basis = 'patient_report' if role == 'patient' or verb in {'reports', 'report', 'denies', 'deny'} else 'documented_history'
                polarity = 'absent' if verb in {'denies', 'deny', 'do not have', 'does not have', "don't have", 'don’t have'} else 'present'
                for term in terms:
                    atoms.append(Claim(claim_id='local-'+digest([source.sha256,unit.start,term])[:24],
                        source_id=source.source_id,patient_id=source.patient_id,encounter_id=source.encounter_id,
                        spans=[unit],category='symptom',concept=term,experiencer='patient',
                        reporting_basis=basis,polarity=polarity,certainty='explicit',temporality='current',
                        event_time=event_time,attributes=attrs))
        match = MEASUREMENT_CLAUSE.fullmatch(text)
        if not match:
            continue
        entry = next(((key, data) for key, data in MEASUREMENTS.items() if norm(match['concept']) in data[1]), None)
        if entry is None:
            continue
        concept, (category, aliases, units) = entry
        subject = norm(match['subject'])
        # An unlabeled first-person or clinician's own measurement is not a
        # patient measurement. 'Your' requires an actual clinician turn.
        if subject == 'your' and role not in {'doctor', 'clinician', 'nurse'}:
            continue
        if not subject and (source.input_kind != 'note' or role not in {None, 'doctor', 'clinician', 'nurse'}):
            continue
        unit_value = norm(match['unit'])
        if unit_value not in units:
            continue
        temporal = 'historical' if norm(match['verb']) == 'was' or norm(match['when']) == 'yesterday' else 'current'
        atoms.append(Claim(claim_id='local-'+digest([source.sha256,unit.start,concept])[:24],
            source_id=source.source_id,patient_id=source.patient_id,encounter_id=source.encounter_id,
            spans=[unit],category=category,concept=concept,experiencer='patient',
            reporting_basis='clinician_observation',polarity='present',certainty='explicit',
            temporality=temporal,event_time=norm(match['when']) or None,
            attributes={'value':match['value'], 'unit':match['unit']}))
    return atoms


def _concept(value):
    value = norm(value)
    return next((key for key,data in MEASUREMENTS.items() if value in data[1]), value)


def _number(value):
    try:
        return tuple(Decimal(part.replace(',', '')) for part in str(value).split('/'))
    except InvalidOperation:
        return None


def _preceding_scope(source, claim):
    """A document instruction is distinct from an unrelated event's 'next week'."""
    from .contextual import _preceding_qualifiers
    contexts = []
    for unit in _preceding_qualifiers(source, claim):
        heading = re.fullmatch(r'\s*(?:childhood|past|historical|remote|previous)\s+(?:history|symptoms|events|visit|encounter)(?:\s+(?:below|follows|recorded below))?\s*[:.!]?\s*', unit.quote, re.I)
        instruction = re.search(r'\b(?:next\s+(?:sentence|statement|example|scenario|case|quotation|quote|section|symptoms?|events?)|following|below|follows|recorded below)\b', unit.quote, re.I)
        if heading or instruction:
            contexts.append(unit)
    return contexts


def _checks(claim, atom):
    proposed = claim.model_copy(update={'concept':atom.concept})
    checks = _compare(proposed, atom, source_interpretation_version='bounded-source-grammar/4')
    for check in checks:
        if check.dimension == 'concept':
            check.proposed = claim.concept
            check.reason = 'Literal concept or declared measurement abbreviation; no clinical synonym inference.'
        elif check.dimension == 'attributes.value' and atom.category in {'observation', 'laboratory_result'}:
            if _number(check.proposed) is not None and _number(check.proposed) == _number(check.source_value):
                check.status = 'SUPPORTED'
                check.reason = 'Exact numeric value, allowing thousands separators only.'
        elif check.dimension == 'attributes.unit' and _concept(atom.concept) == 'oxygen saturation':
            if norm(check.proposed) in {'%', 'percent'} and norm(check.source_value) in {'%', 'percent'}:
                check.status = 'SUPPORTED'
                check.reason = 'Explicit percent representation equivalence.'
    return checks


def apply_local_scope(source, claim, base, *, calibrations=(), reviews=()):
    """Return a new proof only inside the finite source grammar and context guard."""
    source = Source.model_validate(source); claim = Claim.model_validate(claim)
    if reviews or base.risk_route == 'MISSING_EVIDENCE' or base.status in {'CONTRADICTED', 'CONFLICTED'}:
        return base
    if claim.action_type or claim.action_state not in UNKNOWN or claim.completion_scope:
        return base
    atoms = _atoms(source)
    target = _concept(claim.concept)
    own = [a for a in atoms if _concept(a.concept) == target and overlapping(a, claim)]
    if len(own) != 1:
        return base
    atom = own[0]
    # No local winner is chosen by dropping other times, patients, headings,
    # questions, later negations or unresolved co-reference from the document.
    unresolved, context = inspect_source_context(source, claim, atom)
    context.extend(_preceding_scope(source, claim))
    units = list(source_units(source))
    for index, unit in enumerate(units):
        if not any(span.start < unit.end and unit.start < span.end for span in atom.spans):
            continue
        for adjacent in units[index:index+2]:
            if (re.search(r'\b(?:this|that|the)\s+(?:value|result|measurement|reading|statement)\b', adjacent.quote, re.I)
                    and re.search(r'\b(?:not|never|no|hypothetical|example|conditional|refers? to|another|someone else)\b', adjacent.quote, re.I)):
                context.append(adjacent)
    if unresolved or context:
        return base
    aliases = MEASUREMENTS[target][1] if target in MEASUREMENTS else {target}
    for unit in units:
        if not any(re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',unit.quote,re.I) for alias in aliases):
            continue
        if not any(_concept(a.concept) == target and overlapping(a, claim.model_copy(update={'spans':[unit]})) for a in atoms):
            return base
    same = [a for a in atoms if _concept(a.concept) == target]
    # Multiple source events for an identical concept require an explicit
    # unambiguous time match; the simple Auto grammar deliberately abstains.
    if len(same) != 1:
        return base
    checks = _checks(claim, atom)
    if any(c.status == 'CONTRADICTED' for c in checks):
        return base  # This extension does not create new clinical counterclaims.
    unknown = [c.dimension for c in checks if c.status == 'UNVERIFIED']
    full = Span(start=0,end=len(source.text),quote=source.text,source_id=source.source_id)
    checks.append(DimensionCheck(dimension='source_context',status='SUPPORTED',
        proposed='full_original_source_retained',source_value='full_original_source_retained',
        reason='Complete original source, original labels, adjacent qualifiers and every same-entity mention inspected.',spans=[full]))
    status = 'INSUFFICIENT_EVIDENCE' if unknown else 'SUPPORTED_BY_SOURCE'
    route = 'REVIEW_REQUIRED'; calibration_id = None
    if not unknown:
        for raw in calibrations:
            calibration = Calibration.model_validate(raw)
            if (calibration.method == METHOD and calibration.scope == SCOPE and claim.category in calibration.categories
                    and calibration.measured_precision >= calibration.minimum_precision):
                route = 'AUTO_ACCEPT_ELIGIBLE'; calibration_id = calibration.calibration_id
                break
    return base.model_copy(update={'status':status, 'dimension_checks':checks,
        'supporting_spans':atom.spans if not unknown else [], 'counter_spans':[],
        'source_assertion':atom, 'context_spans':[full], 'risk_route':route,
        'calibration_id':calibration_id, 'method':METHOD, 'uncertainty':unknown,
        'reasons':['Explicit source clause independently establishes the proposed main assertion; any unresolved attributes remain separately listed.']})
