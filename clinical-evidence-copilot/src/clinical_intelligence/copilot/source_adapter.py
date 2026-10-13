"""Original-text speaker format adapter; no changes to Engine indexing behavior."""
import json
import re

from ..clinical_notes.schema import Evidence, validate_extraction
from ..dialogue_first import contract as engine
from ..dialogue_first.dataset import source_index as engine_index
from ..dialogue_first.prompt import DIALOGUE_INSTRUCTION, NOTE_INSTRUCTION

VERSION = 'copilot-source-index/v1'
NATIVE_LABELS = re.compile(r'(?<!\w)(Doctor|Patient|Nurse|Clinician|Physician|Provider):', re.I)


def speaker_annotations(doc):
    """Preserve all observed line labels separately from legacy turn indexing.

    Existing source IDs/provenance remain immutable. Labels that the old index
    missed, such as a family member, are explicit boundary discrepancies; neither
    a supplied label nor the inferred role is clinical attribution proof.
    """
    if doc.input_kind != 'dialogue':
        return []
    labels = list(re.finditer(r"(?m)^\s*(\[[^\]\r\n]{1,40}\]|[A-Za-z][A-Za-z '\u2019-]{0,39}:)", doc.text))
    indexed = source_index(doc)['turns']
    result = []
    for index, match in enumerate(labels):
        start, end = match.start(1), labels[index+1].start(1) if index+1 < len(labels) else len(doc.text)
        label = match.group(1)
        normalized = label.strip('[]:').casefold()
        declared = 'clinician' if normalized in {'doctor','clinician','physician','provider','nurse'} else 'patient' if normalized == 'patient' else 'family' if 'family' in normalized else 'unknown'
        old = next((t for t in indexed if t['start'] <= start < t['end']), None)
        result.append({'raw_label': label, 'label_start': start, 'label_end': match.end(1),
            'start': start, 'end': end, 'declared_role': declared,
            'inferred_role': 'unknown', 'role_status': 'UNVERIFIED',
            'legacy_turn_id': old['turn_id'] if old else None,
            'legacy_speaker_label': old['speaker_label'] if old else None,
            'boundary_discrepancy': old is None or old['start'] != start or old['speaker_label'] != label})
    return result


def source_index(doc):
    if doc.input_kind != 'dialogue' or re.search(r'\[(doctor|patient|nurse|clinician|physician|provider)\]', doc.text, re.I):
        return engine_index(doc)
    labels = list(NATIVE_LABELS.finditer(doc.text))
    if not labels:
        return engine_index(doc)
    doc.verify()
    boundaries = [m.start() for m in labels]
    if boundaries[0] != 0:
        boundaries.insert(0, 0)
    boundaries.append(len(doc.text))
    turns, catalogue = [], []
    for number, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        label = next((m.group(0) for m in labels if m.start() == start), None)
        turn_id = f't{number:04d}'
        turns.append(dict(turn_id=turn_id, speaker_label=label, start=start, end=end, quote=doc.text[start:end]))
        body = start+len(label or '')
        stops = [body]+[body+m.end() for m in re.finditer(r'\n|(?<=[.!?])\s+(?=[A-Za-z])', doc.text[body:end])]+[end]
        for a, b in zip(stops, stops[1:]):
            while a < b and doc.text[a].isspace(): a += 1
            while b > a and doc.text[b-1].isspace(): b -= 1
            if a < b:
                catalogue.append(dict(source_id=f'{turn_id}:{a}:{b}', turn_id=turn_id,
                    speaker_label=label, start=a, end=b, quote=doc.text[a:b]))
    return {'turns': turns, 'source_catalogue': catalogue}


def prompt(doc):
    return (DIALOGUE_INSTRUCTION if doc.input_kind == 'dialogue' else NOTE_INSTRUCTION)+'\n'+json.dumps({
        'document_id': doc.document_id, 'encounter_id': doc.encounter_id, 'input_kind': doc.input_kind,
        'transcript' if doc.input_kind == 'dialogue' else 'note': doc.text,
        **source_index(doc)}, ensure_ascii=False)


def schema(doc):
    shape = engine.Proposal.model_json_schema()
    shape['$defs']['References']['properties']['source_ids']['items']['enum'] = [s['source_id'] for s in source_index(doc)['source_catalogue']]
    shape['properties']['document_id']['enum'] = [doc.document_id]
    return shape


def inspect(raw, doc):
    """Resolve using Engine types/resolvers with the application catalogue."""
    if source_index(doc) == engine_index(doc):
        return engine.inspect(raw, doc)
    doc.verify()
    catalogue = {s['source_id']: s for s in source_index(doc)['source_catalogue']}
    facts, accepted, relationships, errors = [], [], [], []
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {'document_id','facts','relationships'} or value['document_id'] != doc.document_id:
            raise ValueError('Malformed extraction envelope/document identity')
        if not isinstance(value['facts'], list) or not isinstance(value['relationships'], list):
            raise ValueError('Expected fact and relationship lists')
    except (ValueError, TypeError) as exc:
        return dict(status='INVALID',result=None,accepted_indices=[],errors=[str(exc)])
    for i, item in enumerate(value['facts']):
        try:
            f = engine.ProposedFact.model_validate(item)
            spans = engine.resolve_references(f.evidence, doc, catalogue)
            resolved = {**f.model_dump(exclude={'evidence'}), 'original_term': spans[0]['quote'],
                'evidence': {k:spans[0][k] for k in Evidence.model_fields},
                'supporting_evidence': [{k:s[k] for k in Evidence.model_fields} for s in spans[1:]], 'provenance': spans}
            facts.append(engine.DialogueFact.model_validate(resolved).model_dump())
            accepted.append(i)
        except ValueError as exc:
            errors.append(f'facts[{i}]: {exc}')
    mapping = {raw_index: i for i, raw_index in enumerate(accepted)}
    for i, relation in enumerate(value['relationships']):
        try:
            relationships.append(engine.resolve_relationship(relation, doc, catalogue, mapping))
        except ValueError as exc:
            errors.append(f'relationships[{i}]: {exc}')
    result = engine.Extraction(document_id=doc.document_id, facts=facts, relationships=relationships).model_dump()
    validate_extraction(json.dumps(engine.primary_projection(result)), doc)
    return dict(status='PARTIAL' if errors and facts else 'INVALID' if errors else 'VALID',
                result=result,accepted_indices=accepted,errors=errors)
