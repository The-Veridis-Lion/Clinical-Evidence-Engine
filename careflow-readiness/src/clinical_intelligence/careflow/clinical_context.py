"""Source-validated reuse of universal ClinicalFact, never a PA/claim conversion."""
import json
from types import SimpleNamespace

from ..clinical_notes.dataset import sha
from ..clinical_notes.schema import validate_extraction
from ..dialogue_first.contract import primary_projection
from ..dialogue_first.dataset import Document, source_index
from ..claims_review.facts import source_key
from ..claims_review.prepare import digest
from .evidence import available


def checked_structured(context, source):
    if context.structured_extraction is None:
        return {}
    if context.structured_extraction.get('version') == 'careflow-shared-copilot-snapshot/1':
        from .shared_evidence import checked_snapshot
        return checked_snapshot(context, source)
    from .extraction import inspect_structured
    retained = context.structured_extraction
    if not isinstance(retained, dict) or retained.get('source_sha256') != sha(source.content):
        raise ValueError('Structured extraction source hash mismatch')
    raw = retained.get('raw_response')
    if not isinstance(raw, str) or retained.get('raw_response_sha256') != sha(raw):
        raise ValueError('Structured extraction original response hash mismatch')
    outcome = inspect_structured(raw, document(source, context.extraction))
    if (outcome['status'] != 'VALID' or outcome.get('structured_extraction') != retained
            or outcome['result'] != context.extraction.model_dump(mode='json')):
        raise ValueError('Structured extraction differs from reconstructed original response')
    semantics = {row['fact_index']: row for row in retained['semantic_proposals']}
    return {row['fact_index']:{'task_version':retained['version'],
        'raw_response_sha256':retained['raw_response_sha256'],
        'source_sha256':retained['source_sha256'], 'anchor':row,
        'semantics':semantics.get(row['fact_index'], {}).get('semantics', {}),
        'invalid_fields':semantics.get(row['fact_index'], {}).get('invalid_fields', [])}
        for row in retained['anchors']}


def checked_semantics(context, source):
    """Validate the existing typed/2 proposal wire, not its clinical correctness."""
    rows = context.clinical_semantics
    bound_hash = context.clinical_semantics_source_sha256
    if not rows:
        if bound_hash is not None:
            raise ValueError('Clinical semantics source hash requires explicit indexed proposals')
        return {}
    if bound_hash != sha(source.content):
        raise ValueError('Clinical semantics source hash mismatch')
    required = {'version', 'frequency', 'event_time', 'duration', 'action_state',
                'completion_scope', 'assertion_basis', 'action_type'}
    states = {'planned', 'completed', 'not_completed', 'ongoing', 'discussed', 'unknown'}
    bases = {'patient_report', 'patient_reported', 'clinician_assessment', 'clinician_observation',
             'documented_history', 'discussion', 'unknown'}
    result = {}
    for row in rows:
        if (set(row) != {'fact_index', 'semantics'} or type(row['fact_index']) is not int
                or not 0 <= row['fact_index'] < len(context.extraction.facts)
                or row['fact_index'] in result):
            raise ValueError('Clinical semantics needs unique existing original fact indices')
        value = row['semantics']
        if (not isinstance(value, dict) or set(value) != required
                or value['version'] != 'clinical-fact-semantics/2'
                or not isinstance(value['action_state'], str) or not isinstance(value['assertion_basis'], str)
                or value['completion_scope'] is not None and not isinstance(value['completion_scope'], str)
                or value['action_state'] not in states or value['assertion_basis'] not in bases
                or value['completion_scope'] not in {None, 'single_event', 'course', 'full_course', 'unknown'}
                or any(value[key] is not None and not isinstance(value[key], str)
                       for key in ('frequency', 'event_time', 'duration', 'action_type'))):
            raise ValueError('Clinical semantics differs from clinical-fact-semantics/2')
        result[row['fact_index']] = dict(value)
    return result


def document(source, extraction):
    locator = source.original_locator or {}
    if not isinstance(source.content, str):
        raise ValueError('Clinical extraction requires an original text source')
    expected_id = locator.get('document_id', source.source_id)
    if extraction.document_id != expected_id:
        raise ValueError('Clinical extraction document identity differs from its source binding')
    return Document(expected_id, source.encounter_id or expected_id, locator.get('dataset', 'supplied-source'),
                    source.content, sha(source.content), sha(source.content), 0,
                    input_kind=locator.get('input_kind', 'note'))


def context_source_index(context, doc):
    if context.source_index_version is None:
        return source_index(doc)
    if context.source_index_version != 'copilot-source-index/v1':
        raise ValueError('Unsupported source catalogue version')
    from ..evidence_bridge import verification_package
    verification_package()
    from evidence_verification.extensions.source_index import source_index as copilot_index
    return copilot_index(doc, legacy_index=source_index)


