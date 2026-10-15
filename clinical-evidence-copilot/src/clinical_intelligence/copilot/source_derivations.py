"""Bounded, source-preserving proposals for an explicit program reprocessing event.

This module does not certify clinical truth or mutate a packet. It exposes a
previously composite, explicitly negated execution state and removes only clear
time-point/duration representation errors. Applying the plan must create an
audited version and run the normal source verifier again.
"""
import copy
import re

from .models import digest
from .semantics import checked_records


VERSION = 'source-proposal-derivations/1'
_LIFE = r'(?:early |late )?(?:childhood|adolescence|infancy|adulthood)'
_LIFE_POINT = re.compile(rf'(?:(?:in|during) )?{_LIFE}|as a (?:child|teenager|young adult)', re.I)
_RELATIVE_POINT = re.compile(
    r'(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve) '
    r'(?:days?|weeks?|months?|years?|hours?|minutes?) (?:before|after) .+', re.I)
_CALENDAR_POINT = re.compile(r'(?:today|yesterday|tomorrow|(?:next|last) (?:week|month|year)|\d{4}-\d{2}-\d{2})', re.I)
_FREQUENCY = re.compile(r'(?:daily|nightly|weekly|monthly|(?:once|twice|three times) (?:daily|weekly|a day|a week)|every (?:\d+|one|two|three|four|six|eight|twelve) (?:hours?|days?|weeks?|months?))', re.I)
_NUMBER = r'(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
_SPAN_VALUE = re.compile(rf'{_NUMBER}(?:\s+to\s+{_NUMBER})?\s+(?:hours?|days?|weeks?|months?|years?)', re.I)
_NOT_STARTED = re.compile(r'\b(?:not\s+(?:yet\s+)?|(?:hasn|haven|isn|aren)[\'’]t\s+(?:yet\s+)?)(?:been\s+)?(?:started|begun|initiated)\b', re.I)
_UNCERTAIN = re.compile(r'\b(?:if|unless|might|may|could|would|unclear|unknown|possibly|perhaps|reported|denied)\b', re.I)
_FAMILY = re.compile(r'\b(?:mother|father|sister|brother|daughter|son|grandmother|grandfather|aunt|uncle|wife|husband|family)\b', re.I)
_OTHER_SUBJECT = re.compile(r'\b(?:another patient|neighbor|neighbour|friend|roommate)\b', re.I)
_UNIT_BREAK = re.compile(r'(?<=[.!?;])\s+|\n|\b(?:and|but|while|whereas)\b', re.I)


def _normal(value):
    return ' '.join((value or '').casefold().split()).rstrip('. ')


def _spans(packet, fact):
    spans = []
    for span in fact.original_fact.get('provenance', []):
        if not (0 <= span['start'] < span['end'] <= len(packet.source.text)
                and packet.source.text[span['start']:span['end']] == span['quote']
                and span['document_id'] == packet.source.document_id):
            raise ValueError('Program derivation source differs from the immutable original')
        spans.append(copy.deepcopy(span))
    return spans


def _bound_duration_spans(packet, item, spans, value):
    """Require one local entity/subject scope; full sources still reach verification.

    This is a binding guard for a representation correction, not an entailment
    certificate. Ambiguous aliases or multiple entities are left unchanged.
    """
    concept = item.original_fact.get('concept')
    experiencer = item.original_fact.get('experiencer')
    if not concept or experiencer not in {'patient', 'family'}:
        return []
    anchor = re.compile(rf'(?<!\w){re.escape(concept)}(?!\w)', re.I)
    selected = []
    for span in spans:
        for unit in _UNIT_BREAK.split(span['quote']):
            if value not in _normal(unit) or not anchor.search(unit):
                continue
            if _OTHER_SUBJECT.search(unit) or (bool(_FAMILY.search(unit)) != (experiencer == 'family')):
                continue
            other_entity = any(other.fact_id != item.fact_id
                and _normal(other.original_fact.get('concept')) != _normal(concept)
                and other.original_fact.get('concept')
                and re.search(rf'(?<!\w){re.escape(other.original_fact["concept"])}(?!\w)', unit, re.I)
                for other in packet.facts)
            if other_entity:
                continue
            selected.append(span)
            break
    return selected


