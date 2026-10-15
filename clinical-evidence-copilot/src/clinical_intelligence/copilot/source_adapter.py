"""Original-text speaker format adapter; no changes to Engine indexing behavior."""
import json
import re

from ..clinical_notes.schema import Evidence, validate_extraction
from ..dialogue_first import contract as engine
from ..dialogue_first.dataset import source_index as engine_index
from ..dialogue_first.prompt import DIALOGUE_INSTRUCTION, NOTE_INSTRUCTION

VERSION = 'copilot-source-index/v1'
TASK_VERSION = 'clinical-event-assertions/1'
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


def prompt(doc, *, semantics_version=None, task_version=None):
    instruction = DIALOGUE_INSTRUCTION if doc.input_kind == 'dialogue' else NOTE_INSTRUCTION
    if semantics_version == 'clinical-fact-semantics/2':
        instruction += ('\nVERSIONED REPRESENTATION CONTRACT: each fact has a semantics object. '
            'Frequency (e.g. daily) is separate from elapsed duration; event_time preserves explicit original time wording. '
            'Null means not asserted, unknown action_state means not established. '
            'An administered/taken dose is a single_event, never a completed course. '
            'Conditional consideration is discussed, not a committed plan or execution. '
            'Do not invent values; the source verifier checks each dimension separately.')
    elif semantics_version is not None:
        raise ValueError('Unsupported clinical semantics schema version')
    if task_version is not None:
        if task_version != TASK_VERSION or semantics_version != 'clinical-fact-semantics/2':
            raise ValueError('Event assertion task requires the existing clinical semantics/2 schema')
        instruction += ('\nCLINICAL EVENT ASSERTIONS CONTRACT/1: facts are independent propositions, not just unique concepts. '
            'Keep distinct subject, event time, action and completion scope. A future scheduled treatment and its currently not-started course are two propositions, even for the same treatment. '
            'A completed session is not a completed course. Do not combine incompatible present, historical or planned assertions into one clinical_status. '
            'Frequency, event_time, dose and duration are attributes of their corresponding assertion, not extra duplicate facts. '
            'Choose assertion_basis for the actual proposition: a clinician future order/assessment is not an observation of a performed action; preserve independently measured findings as observations. '
            'Keep explicit documentation statements as independent facts using category=other, concept="documentation of [the documented target]", clinical_status=not_documented when documentation is explicitly absent. '
            'The absence polarity then describes documentation only; it does not assert the clinical event or adverse effect was absent. Unstated documentation is not an explicit documentation-gap fact. '
            'For each fact primary_source_id selects a cited passage that directly supports that proposition, or null if no primary anchor can be established. '
            'Keep every original evidence.source_ids in source order, including question/answer context. A question alone is not proof; yes/no or elliptical answers need the governing question as well. '
            'Select primary support by meaning, never simply by patient/clinician speaker role. Do not discard other supporting or conflicting passages.')
    return instruction+'\n'+json.dumps({
        'document_id': doc.document_id, 'encounter_id': doc.encounter_id, 'input_kind': doc.input_kind,
        'transcript' if doc.input_kind == 'dialogue' else 'note': doc.text,
        **source_index(doc)}, ensure_ascii=False)


def schema(doc, *, semantics_version=None, task_version=None):
    if task_version is not None:
        if task_version != TASK_VERSION or semantics_version != 'clinical-fact-semantics/2':
            raise ValueError('Event assertion task requires the existing clinical semantics/2 schema')
        from .semantics import ClinicalSemanticsV2
        class EventFact(engine.ProposedFact):
            semantics: ClinicalSemanticsV2
            primary_source_id: str | None
        class EventProposal(engine.Proposal):
            facts: list[EventFact]
        shape = EventProposal.model_json_schema()
        shape['$defs']['EventFact']['properties']['primary_source_id']['anyOf'][0]['enum'] = [
            s['source_id'] for s in source_index(doc)['source_catalogue']]
        shape['$defs']['ClinicalSemanticsV2']['required'] = list(shape['$defs']['ClinicalSemanticsV2']['properties'])
        shape['$defs']['ClinicalSemanticsV2']['properties']['version'].pop('default',None)
    elif semantics_version == 'clinical-fact-semantics/2':
        from .semantics import ClinicalSemanticsV2
        class ProposedFactV2(engine.ProposedFact):
            semantics: ClinicalSemanticsV2
        class ProposalV2(engine.Proposal):
            facts: list[ProposedFactV2]
        shape = ProposalV2.model_json_schema()
        shape['$defs']['ClinicalSemanticsV2']['required'] = list(shape['$defs']['ClinicalSemanticsV2']['properties'])
        shape['$defs']['ClinicalSemanticsV2']['properties']['version'].pop('default',None)
    elif semantics_version is None:
        shape = engine.Proposal.model_json_schema()
    else:
        raise ValueError('Unsupported clinical semantics schema version')
    shape['$defs']['References']['properties']['source_ids']['items']['enum'] = [s['source_id'] for s in source_index(doc)['source_catalogue']]
    shape['properties']['document_id']['enum'] = [doc.document_id]
    return shape


