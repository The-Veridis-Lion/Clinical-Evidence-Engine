"""Bounded transport for the existing SourceReview contract; no new verifier.

Wire identities and proposed values are expanded only from the frozen request.
Full original text is retained for every batch; splitting never changes offsets.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Literal

from pydantic import Field

from ..models import Claim, DimensionCheck, Model, Source, SourceReview, Span, digest
from ..verifier import DIMENSIONS, EvidenceVerifier

TRANSPORT_VERSION = 'bounded-source-review/1'
MAX_CLAIMS = 2
MAX_SOURCE_CHARACTERS = 24000
MAX_RESPONSE_CHARACTERS = 64000


class SchemaPreflightError(ValueError):
    pass


def strict_schema_preflight(schema: dict) -> dict:
    """Reject unsupported/open JSON schemas before model reservation or dispatch.

    This validates the subset used here, not every possible provider schema.
    No field type, optionality, or source semantics is silently rewritten.
    """
    if not isinstance(schema, dict) or schema.get('type') != 'object':
        raise SchemaPreflightError('Root must be an explicitly typed object')
    prohibited = {'allOf', 'not', 'dependentRequired', 'dependentSchemas', 'if', 'then', 'else', 'patternProperties', 'default'}
    definitions = schema.get('$defs', {})
    def visit(node, path):
        if not isinstance(node, dict):
            raise SchemaPreflightError(f'{path}: schema node must be an object')
        bad = prohibited.intersection(node)
        if bad:
            raise SchemaPreflightError(f'{path}: unsupported keywords {sorted(bad)}')
        if '$ref' in node:
            ref = node['$ref']
            if not isinstance(ref, str) or not ref.startswith('#/$defs/') or ref[8:] not in definitions:
                raise SchemaPreflightError(f'{path}: unresolved local reference')
        elif 'anyOf' in node:
            if not isinstance(node['anyOf'], list) or not node['anyOf']:
                raise SchemaPreflightError(f'{path}: invalid anyOf')
            for i, branch in enumerate(node['anyOf']):
                visit(branch, f'{path}/anyOf/{i}')
        elif node.get('type') not in {'object', 'array', 'string', 'number', 'integer', 'boolean', 'null'}:
            raise SchemaPreflightError(f'{path}: missing or unsupported explicit type')
        if node.get('type') == 'object':
            properties = node.get('properties')
            if not isinstance(properties, dict) or node.get('additionalProperties') is not False:
                raise SchemaPreflightError(f'{path}: object must have properties and additionalProperties:false')
            required = node.get('required')
            if not isinstance(required, list) or len(required) != len(set(required)) or set(required) != set(properties):
                raise SchemaPreflightError(f'{path}: every property must be required')
            for key, value in properties.items():
                visit(value, f'{path}/properties/{key}')
        if node.get('type') == 'array':
            visit(node.get('items'), f'{path}/items')
    visit(schema, '#')
    for name, definition in definitions.items():
        visit(definition, f'#/$defs/{name}')
    return deepcopy(schema)


class WireSpan(Model):
    start: int
    end: int


class WireDimension(Model):
    dimension: str
    status: Literal['SUPPORTED', 'CONTRADICTED', 'UNVERIFIED', 'NOT_ASSERTED']
    source_value_json: str
    reason: str
    spans: list[WireSpan]


class WireReview(Model):
    claim_id: str
    status: Literal['SUPPORTED_BY_SOURCE', 'CONTRADICTED', 'INSUFFICIENT_EVIDENCE', 'CONFLICTED']
    dimension_checks: list[WireDimension]
    supporting_spans: list[WireSpan]
    counter_spans: list[WireSpan]
    reason: str
    uncertainty: list[str]


class WireBatch(Model):
    reviews: list[WireReview]


def review_schema() -> dict:
    # All wire fields have no defaults. Existing canonical nullable/open fields
    # are not sent as unconstrained Any or maps; they are lossless JSON strings.
    return strict_schema_preflight(WireBatch.model_json_schema())


def asserted_dimensions(claim: Claim) -> dict:
    values = {name: getattr(claim, name) for name in DIMENSIONS if name != 'attributes'}
    values.update({'attributes.' + key: value for key, value in claim.attributes.items() if value is not None})
    values['source_context'] = 'full_source_scope_resolved'
    return values


def prepare_review_batch(source: Source | dict, claims: list[Claim | dict]) -> dict:
    source = Source.model_validate(source)
    claims = [Claim.model_validate(c) for c in claims]
    if not 1 <= len(claims) <= MAX_CLAIMS:
        raise ValueError(f'Bounded review requires 1..{MAX_CLAIMS} claims')
    if len(source.text) > MAX_SOURCE_CHARACTERS:
        raise ValueError('Full source exceeds bounded task limit; never truncate source to fit')
    if len({c.claim_id for c in claims}) != len(claims):
        raise ValueError('Duplicate claim IDs in review batch')
    for claim in claims:
        if (claim.source_id, claim.patient_id, claim.encounter_id) != (source.source_id, source.patient_id, source.encounter_id):
            raise ValueError('Claim source/patient/encounter mismatch')
        if not all(source.check_span(s) for s in claim.spans):
            raise ValueError('Invalid original claim span')
    schema = review_schema()
    batch = {'transport_version': TRANSPORT_VERSION, 'source': source.model_dump(mode='json'),
             'claims': [{'claim': c.model_dump(mode='json'), 'claim_fingerprint': c.fingerprint(),
                         'dimensions': asserted_dimensions(c)} for c in claims],
             'schema_sha256': digest(schema)}
    batch['request_identity'] = digest(batch)
    return batch


def review_prompt(batch: dict) -> str:
    return (
        'Verify these immutable claims against the FULL original source. Return exactly one review for each claim_id; '
        'no tools, no reference note, no outside clinical facts. All offsets are original Unicode code-point indices, end exclusive. '
        'Check every listed dimension independently. source_value_json is a valid JSON value string: e.g. '
        '\"patient\" including quotes, null, 2, false. SUPPORTED requires source entailment and exact matching source value; '
        'CONTRADICTED requires exact counterevidence; missing information is UNVERIFIED, not false. '
        'Unknown proposal fields use NOT_ASSERTED. Source_context must explicitly evaluate the entire source for cross-sentence '
        'negation, attribution, time, hypothetical conditions, and conflicting statements; use full source span for that dimension. '
        'Prescribing is not taking, one dose is not a full course, conditional discussion is not committed plan or completion, '
        'no documentation is not clinical absence. Whole SUPPORTED_BY_SOURCE requires all asserted known dimensions supported. '
        'Use INSUFFICIENT_EVIDENCE for unresolved dimensions, CONFLICTED for unresolved conflicting original statements. '
        'Evidence spans must be exact existing source ranges. Keep reasons short and specific. '
        'This is fallible AI source verification, not expert clinical validation. Do not force a positive judgment.\n'
        + json.dumps(batch, ensure_ascii=False, sort_keys=True))


def parse_review_response(raw: str, batch: dict, *, request_uid: str, model_version: str) -> list[SourceReview]:
    if len(raw) > MAX_RESPONSE_CHARACTERS:
        raise ValueError('Response exceeds bounded review output limit')
    source = Source.model_validate(batch['source'])
    original = prepare_review_batch(source, [item['claim'] for item in batch['claims']])
    if original != batch:
        raise ValueError('Frozen review request identity or claim fingerprint changed')
    response = WireBatch.model_validate_json(raw)
    claims = {item['claim']['claim_id']: Claim.model_validate(item['claim']) for item in batch['claims']}
    if len(response.reviews) != len(claims) or {r.claim_id for r in response.reviews} != set(claims):
        raise ValueError('Review response omits, duplicates, or adds claim IDs')
    def expand_span(wire):
        span = Span(start=wire.start, end=wire.end, quote=source.text[wire.start:wire.end], source_id=source.source_id)
        if not source.check_span(span):
            raise ValueError('Review evidence outside original source')
        return span
    result = []
    for wire in response.reviews:
        claim = claims[wire.claim_id]
        proposed = asserted_dimensions(claim)
        names = [d.dimension for d in wire.dimension_checks]
        if len(names) != len(set(names)) or set(names) != set(proposed):
            raise ValueError('Response must cover exactly every requested dimension')
        checks = [DimensionCheck(dimension=d.dimension, status=d.status, proposed=proposed[d.dimension],
                                 source_value=json.loads(d.source_value_json), reason=d.reason,
                                 spans=[expand_span(s) for s in d.spans]) for d in wire.dimension_checks]
        review = SourceReview(review_id=digest([request_uid, claim.claim_id]), source_id=source.source_id,
                              source_hash=source.sha256, patient_id=source.patient_id, encounter_id=source.encounter_id,
                              claim_fingerprint=claim.fingerprint(), status=wire.status, dimension_checks=checks,
                              supporting_spans=[expand_span(s) for s in wire.supporting_spans],
                              counter_spans=[expand_span(s) for s in wire.counter_spans], reason=wire.reason,
                              method=TRANSPORT_VERSION, model_version=model_version, reviewer_type='advanced_ai',
                              uncertainty=wire.uncertainty)
        # Full context is mandatory in this transport, irrespective of whether
        # the bounded native detector happened to recognize that qualifier.
        context = next(d for d in checks if d.dimension == 'source_context')
        if not any(s.start == 0 and s.end == len(source.text) for s in context.spans):
            raise ValueError('Review must retain full-source context proof')
        EvidenceVerifier._validate_review(source, claim, review, context_spans=[Span(start=0, end=len(source.text), quote=source.text, source_id=source.source_id)])
        result.append(review)
    return result