def _duration_update(record, spans):
    before = record['semantics']
    duration = before.get('duration')
    if not duration:
        return None
    value = _normal(duration)
    cited = ' '.join(span['quote'] for span in spans)
    if value not in _normal(cited):
        return None  # A missing/wrong citation is not permission to repair it.
    after = copy.deepcopy(before)
    if _FREQUENCY.fullmatch(value) and before.get('frequency') in {None, duration}:
        after['frequency'] = duration
        after['duration'] = None
        return after, 'explicit_repetition_is_frequency_not_elapsed_duration'
    life_point = _LIFE_POINT.fullmatch(value)
    if life_point:
        # "Since childhood" can describe an elapsed history. Do not replace it
        # with a point-in-life interpretation merely because one token matches.
        bare = re.sub(r'^(?:in|during) ', '', value)
        if re.search(rf'\bsince\s+{re.escape(bare)}\b', cited, re.I):
            return None
        source_point = re.search(rf'\b(?:in|during)\s+{re.escape(bare)}\b', cited, re.I)
        if not source_point and not value.startswith('as a '):
            return None
        # Reclassifying a disputed old field must not create a new event-time
        # assertion. Only remove a duplicated, already explicit point proposal.
        if before.get('event_time') is None or bare not in _normal(before['event_time']):
            return None
    elif (_RELATIVE_POINT.fullmatch(value) or _CALENDAR_POINT.fullmatch(value)
            or (_SPAN_VALUE.fullmatch(value) and before['action_state'] == 'planned'
                and re.search(rf'\bin\s+{re.escape(value)}\b', cited, re.I))):
        if _normal(before.get('event_time')) != value:
            return None
        if re.search(rf'\b(?:for|throughout)\s+{re.escape(value)}\b', cited, re.I):
            return None
    else:
        return None
    after['duration'] = None
    return after, 'explicit_time_point_is_not_elapsed_duration'


def _unstarted_proposal(packet, item, semantics, spans):
    raw = item.original_fact
    if (raw['category'] not in {'medication', 'procedure', 'treatment'}
            or not raw.get('concept') or raw['temporality'] != 'planned'
            or not semantics or semantics['action_state'] != 'planned'
            or not _NOT_STARTED.search(raw.get('clinical_status') or '')):
        return None
    concept = raw['concept']
    # This is deliberately a small syntactic derivation, not a replacement
    # extractor. No aliases, patient role inference or cross-sentence coreference.
    for span in spans:
        if span['quote'].count(';') != 1 or _UNCERTAIN.search(span['quote']):
            continue
        left, right = [part.strip().rstrip('.') for part in span['quote'].split(';')]
        if not re.fullmatch(rf'{re.escape(concept)}\s+(?:is|are|has been|have been)\s+'
                r'(?:scheduled|planned|arranged|booked)\b[^;.!?]+', left, re.I):
            continue
        if re.search(r'\band\b|,', left, re.I):
            continue  # A second object can make "the course" ambiguous.
        target = rf'(?:the |this |its )?(?:course|treatment|therapy|regimen|procedure|medication|{re.escape(concept)})'
        if not re.fullmatch(target + r'\s+(?:(?:has|have|is|are)\s+not\s+(?:yet\s+)?|(?:hasn|haven|isn|aren)[\'’]t\s+(?:yet\s+)?)'
                r'(?:been\s+)?(?:started|begun|initiated)(?:\s+(?:yet|currently|as of today))?', right, re.I):
            continue
        # The already retained proposal must itself contain the negated start
        # predicate. Merely seeing an unextracted sentence does not pass this gate.
        if not _NOT_STARTED.search(right):
            continue
        derived = copy.deepcopy(raw)
        derived.update(polarity='absent', temporality='current', clinical_status=right,
                       attributes=None)
        course = bool(re.search(r'\b(?:course|regimen)\b', right, re.I))
        event = {**semantics, 'frequency': None,
                 'event_time': 'as of today' if right.casefold().endswith('as of today') else None,
                 'duration': None, 'action_state': 'not_completed',
                 'action_type': semantics.get('action_type') if course and 'course' in (semantics.get('action_type') or '') else None,
                 'completion_scope': 'course' if course else None}
        return derived, event, span
    return None


