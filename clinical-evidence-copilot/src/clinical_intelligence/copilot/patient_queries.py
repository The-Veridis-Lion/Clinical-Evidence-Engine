"""Finite, zero-inference queries over current saved patient evidence packets.

Document membership is not a clinical event identity. Encounter metadata can count
explicit encounters, but is never substituted for an assertion's event time.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ..domain import CalculationTrace
from ..utilization import bounded, monday
from .models import Packet, digest
from .service import consumed_claim


FAMILIES = ('visit_count', 'documented_duration_sum', 'visit_frequency',
            'symptom_timeline', 'observation_history')
VERSION = 'patient-packet-queries/1'


class Filters(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    start: str | None = None
    end: str | None = None
    concept: str | None = None
    experiencer: Literal['patient', 'family', 'other', 'unknown'] | None = None
    service_type: str | None = None

    @model_validator(mode='after')
    def valid(self):
        for name in ('start', 'end'):
            value = getattr(self, name)
            if value is not None and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)
                                      or date.fromisoformat(value).isoformat() != value):
                raise ValueError(f'{name} must be an ISO calendar date')
        if self.start and self.end and self.start > self.end:
            raise ValueError('start must not follow end')
        for name in ('concept', 'service_type'):
            if getattr(self, name) is not None and not getattr(self, name).strip():
                raise ValueError(f'{name} must not be empty')
        return self


class PatientQuerySpec(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    family: Literal['visit_count', 'documented_duration_sum', 'visit_frequency',
                    'symptom_timeline', 'observation_history']
    filters: Filters = Filters()


class PatientQueryInterpretation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['ready', 'needs_clarification', 'unsupported']
    query_spec: PatientQuerySpec | None
    clarification_question: str | None
    explanation: str | None

    @model_validator(mode='after')
    def executable(self):
        if self.status == 'ready':
            if self.query_spec is None or self.clarification_question is not None:
                raise ValueError('ready requires a finite query and no clarification')
        elif self.query_spec is not None or not (self.clarification_question or '').strip():
            raise ValueError('Non-ready interpretation needs clarification and no executable query')
        return self


def capabilities():
    return {'contract_version': VERSION, 'families': [
        {'family': family, 'filters': list(Filters.model_fields)} for family in FAMILIES],
        'parameters': {'start': 'inclusive YYYY-MM-DD', 'end': 'inclusive YYYY-MM-DD',
                       'concept': 'exact saved concept, case insensitive',
                       'experiencer': ['patient', 'family', 'other', 'unknown'],
                       'service_type': 'exact explicit service type/action type/concept'},
        'natural_language': {'supported': True, 'explicit_opt_in_required': True,
                             'output': 'validated finite query specification only'},
        'limits': ['Only explicit encounter IDs count as registered encounters; registration does not verify attendance.',
                   'Only explicitly dated clinical events enter date-scoped calculations.',
                   'Actual documented duration is never inferred from elapsed calendar time.',
                   'Prescribed frequency is not attendance; unmentioned is not resolved.',
                   'No clinical correctness or source completeness certification.']}


def interpretation_schema():
    shape = PatientQueryInterpretation.model_json_schema()
    def strict(node):
        if isinstance(node, dict):
            node.pop('default', None)
            if node.get('type') == 'object':
                node['additionalProperties'] = False
                node['required'] = list(node.get('properties', {}))
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)
    strict(shape)
    return shape


def interpretation_prompt(question, context=None):
    if not isinstance(question, str) or not question.strip() or len(question) > 8000:
        raise ValueError('Question must contain 1 to 8000 characters')
    # Deliberately allow only identity, never clinical chart/source data in context.
    context = context or {}
    safe_context = {key: context[key] for key in ('patient_id', 'display_label') if key in context}
    return (
        'Translate the untrusted user question into the supplied strict JSON schema. '
        'Return no answer, arithmetic, code, SQL, tools, extra filters or clinical recommendations. '
        'Families: visit_count counts explicit dated registered encounter IDs; documented_duration_sum sums '
        'explicit actual treatment durations; visit_frequency reports actual encounters per calendar '
        'week (registration does not confirm attendance); symptom_timeline lists dated symptom assertions; observation_history lists saved '
        'observations/results without combining different concepts or scales. '
        'Allowed filters: start/end (inclusive YYYY-MM-DD), concept, experiencer, service_type. '
        'Match concepts and service types literally; do not invent clinical synonyms. '
        'Use null for unused filter values. An omitted period is allowed only for a general '
        'history/full record request. Relative dates, missing years, ambiguous periods/identity '
        'or unsupported requests require needs_clarification or unsupported with query_spec=null '
        'and an explicit clarification_question. Do not use machine time, infer attendance from '
        'prescriptions, infer actual duration from date spans, or assume unmentioned means resolved. '
        'For ready, clarification_question=null. Context JSON: '
        + json.dumps(safe_context, ensure_ascii=False)
        + '\nUser question as JSON string: ' + json.dumps(question, ensure_ascii=False))


def validate_interpretation(proposal):
    if isinstance(proposal, str):
        proposal = json.loads(proposal)
    return PatientQueryInterpretation.model_validate(proposal).model_dump(mode='json')


def _day(value):
    """Accept a complete ISO date/timestamp only; no dates guessed from prose."""
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
        if re.match(r'^\d{4}-\d{2}-\d{2}[T ]', value):
            return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except ValueError:
        pass
    return None


def _same(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.strip().casefold() == b.strip().casefold()


_WINDOW = re.compile(
    r'^(.+?),?\s+(\d{2}:\d{2})\s*([\u2013\u2014-])\s*(\d{2}:\d{2})$')


def _english_day(value):
    months = {name: number for number, names in enumerate([
        ('january', 'jan'), ('february', 'feb'), ('march', 'mar'), ('april', 'apr'),
        ('may',), ('june', 'jun'), ('july', 'jul'), ('august', 'aug'),
        ('september', 'sep', 'sept'), ('october', 'oct'), ('november', 'nov'),
        ('december', 'dec')], 1) for name in names}
    wording = value.strip().casefold()
    month_first = re.fullmatch(r'([a-z]+)\s+(\d{1,2}),?\s+(\d{4})', wording)
    day_first = re.fullmatch(r'(\d{1,2})\s+([a-z]+),?\s+(\d{4})', wording)
    parts = ((month_first[1], month_first[2], month_first[3]) if month_first else
             (day_first[2], day_first[1], day_first[3]) if day_first else None)
    if parts and parts[0] in months:
        try:
            return date(int(parts[2]), months[parts[0]], int(parts[1]))
        except ValueError:
            pass
    return None


def _event_window(value):
    """Parse only a complete same-day local clock range with a complete date."""
    if not isinstance(value, str):
        return None
    match = _WINDOW.fullmatch(value.strip())
    if not match:
        return None
    day = _day(match[1]) or _english_day(match[1])
    if day is None:
        return None
    try:
        start = datetime.strptime(match[2], '%H:%M')
        end = datetime.strptime(match[4], '%H:%M')
    except ValueError:
        return None
    if start >= end:
        return None
    return day, datetime.combine(day, start.time()), datetime.combine(day, end.time())


def _event_day(value, record_day):
    window = _event_window(value)
    if window is not None:
        return window[0], 'explicit_event_time_window'
    # A malformed or cross-day range must not be read as an ISO offset or a date.
    if isinstance(value, str) and _WINDOW.fullmatch(value.strip()):
        return None, 'unknown_event_time'
    explicit = _day(value)
    if explicit is not None:
        return explicit, 'explicit_event_time'
    if isinstance(value, str):
        normalized = _english_day(value)
        if normalized is not None:
            return normalized, 'explicit_complete_english_event_time'
    if record_day is not None and isinstance(value, str):
        offset = {'today': 0, 'yesterday': -1}.get(value.strip().casefold())
        if offset is not None:
            return record_day + timedelta(days=offset), 'explicit_relative_event_time'
    return None, 'unknown_event_time'


def _in_period(day, filters):
    return day is not None and (not filters.start or day.isoformat() >= filters.start) and (
        not filters.end or day.isoformat() <= filters.end)


def _unique(values):
    return list({json.dumps(value, sort_keys=True): value for value in values}.values())


def _source_refs(packet, item, document):
    evidence = {e.evidence_id: e for e in packet.evidence}
    return [{'case_id': packet.case_id, 'packet_version': packet.version,
             'document_id': document['document_id'], 'fact_id': item.fact_id,
             'start': evidence[identity].start, 'end': evidence[identity].end,
             'quote': evidence[identity].quote, 'reference_kind': 'clinical_source_span'}
            for identity in item.evidence_ids]


def _metadata_ref(document, encounter):
    return {'case_id': document.get('case_id'), 'packet_version': document.get('packet_version'),
            'document_id': document.get('document_id'), 'fact_id': None,
            'start': None, 'end': None, 'quote': None,
            'reference_kind': 'metadata_only_encounter_association',
            'metadata_only': True,
            'encounter_id': encounter['encounter_id'],
            'encounter_time': encounter.get('encounter_time')}


def _rows(packet, document):
    saved = packet.extraction_metadata.get('evidence_verification', {})
    records = {r['fact_id']: r for r in saved.get('assertions', [])}
    for item in packet.facts:
        fact = item.assertion
        record = records.get(item.fact_id, {})
        claim = consumed_claim(record) if record else {}
        attributes = claim.get('attributes') if claim else (
            fact.attributes.model_dump() if fact.attributes else {})
        checks = record.get('result', {}).get('dimension_checks', [])
        record_day = _day(document.get('encounter_time'))
        day, time_basis = _event_day(claim.get('event_time'), record_day)
        yield {'case_id': packet.case_id, 'packet_version': packet.version,
               'document_id': document['document_id'], 'fact_id': item.fact_id,
               'encounter_id': document.get('encounter_id'), 'source_sha256': packet.source.sha256,
               'category': claim.get('category', fact.category),
               'concept': claim.get('concept', fact.concept),
               'experiencer': claim.get('experiencer', fact.experiencer),
               'polarity': claim.get('polarity', fact.polarity),
               'temporality': claim.get('temporality', fact.temporality),
               'assertion_basis': claim.get('reporting_basis', fact.assertion_basis),
               'clinical_status': fact.clinical_status,
               'status_qualifier': fact.clinical_status,
               'event_time': claim.get('event_time'), 'event_date': day.isoformat() if day else None,
               'original_event_time': claim.get('event_time'),
               'record_time': document.get('encounter_time'), 'record_date': str(record_day) if record_day else None,
               'time_basis': time_basis,
               'normalization_basis': time_basis,
               'action_type': claim.get('action_type'),
               'action_state': claim.get('action_state', item.action_status),
               'completion_scope': claim.get('completion_scope'),
               'attributes': attributes or {}, 'review_status': item.review_status,
               'verification_status': record.get('result', {}).get('status', 'UNVERIFIED'),
               'contradicted_dimensions': [c['dimension'] for c in checks if c['status'] == 'CONTRADICTED'],
               'source_refs': _source_refs(packet, item, document)}


def _filter(row, filters):
    return ((filters.concept is None or _same(row['concept'], filters.concept))
            and (filters.experiencer is None or row['experiencer'] == filters.experiencer)
            and (filters.service_type is None or any(_same(value, filters.service_type)
                 for value in (row.get('service_type'), row.get('action_type'), row.get('concept')))))


_DURATION_UNITS = {'min': Decimal(1), 'mins': Decimal(1),
                   'minute': Decimal(1), 'minutes': Decimal(1), 'h': Decimal(60),
                   'hr': Decimal(60), 'hrs': Decimal(60), 'hour': Decimal(60), 'hours': Decimal(60)}


def _minutes(value):
    # Course days/weeks/months/years are not contact minutes. Ranges and
    # approximate wording cannot become exact contact minutes either.
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([a-z]+)\s*', value.casefold())
    if not match or match[2] not in _DURATION_UNITS:
        return None
    return Decimal(match[1]) * _DURATION_UNITS[match[2]]


def _reason(row, reason):
    return {'case_id': row.get('case_id'), 'document_id': row.get('document_id'),
            'fact_id': row.get('fact_id'), 'encounter_id': row.get('encounter_id'),
            'reason': reason, 'source_refs': row.get('source_refs', [])}


def _event_identity(row):
    """Use explicit event precision; a later review encounter is not the event."""
    timestamp = None
    timestamp_timezone = None
    window_end = None
    raw = row['event_time']
    window = _event_window(raw)
    if window is not None:
        timestamp = window[1].isoformat()
        window_end = window[2].isoformat()
        timestamp_timezone = 'unspecified'
    elif isinstance(raw, str) and re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}', raw):
        try:
            instant = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            timestamp_timezone = 'explicit_offset' if instant.tzinfo is not None else 'unspecified'
            if instant.tzinfo is not None:
                instant = instant.astimezone(timezone.utc)
            timestamp = instant.isoformat()
        except ValueError:
            pass
    encounter = (row['encounter_id'] if row['temporality'] == 'current'
                 and row['completion_scope'] == 'single_event'
                 and row['event_date'] is not None
                 and row['event_date'] == row['record_date'] else None)
    return {'event_date': row['event_date'], 'event_timestamp': timestamp,
            'event_window_end': window_end,
            'timestamp_timezone': timestamp_timezone,
            'timestamp_context': (['encounter', row['encounter_id'], row['record_date']]
                                  if row['encounter_id'] and row['record_date'] else
                                  ['source', row['source_sha256']]),
            'encounter_id': encounter,
            'basis': ('explicit_event_time_window' if window_end else
                      'explicit_event_timestamp' if timestamp else
                      'current_event_on_bound_encounter_day' if encounter else
                      'normalized_event_day_only')}


def _distinct_events(left, right):
    if (left['encounter_id'] is not None and right['encounter_id'] is not None
            and left['encounter_id'] != right['encounter_id']):
        return True
    # Offset-aware instants are comparable after UTC normalization, including
    # retellings whose original local calendar dates straddle midnight.
    if left['timestamp_timezone'] == right['timestamp_timezone'] == 'explicit_offset':
        return left['event_timestamp'] != right['event_timestamp']
    days = []
    for identity in (left, right):
        candidates = {identity['event_date']}
        if identity['timestamp_timezone'] == 'explicit_offset':
            candidates.add(identity['event_timestamp'][:10])
        days.append(candidates)
    if days[0].isdisjoint(days[1]):
        return True
    if (left['event_window_end'] and right['event_window_end']
            and left['timestamp_context'] == right['timestamp_context']):
        return (left['event_window_end'] <= right['event_timestamp']
                or right['event_window_end'] <= left['event_timestamp'])
    # Missing offset is not UTC. Different naive times only distinguish events
    # in an explicitly shared record context, never merely different sources.
    return (not left['event_window_end'] and not right['event_window_end']
            and left['timestamp_timezone'] == right['timestamp_timezone'] == 'unspecified'
            and left['timestamp_context'] == right['timestamp_context']
            and left['event_timestamp'] != right['event_timestamp'])


def _event_key(row):
    # A saved extraction identity explicitly forbids inferred deduplication. Only
    # equal source spans are identical assertions; broader event collisions are
    # surfaced separately rather than silently calling two events duplicates.
    identity = _event_identity(row)
    event_time = ((identity['event_date'], identity['event_timestamp'], identity['event_window_end'])
                  if identity['event_date'] else row['event_time'])
    return (row['source_sha256'], row['category'], row['concept'], row['experiencer'], event_time,
            row['action_type'], row['completion_scope'], row['polarity'], row['temporality'],
            row['action_state'], row['assertion_basis'],
            json.dumps(row['attributes'], sort_keys=True),
            tuple((r['start'], r['end']) for r in row['source_refs']))


def _deduplicate(rows, excluded):
    groups = {}
    for row in rows:
        key = _event_key(row)
        if key in groups:
            retained = groups[key]
            retained['source_refs'] = _unique(retained['source_refs'] + row['source_refs'])
            retained['event_time_variants'] = _unique(retained['event_time_variants'] + [row['event_time']])
            excluded.append({**_reason(row, 'duplicate_same_source_assertion'),
                             'retained_fact_id': retained['fact_id']})
        else:
            groups[key] = {**row, 'event_time_variants': [row['event_time']]}
    return list(groups.values())


def _encounters(workspace, documents, rows, filters, excluded, missing):
    result = []
    groups = defaultdict(list)
    for encounter in workspace.get('encounters', []):
        groups[encounter['encounter_id']].append(encounter)
    # The explicit ID binding on documents is usable even without a separate row.
    for document in documents:
        identity = document.get('encounter_id')
        if not identity:
            missing.append(_reason(document, 'document_has_no_explicit_encounter_id'))
        elif identity not in groups:
            groups[identity].append({'encounter_id': identity,
                                     'encounter_time': document.get('encounter_time')})
    for identity, records in sorted(groups.items()):
        members = [d for d in documents if d.get('encounter_id') == identity]
        dates = {_day(e.get('encounter_time') or e.get('date')) for e in records}
        dates |= {_day(d.get('encounter_time')) for d in members if d.get('encounter_time')}
        dates.discard(None)
        refs = [_metadata_ref(d, records[0]) for d in members]
        if not refs:
            refs = [_metadata_ref({}, records[0])]
        entry = {'encounter_id': identity, 'source_refs': refs}
        if len(dates) != 1:
            missing.append({**entry, 'reason': 'missing_or_conflicting_encounter_date',
                            'date_options': sorted(str(d) for d in dates)})
            continue
        day = next(iter(dates))
        if not _in_period(day, filters):
            excluded.append({**entry, 'reason': 'outside_requested_period'})
            continue
        states = {str(e.get('status', '')).casefold() for e in records}
        if states & {'planned', 'scheduled', 'cancelled', 'canceled', 'no_show', 'not_completed'}:
            excluded.append({**entry, 'reason': 'encounter_not_established_as_actual'})
            continue
        clinical = [r for r in rows if r['encounter_id'] == identity and _filter(r, filters)]
        metadata_type = any(_same(e.get('service_type'), filters.service_type) for e in records)
        needs_clinical = filters.concept is not None or filters.experiencer is not None
        if ((needs_clinical and not clinical) or
                (filters.service_type is not None and not clinical and not metadata_type)):
            missing.append({**entry, 'reason': 'encounter_filter_not_established'})
            continue
        if clinical and (needs_clinical or filters.service_type is not None):
            refs = _unique(refs + [ref for row in clinical for ref in row['source_refs']])
        result.append({**entry, 'encounter_date': str(day), 'source_refs': refs,
                       'basis': 'explicit_encounter_metadata'})
    return result


def _duration(rows, filters, excluded, missing):
    eligible = []
    unaggregated = []
    for row in rows:
        if row['category'] not in {'treatment', 'procedure', 'medication'}:
            excluded.append(_reason(row, 'not_a_treatment_duration'))
        elif row['experiencer'] != 'patient' or row['polarity'] != 'present':
            excluded.append(_reason(row, 'not_positive_patient_treatment'))
        elif row['action_state'] != 'completed' or row['temporality'] == 'planned':
            excluded.append({**_reason(row, 'no_completed_treatment_assertion'),
                             'documented_duration': row['attributes'].get('duration'),
                             'action_state': row['action_state']})
            unaggregated.append({**row, 'aggregation_status': 'not_established_as_completed'})
        elif row['contradicted_dimensions']:
            missing.append(_reason(row, 'contradicted_treatment_dimension'))
        elif (value := _minutes(row['attributes'].get('duration'))) is None:
            missing.append(_reason(row, 'missing_or_nonexact_documented_duration'))
            unaggregated.append({**row, 'aggregation_status': 'not_exact_contact_minutes_or_hours'})
        elif row['completion_scope'] != 'single_event':
            missing.append(_reason(row, 'duration_scope_not_established_as_single_event'))
            unaggregated.append({**row, 'aggregation_status': 'single_event_scope_unknown_or_course'})
        else:
            eligible.append({**row, 'minutes': float(value), 'event_identity': _event_identity(row)})
    # Equal dates/concepts across different original sources do not establish
    # event identity. A copied history and two same-day sessions are ambiguous.
    collisions = defaultdict(list)
    for row in eligible:
        selected_action = filters.service_type is not None and _same(
            row['action_type'], filters.service_type)
        collisions[(row['experiencer'], None if selected_action else row['concept'],
                    row['action_type'], row['completion_scope'])].append(row)
    accepted = []
    for group in collisions.values():
        for index, row in enumerate(group):
            identity = row['event_identity']
            # A date-only mention can retell a precisely timed event. It must
            # collide unless both rows explicitly distinguish their events.
            if any(not _distinct_events(identity, other['event_identity'])
                   for n, other in enumerate(group) if n != index):
                missing.append({**_reason(row, 'ambiguous_repeated_event_identity_or_conflicting_duration'),
                                'event_time': row['event_time'], 'event_date': row['event_date'],
                                'event_identity': identity})
                unaggregated.append({**row, 'aggregation_status': 'ambiguous_event_identity'})
            else:
                accepted.append(row)
    totals = defaultdict(Decimal)
    for row in accepted:
        # Different treatments/course scopes remain separate to avoid an
        # uninterpretable combined exposure total.
        key = (row['concept'], row['action_type'], row['completion_scope'])
        totals[key] += Decimal(str(row['minutes']))
    groups = [{'concept': key[0], 'action_type': key[1], 'completion_scope': key[2],
               'documented_minutes': float(value), 'documented_hours': float(value / 60)}
              for key, value in totals.items()]
    selected_action_total = (filters.service_type is not None and bool(accepted)
                             and all(_same(row['action_type'], filters.service_type)
                                     and row['completion_scope'] == 'single_event'
                                     for row in accepted))
    comparable = len(groups) <= 1 or selected_action_total
    if not comparable:
        missing.append({'reason': 'noncomparable_duration_groups',
                        'source_refs': _unique([r for row in accepted for r in row['source_refs']]),
                        'explanation': 'Different concepts, action types or completion scopes retain separate totals unless an explicit service type selects one saved action type.'})
    subtotal = sum((Decimal(str(row['minutes'])) for row in accepted), Decimal(0))
    unknown = bool(missing)
    value = float(subtotal) if comparable else None
    return {'documented_minutes': value, 'documented_hours': float(subtotal / 60) if comparable else None,
            'minutes': bounded(value, None if unknown else value),
            'complete': not unknown, 'comparable_total': comparable, 'groups': groups, 'events': accepted,
            'unaggregated_durations': unaggregated,
            'interpretation': 'Sum of documented completed single-event contact minutes/hours; course duration remains separately quoted in its original units and scope.'}, accepted


def _history(rows, family):
    rows = sorted(rows, key=lambda r: (r.get('display_date') or r['event_date'] or '',
                                     r['event_time'] or '', r['case_id'], r['fact_id']))
    groups = defaultdict(list)
    for row in rows:
        attributes = row['attributes']
        # Value units and stated scale/severity remain separate. A clinical
        # diagnosis, symptom, and result with the same label are not comparable.
        key = (row['experiencer'], row['category'], row['concept'], attributes.get('unit'),
               row['action_type'], row['completion_scope'], row['assertion_basis'])
        groups[key].append(row)
    histories = []
    for key, events in groups.items():
        histories.append({'comparison_key': {'experiencer': key[0], 'category': key[1],
                          'concept': key[2], 'unit_or_scale': key[3], 'action_type': key[4],
                          'completion_scope': key[5], 'assertion_basis': key[6]},
                          'events': events, 'clinical_trend': 'NOT_INFERRED',
                          'comparability_status': 'UNVERIFIED_INSTRUMENT_OR_EVENT_IDENTITY'})
    return {'events': rows, 'histories': histories,
            'comparability': 'Separate subject, exact concept, category, unit/scale, event type/scope and reporting basis; distinct assertions retain their own identity.',
            'interpretation_limits': ['An absent assertion is explicit source content; a missing later mention is unknown.',
                                     'Equal values/labels do not establish the same instrument or event.',
                                     'No causal effect, remission or clinical trend is inferred.']}


def query_patient_packets(workspace, packets, query):
    """Execute only finite validated parameters; no extraction/provider dependency."""
    spec = PatientQuerySpec.model_validate(query)
    supplied = list(packets.values()) if isinstance(packets, Mapping) else list(packets)
    verified = []
    for packet in supplied:
        if not isinstance(packet, Packet):
            packet = Packet.model_validate(packet)
        verified.append(packet.verify())
    return _query_verified_patient_packets(workspace, verified, spec)


def _query_verified_patient_packets(workspace, packets, query):
    """Calculate from CaseStore-verified packets without repeating their source checks."""
    spec = PatientQuerySpec.model_validate(query)
    filters = spec.filters
    patient_id = workspace.get('patient', {}).get('patient_id', workspace.get('patient_id'))
    if not patient_id:
        raise ValueError('Workspace requires explicit patient identity')
    documents = list(workspace.get('documents', []))
    by_case = {}
    for document in documents:
        case_id = document.get('case_id')
        if not document.get('document_id'):
            raise ValueError('Workspace documents require document_id')
        if case_id:
            if case_id in by_case and by_case[case_id] != document:
                raise ValueError('Conflicting document metadata for one saved case')
            by_case[case_id] = document
    supplied = list(packets.values()) if isinstance(packets, Mapping) else list(packets)
    selected = {}
    excluded, missing = [], []
    for packet in supplied:
        if not isinstance(packet, Packet):
            raise TypeError('Internal patient query requires verified Packet objects')
        if packet.patient_id != patient_id or packet.case_id not in by_case:
            raise ValueError('Packet does not belong to this patient workspace')
        previous = selected.get(packet.case_id)
        if previous and previous.version == packet.version and previous.content_hash != packet.content_hash:
            raise ValueError('Conflicting packets have the same case/version')
        if previous is None or packet.version > previous.version:
            if previous:
                excluded.append({'case_id': previous.case_id, 'packet_version': previous.version,
                                 'reason': 'superseded_packet_revision', 'source_refs': []})
            selected[packet.case_id] = packet
        else:
            excluded.append({'case_id': packet.case_id, 'packet_version': packet.version,
                             'reason': 'duplicate_or_superseded_packet_revision', 'source_refs': []})
    rows = []
    for case_id, document in by_case.items():
        packet = selected.get(case_id)
        if packet is not None:
            bindings = {'packet_version': packet.version, 'content_hash': packet.content_hash,
                        'source_hash': packet.source.sha256}
            if any(document.get(key) is not None and document[key] != value
                   for key, value in bindings.items()):
                raise ValueError('Evidence changed or metadata binding differs; reload the patient workspace')
        if packet is None:
            missing.append(_reason(document, 'saved_packet_unavailable'))
        elif packet.extraction_status in {'failed', 'invalid'}:
            missing.append(_reason(document, 'extraction_not_usable'))
        else:
            if packet.extraction_status == 'partial':
                missing.append(_reason(document, 'partial_extraction_source_coverage_unknown'))
            rows.extend(_rows(packet, document))
    for document in documents:
        if not document.get('case_id'):
            missing.append(_reason(document, 'document_extraction_not_available'))
    rows = _deduplicate([r for r in rows if _filter(r, filters)], excluded)
    if spec.family in {'visit_count', 'visit_frequency'}:
        encounters = _encounters(workspace, documents, rows, filters, excluded, missing)
        used = encounters
        answer = {'visit_count': len(encounters), 'encounters': encounters,
                  'counting_basis': 'unique explicit dated registered encounter IDs; registration does not verify clinical attendance',
                  'attendance_confirmation': 'NOT_ESTABLISHED_BY_REGISTRATION',
                  'complete': not missing}
        if spec.family == 'visit_frequency':
            dates = [date.fromisoformat(e['encounter_date']) for e in encounters]
            start = date.fromisoformat(filters.start) if filters.start else min(dates, default=None)
            end = date.fromisoformat(filters.end) if filters.end else max(dates, default=None)
            weeks = []
            if start and end:
                if (end - start).days > 36600:
                    raise ValueError('Frequency period exceeds 100 years')
                week = monday(start)
                while week <= end:
                    stop = week + timedelta(days=6)
                    members = [e for e in encounters if max(start, week).isoformat() <= e['encounter_date'] <= min(end, stop).isoformat()]
                    weeks.append({'week_start': str(week), 'week_end': str(stop),
                                  'observed_start': str(max(start, week)), 'observed_end': str(min(end, stop)),
                                  'visit_count': len(members), 'source_refs': _unique([r for e in members for r in e['source_refs']])})
                    week += timedelta(days=7)
            answer.update(weeks=weeks, start=str(start) if start else None,
                          end=str(end) if end else None, prescribed_frequency_used=False,
                          interpretation='Registered explicit encounters per Monday-Sunday week; partial weeks labelled; clinical attendance and undocumented visits remain unknown.')
    else:
        dated = []
        recorded_mentions = []
        allowed = {'symptom'} if spec.family == 'symptom_timeline' else (
            {'symptom', 'observation', 'laboratory_result', 'condition', 'diagnosis', 'other'}
            if spec.family == 'observation_history' else {'medication', 'procedure', 'treatment'})
        for row in rows:
            if row['category'] not in allowed:
                excluded.append(_reason(row, 'outside_query_category'))
            elif row['event_date'] is None:
                missing.append({**_reason(row, 'event_date_unknown_or_not_exact'), 'record': row})
                if spec.family != 'documented_duration_sum' and row['record_date']:
                    record_day = date.fromisoformat(row['record_date'])
                    if _in_period(record_day, filters):
                        recorded = {**row, 'display_date': row['record_date'],
                                    'time_basis': 'encounter_record',
                                    'temporal_limit': 'Date of this record only; event occurrence time is unknown.'}
                        if row['temporality'] == 'current':
                            dated.append(recorded)
                        else:
                            recorded_mentions.append(recorded)
            elif not _in_period(date.fromisoformat(row['event_date']), filters):
                excluded.append(_reason(row, 'outside_requested_period'))
            else:
                dated.append(row)
        if spec.family == 'documented_duration_sum':
            answer, used = _duration(dated, filters, excluded, missing)
        else:
            answer, used = _history(dated, spec.family), dated
            answer['undated_records'] = [m['record'] for m in missing if 'record' in m]
            answer['recorded_mentions'] = sorted(recorded_mentions, key=lambda r: (r['display_date'], r['fact_id']))
            used = used + recorded_mentions
    refs = _unique([ref for row in used for ref in row['source_refs']])
    trace = CalculationTrace(operation=spec.family,
        inputs={'query': spec.model_dump(mode='json'), 'record_count': len(used),
                'contributions': [{key: row[key] for key in ('case_id', 'fact_id', 'encounter_id',
                    'event_date', 'event_time', 'event_time_variants', 'time_basis', 'event_identity',
                    'minutes', 'encounter_date') if key in row}
                    for row in used],
                **({'duration_identity_assessment': [
                    {key: row[key] for key in ('case_id', 'fact_id', 'event_date', 'event_time',
                        'event_time_variants', 'event_identity', 'aggregation_status') if key in row}
                    for row in answer['events'] + answer['unaggregated_durations']]}
                   if spec.family == 'documented_duration_sum' else {})},
        output={key: value for key, value in answer.items() if key in {'visit_count', 'documented_minutes', 'documented_hours', 'complete'}},
        claim_ids=sorted({r['fact_id'] for r in used if r.get('fact_id')}),
        event_ids=sorted({r['encounter_id'] for r in used if r.get('encounter_id')}),
        assumptions=['Current saved packets only; sources are not re-extracted.',
                     'Missing/ambiguous events are retained separately; no undocumented negative is imputed.',
                     'Source citations establish location, not clinical correctness.']).model_dump(mode='json')
    return {'answer': answer, 'query_spec': spec.model_dump(mode='json'),
            'evidence_version': workspace.get('evidence_version') or digest([
                [p.case_id, p.version, p.content_hash] for p in sorted(selected.values(), key=lambda p: p.case_id)]),
            'computed_from': [{'case_id': p.case_id, 'packet_version': p.version,
                               'document_id': by_case[p.case_id]['document_id'],
                               'content_hash': p.content_hash, 'source_sha256': p.source.sha256}
                              for p in sorted(selected.values(), key=lambda p: p.case_id)],
            'calculation_steps': [trace], 'excluded_records': excluded, 'missing_data': missing,
            'source_refs': refs, 'model_used_for_interpretation': False, 'model_calls': 0}