def inspect(raw, doc, *, semantics_version=None, task_version=None):
    """Resolve using Engine types/resolvers with the application catalogue."""
    if task_version is not None:
        if task_version != TASK_VERSION or semantics_version != 'clinical-fact-semantics/2':
            raise ValueError('Event assertion task requires the existing clinical semantics/2 schema')
        try:
            payload=json.loads(raw)
            if not isinstance(payload,dict) or not isinstance(payload.get('facts'),list):
                raise ValueError('Malformed event assertion envelope')
            stripped=[];anchors={};errors=[]
            for i,fact in enumerate(payload['facts']):
                if not isinstance(fact,dict):
                    stripped.append(fact);continue
                primary=fact.get('primary_source_id')
                if ('primary_source_id' not in fact or
                        (primary is not None and (not isinstance(primary,str) or
                         primary not in fact.get('evidence',{}).get('source_ids',[])))):
                    stripped.append({})
                    errors.append(f'facts[{i}].primary_source_id must be null or a selected evidence source ID')
                    continue
                stripped.append({k:v for k,v in fact.items() if k!='primary_source_id'})
                anchors[i]={'primary_source_id':primary,
                    'selected_source_ids':list(fact.get('evidence',{}).get('source_ids',[]))}
            result=inspect(json.dumps({**payload,'facts':stripped},ensure_ascii=False),doc,
                semantics_version=semantics_version)
            result['errors'].extend(errors)
            if result['result'] is not None:
                result['result']['event_assertion_contract']={'version':TASK_VERSION,'source_sha256':doc.note_sha256,
                    'assertions':[{'fact_index':i,**anchors[raw_index]} for i,raw_index in enumerate(result['accepted_indices'])]}
                result['status']='PARTIAL' if result['errors'] and result['result']['facts'] else 'INVALID' if result['errors'] else 'VALID'
            return result
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            return dict(status='INVALID',result=None,accepted_indices=[],errors=[str(exc)])
    if semantics_version == 'clinical-fact-semantics/2':
        from .semantics import ClinicalSemanticsV2
        try:
            payload = json.loads(raw)
            legacy = {**payload,'facts':[{k:v for k,v in f.items() if k != 'semantics'} if isinstance(f,dict) else f for f in payload['facts']]}
            result = inspect(json.dumps(legacy,ensure_ascii=False),doc)
            if result['result'] is not None:
                selected=[];typed=[];indices=[];mapping={}
                for old_index,raw_index in enumerate(result['accepted_indices']):
                    try:
                        semantics = ClinicalSemanticsV2.model_validate(payload['facts'][raw_index]['semantics']).model_dump(mode='json')
                    except (KeyError,ValueError,TypeError) as exc:
                        result['errors'].append(f'facts[{raw_index}].semantics: {exc}')
                        continue
                    mapping[old_index]=len(selected)
                    selected.append(result['result']['facts'][old_index])
                    typed.append({'fact_index':len(selected)-1,'semantics':semantics})
                    indices.append(raw_index)
                relationships=[]
                for relation in result['result']['relationships']:
                    if relation['from_fact_index'] not in mapping or relation['to_fact_index'] not in mapping:
                        result['errors'].append('Relationship targets rejected typed clinical semantics')
                        continue
                    relationships.append({**relation,'from_fact_index':mapping[relation['from_fact_index']],
                        'to_fact_index':mapping[relation['to_fact_index']]})
                result['result'].update(facts=selected,relationships=relationships,clinical_semantics=typed)
                result['accepted_indices']=indices
                result['status']='PARTIAL' if result['errors'] and selected else 'INVALID' if result['errors'] else 'VALID'
            return result
        except (KeyError,ValueError,TypeError) as exc:
            return dict(status='INVALID',result=None,accepted_indices=[],errors=[str(exc)])
    if semantics_version is not None:
        raise ValueError('Unsupported clinical semantics schema version')
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