def derive_source_proposals(packet):
    """Return changes for a new version; the original packet stays byte-identical.

    A result is a source-supported *proposal*, never an automatic eligibility or
    human review record. Normal source verification and material rules still run.
    Repeated application on an already derived snapshot yields no duplicate event.
    """
    packet.verify()
    records = checked_records(packet)
    result = {'version': VERSION, 'source_sha256': packet.source.sha256,
              'parent_content_hash': packet.content_hash,
              'derived_facts': [], 'semantic_updates': [], 'unresolved': []}
    for item in packet.facts:
        spans = _spans(packet, item)
        record = records.get(item.fact_id)
        current = item.assertion.model_dump()
        if current != item.original_fact:
            result['unresolved'].append({'fact_id': item.fact_id,
                'dimension': 'program_derivation.binding',
                'changed_dimensions': sorted(key for key in current.keys() | item.original_fact.keys()
                    if current.get(key) != item.original_fact.get(key)),
                'reason': 'The current assertion differs from the retained original proposal; program derivation must not restore superseded raw content.',
                'source_spans': spans, 'applied': False})
            continue
        if record is not None and record['origin'].startswith('targeted_semantics_correction'):
            result['unresolved'].append({'fact_id': item.fact_id,
                'dimension': 'program_derivation.semantic_binding',
                'review_origin': record['origin'],
                'reason': 'An explicit targeted semantic correction supersedes the extraction proposal; program derivation must not overwrite it.',
                'source_spans': spans, 'applied': False})
            continue
        if record is not None:
            duration = record['semantics'].get('duration')
            bound_spans = _bound_duration_spans(packet, item, spans, _normal(duration)) if duration else []
            update = _duration_update(record, bound_spans)
            if update is not None:
                after, rule = update
                result['semantic_updates'].append({'fact_id': item.fact_id,
                    'before': copy.deepcopy(record['semantics']), 'after': after,
                    'source_spans': bound_spans, 'rule': rule})
            elif duration and (_LIFE_POINT.fullmatch(_normal(duration))
                    or _FREQUENCY.fullmatch(_normal(duration))
                    or _RELATIVE_POINT.fullmatch(_normal(duration))
                    or _CALENDAR_POINT.fullmatch(_normal(duration))):
                result['unresolved'].append({'fact_id': item.fact_id,
                    'dimension': 'attributes.duration', 'proposed_value': duration,
                    'reason': 'Representation may be a time point or frequency; entity, subject, predicate or existing field binding is not established by this derivation.',
                    'source_spans': spans, 'applied': False})
        semantics = record['semantics'] if record is not None else None
        derived = _unstarted_proposal(packet, item, semantics, spans)
        if derived is None:
            continue
        raw, event, source_span = derived
        existing = [other for other in packet.facts if other.fact_id != item.fact_id
            and _normal(other.original_fact.get('concept')) == _normal(raw['concept'])
            and other.original_fact.get('experiencer') == raw['experiencer']
            and other.original_fact.get('temporality') == 'current'
            and (records.get(other.fact_id, {}).get('semantics', {}).get('action_state') == 'not_completed'
                 or _NOT_STARTED.search(other.original_fact.get('clinical_status') or ''))]
        if existing:
            continue
        rule = 'explicit_composite_planned_and_current_unstarted_execution'
        identity = [VERSION, packet.source.sha256, item.fact_id, source_span, rule]
        result['derived_facts'].append({'derivation_id': 'derive-' + digest(identity)[:20],
            'original_fact': raw, 'semantics': event, 'parent_fact_id': item.fact_id,
            'source_spans': [source_span], 'rule': rule,
            'polarity_object': 'execution_of_named_intervention',
            'clinical_verification': 'NOT_GRANTED_BY_DERIVATION'})
    return result
