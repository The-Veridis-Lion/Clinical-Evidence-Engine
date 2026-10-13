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


def validate_context_sources(case):
    sources = {s.source_id: s for s in case.sources}
    if len({c.source_id for c in case.clinical_context}) != len(case.clinical_context):
        raise ValueError('Multiple competing extraction snapshots for the same source need separate source identities')
    for context in case.clinical_context:
        if context.source_id not in sources:
            raise ValueError('Clinical context references an unknown source')
        doc = document(sources[context.source_id], context.extraction)
        value = context.extraction.model_dump(mode='json')
        # Existing schema and exact quote validator, unchanged from the engine.
        validate_extraction(json.dumps(primary_projection(value)), doc)
        catalogue = {p['source_id']: p for p in source_index(doc)['source_catalogue']}
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
        facts = []
        for index, fact in enumerate(context.extraction.facts):
            raw = fact.model_dump(mode='json')
            facts.append({**raw, 'context_fact_id': 'clinical-' + digest([source_key(raw_source), index, raw])[:24],
                          'original_fact_index': index, 'source_id': source.source_id})
        result.append({'document_id': context.extraction.document_id, 'source_id': source.source_id,
                       'source_sha256': source_key(raw_source), 'patient_id': source.patient_id,
                       'request_id': case.request.request_id, 'context_only': True,
                       'scope_status': 'EXCLUDED' if issue else 'IN_SCOPE', 'exclusion_reason': issue,
                       'facts': facts, 'relationships': [r.model_dump(mode='json') for r in context.extraction.relationships],
                       'boundary': 'Supplied clinical interpretations retain their evidence; they do not establish referral intent, PA form, eligibility or rule satisfaction.'})
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
                facts.append(original)
            supplied = ClinicalContext.model_validate({'source_id': context['source_id'], 'extraction': {
                'document_id': context['document_id'], 'facts': facts, 'relationships': context['relationships']}})
            validate_context_sources(SimpleNamespace(sources=[Source.model_validate_json(json.dumps(raw_source))], clinical_context=[supplied]))
            checks.append(bool(valid))
        except (KeyError, ValueError, TypeError, IndexError):
            checks.append(False)
    return checks