def validate_context_sources(case):
    sources = {s.source_id: s for s in case.sources}
    if len({c.source_id for c in case.clinical_context}) != len(case.clinical_context):
        raise ValueError('Multiple competing extraction snapshots for the same source need separate source identities')
    for context in case.clinical_context:
        if context.source_id not in sources:
            raise ValueError('Clinical context references an unknown source')
        doc = document(sources[context.source_id], context.extraction)
        checked_semantics(context, sources[context.source_id])
        checked_structured(context, sources[context.source_id])
        value = context.extraction.model_dump(mode='json')
        # Existing schema and exact quote validator, unchanged from the engine.
        validate_extraction(json.dumps(primary_projection(value)), doc)
        catalogue = {p['source_id']: p for p in context_source_index(context, doc)['source_catalogue']}
        for fact in context.extraction.facts:
            for span in fact.supporting_evidence:
                if not 0 <= span.start < span.end <= len(doc.text) or doc.text[span.start:span.end] != span.quote:
                    raise ValueError('Clinical supporting evidence is ungrounded')
            for ref in fact.provenance:
                original = catalogue.get(ref.source_id)
                if (ref.document_id != doc.document_id or original is None
                        or any(getattr(ref, field) != original[field] for field in ('start', 'end', 'quote', 'turn_id', 'speaker_label'))):
                    raise ValueError('Clinical provenance differs from the original source index')
        for relation in context.extraction.relationships:
            if not (0 <= relation.from_fact_index < len(context.extraction.facts)
                    and 0 <= relation.to_fact_index < len(context.extraction.facts)):
                raise ValueError('Clinical relationship references an absent fact')
            for ref in relation.provenance:
                original = catalogue.get(ref.source_id)
                if (ref.document_id != doc.document_id or original is None
                        or any(getattr(ref, field) != original[field] for field in ('start', 'end', 'quote', 'turn_id', 'speaker_label'))):
                    raise ValueError('Clinical relationship provenance is ungrounded')


def prepared_context(case):
    sources = {s.source_id: s for s in case.sources}
    result = []
    for context in case.clinical_context:
        source = sources[context.source_id]
        raw_source = source.model_dump(mode='json')
        issue = available(raw_source, case)
        semantics = checked_semantics(context, source)
        structured = checked_structured(context, source)
        facts = []
        for index, fact in enumerate(context.extraction.facts):
            raw = fact.model_dump(mode='json')
            if index in semantics:
                raw = {**raw, 'clinical_semantics_v2': semantics[index]}
            if index in structured:
                raw = {**raw, 'structured_clinical_proposal': structured[index]}
            facts.append({**raw, 'context_fact_id': 'clinical-' + digest([source_key(raw_source), index, raw])[:24],
                          'original_fact_index': index, 'source_id': source.source_id})
        result.append({'document_id': context.extraction.document_id, 'source_id': source.source_id,
                       'source_sha256': source_key(raw_source), 'patient_id': source.patient_id,
                       'request_id': case.request.request_id, 'context_only': True,
                       'scope_status': 'EXCLUDED' if issue else 'IN_SCOPE', 'exclusion_reason': issue,
                       'facts': facts, 'relationships': [r.model_dump(mode='json') for r in context.extraction.relationships],
                       'boundary': 'Supplied clinical interpretations retain their evidence; they do not establish referral intent, PA form, eligibility or rule satisfaction.'})
        if semantics:
            result[-1]['clinical_semantics'] = context.clinical_semantics
            result[-1]['clinical_semantics_source_sha256'] = context.clinical_semantics_source_sha256
        if context.source_index_version is not None:
            result[-1]['source_index_version'] = context.source_index_version
        if context.structured_extraction is not None:
            result[-1]['structured_extraction'] = context.structured_extraction
    return result


def verify_packet_context(packet):
    """Check persisted context bundles through the same original source validator."""
    from .contracts import Source, ClinicalContext
    sources = {s['source_id']: s for s in packet['sources']}
    checks = []
    for context in packet.get('clinical_context', []):
        try:
            raw_source = sources[context['source_id']]
            valid = (context['source_sha256'] == source_key(raw_source)
                     and context['patient_id'] == raw_source['patient_id'] and context['context_only'] is True)
            facts = []
            for index, item in enumerate(context['facts']):
                original = {k: v for k, v in item.items() if k not in {'context_fact_id', 'original_fact_index', 'source_id'}}
                valid = valid and (item['original_fact_index'] == index and item['source_id'] == context['source_id']
                                   and item['context_fact_id'] == 'clinical-' + digest([source_key(raw_source), index, original])[:24])
                fact = {k: v for k, v in original.items() if k not in {'clinical_semantics_v2', 'structured_clinical_proposal'}}
                facts.append(fact)
            supplied = ClinicalContext.model_validate({'source_id': context['source_id'], 'extraction': {
                'document_id': context['document_id'], 'facts': facts, 'relationships': context['relationships']},
                **({key: context[key] for key in ('clinical_semantics', 'clinical_semantics_source_sha256')}
                   if context.get('clinical_semantics') else {}),
                **({'source_index_version':context['source_index_version']} if context.get('source_index_version') else {})})
            if context.get('structured_extraction') is not None:
                supplied = supplied.model_copy(update={'structured_extraction':context['structured_extraction']})
            indexed = checked_semantics(supplied, Source.model_validate_json(json.dumps(raw_source)))
            valid = valid and all(item.get('clinical_semantics_v2') == indexed.get(index)
                                  for index, item in enumerate(context['facts']))
            structured = checked_structured(supplied, Source.model_validate_json(json.dumps(raw_source)))
            valid = valid and all(item.get('structured_clinical_proposal') == structured.get(index)
                                  for index, item in enumerate(context['facts']))
            validate_context_sources(SimpleNamespace(sources=[Source.model_validate_json(json.dumps(raw_source))], clinical_context=[supplied]))
            checks.append(bool(valid))
        except (KeyError, ValueError, TypeError, IndexError):
            checks.append(False)
    return checks
