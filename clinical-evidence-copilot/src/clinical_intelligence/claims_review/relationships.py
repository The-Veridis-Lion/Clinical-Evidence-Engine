"""Immutable record relationships and a field-scoped derived view.

Only explicit structured declarations route here; free text is never classified
as an amendment using a word match. Authority is a source assertion, not verified
signature authenticity. There is no latest-timestamp winner.
"""
from typing import Any, Literal
from pydantic import Field
from .contracts import Contract, Citation
from .facts import pointer
from .prepare import digest

VERSION = 'claims-review-relationships/1'
FIELD_PATHS = {'event_date': 'event_date', 'specimen_date': 'event_date',
               'value': 'content/value', 'result': 'content/value'}


class SourceRelationship(Contract):
    relationship_id: str
    patient_id: str
    source_id: str
    target_source_id: str | None
    event_link_id: str | None
    relation: Literal['amends', 'retransmits', 'supersedes']
    field: str | None
    replacement: Any
    authenticated: bool | None
    authority_scope: str | None
    citations: list[Citation] = Field(min_length=1)


def declarations(sources):
    """Declared synthetic/export metadata, preserving original pointers."""
    output = []
    for s in sources:
        c = s['content']
        if not isinstance(c, dict):
            continue
        explicit = c.get('source_relationship')
        if explicit is not None:
            if not isinstance(explicit, dict):
                raise ValueError('source_relationship must be an explicit object')
            relation = explicit.get('relation')
            target = explicit.get('target_source_id')
            field = explicit.get('field')
            replacement = explicit.get('replacement')
            authenticated = explicit.get('authenticated')
            scope = explicit.get('authority_scope')
        elif c.get('correction_target_source_id') is not None:
            relation, target = 'amends', c['correction_target_source_id']
            field = FIELD_PATHS.get(c.get('correction_scope'), c.get('correction_scope'))
            replacement = s['event_date'] if field == 'event_date' else c.get('value') if field == 'content/value' else None
            authenticated = {'electronically_signed': True, 'signed': True, 'unsigned': False}.get(c.get('authentication_status'))
            scope = field if c.get('document_status') == 'amended' else None
        elif c.get('retransmission_of_source_id') is not None:
            relation, target, field, replacement = 'retransmits', c['retransmission_of_source_id'], None, None
            authenticated, scope = None, None
        else:
            continue
        body = dict(patient_id=s['patient_id'], source_id=s['source_id'], target_source_id=target,
                    event_link_id=s['event_link_id'], relation=relation, field=field, replacement=replacement,
                    authenticated=authenticated, authority_scope=scope,
                    citations=[pointer(s, 'content'), pointer(s, 'event_link_id')])
        r = SourceRelationship(relationship_id='pending', **body)
        output.append(r.model_copy(update={'relationship_id': digest(r.model_dump(mode='json'))[:24]}))
    return output


def get_value(source, field):
    if field == 'event_date':
        return source['event_date']
    key=field.split('/', 1)[1]
    return source['content'].get(key,source['content'].get('VALUE') if key=='value' else None)


def reconcile(sources):
    """Return values keyed by (source, field), without editing any source/fact."""
    by_id = {s['source_id']: s for s in sources}
    relations = declarations(sources)
    trace, valid, unresolved, copy_targets = [], [], set(), {}
    fields = {'event_date', 'content/value'}
    for r in relations:
        reasons = []
        target = by_id.get(r.target_source_id)
        source = by_id[r.source_id]
        if target is None:
            reasons.append('target unavailable or not identified')
        elif target['patient_id'] != r.patient_id:
            reasons.append('patient mismatch')
        elif not r.event_link_id or r.event_link_id != target['event_link_id']:
            reasons.append('event identity not explicitly shared')
        elif source['encounter_id'] and target['encounter_id'] and source['encounter_id'] != target['encounter_id']:
            reasons.append('encounter mismatch')
        if r.relation != 'retransmits':
            if r.field not in fields:
                reasons.append('unsupported or unknown target field')
            if r.authenticated is not True or r.authority_scope != r.field:
                reasons.append('applicable field authority/authentication unresolved')
            if r.replacement is None:
                reasons.append('replacement unknown; not a supported deletion')
            if r.field in fields and r.replacement != get_value(source, r.field):
                reasons.append('replacement not supported by declaring record field')
            if r.field == 'event_date' and r.replacement is not None:
                from .facts import parsed_date
                if parsed_date(r.replacement) is None:
                    reasons.append('invalid replacement date')
        else:
            if target and any(get_value(source, f) != get_value(target, f) for f in fields):
                reasons.append('copy differs from original tracked fields')
        row = {'relationship': r.model_dump(mode='json'), 'status': 'UNRESOLVED' if reasons else 'VALID', 'reasons': reasons}
        trace.append(row)
        if reasons:
            affected = fields if r.field is None else {r.field} & fields
            unresolved.update((r.source_id, f) for f in affected)
            if target and target['patient_id'] == r.patient_id:
                unresolved.update((target['source_id'], f) for f in affected)
        elif r.relation == 'retransmits':
            copy_targets[r.source_id] = r.target_source_id
        else:
            valid.append(r)

    def resolve(identifier, field, seen=()):
        if identifier in seen:
            return {'values': [], 'status': 'UNRESOLVED', 'source_ids': list(seen), 'reason': 'relationship cycle'}
        replacements = [r for r in valid if r.target_source_id == identifier and r.field == field]
        if replacements:
            branches = [resolve(r.source_id, field, seen + (identifier,)) for r in replacements]
            values = []
            for branch in branches:
                for value in branch['values']:
                    if value not in values:
                        values.append(value)
            uncertain = (identifier,field) in unresolved or any(b['status'] == 'UNRESOLVED' for b in branches)
            return {'values': values, 'status': 'UNRESOLVED' if uncertain else 'CONFLICTED' if len(values)>1 else 'AMENDED',
                    'source_ids': sorted({identifier, *[x for b in branches for x in b['source_ids']]})}
        if identifier in copy_targets:
            out = resolve(copy_targets[identifier], field, seen + (identifier,))
            return {**out, 'source_ids': sorted(set(out['source_ids'] + [identifier]))}
        return {'values': [get_value(by_id[identifier], field)], 'status': 'UNRESOLVED' if (identifier,field) in unresolved else 'ORIGINAL', 'source_ids': [identifier]}

    view = {identifier: {f: resolve(identifier, f) for f in fields} for identifier in by_id}
    return {'version': VERSION, 'relationships': trace, 'derived': view,
            'authority_limit': 'Explicit source declarations only; signature authenticity/provider credentials not independently verified.'}
