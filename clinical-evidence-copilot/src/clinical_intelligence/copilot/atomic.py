"""Source-unit coverage checklist with independently supplied atomic assertions.

Citation overlap is recorded separately from semantic coverage. In particular a
fully cited sentence can contain an uncovered assertion. No source meaning or
absence is inferred from string matching. This module makes that limitation
visible and accepts explicit, source-grounded independent coverage decisions.
"""
from pydantic import BaseModel, ConfigDict, Field

from .models import digest
from .source_adapter import source_index, speaker_annotations

VERSION = 'copilot-atomic-coverage/v1'
VERIFIED_VERSION = 'copilot-atomic-coverage/v2'


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


class IndependentAssertion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    assertion_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_spans: list[SourceSpan] = Field(min_length=1)
    category: str
    experiencer: str
    polarity: str
    temporality: str
    action_state: str = 'unknown'
    attributes: dict = Field(default_factory=dict)
    origin: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    reviewer_type: str
    reviewer_version: str = Field(min_length=1)
    decision: str = 'UNVERIFIED'
    covered_by_fact_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


def checked_assertions(raw, source, fact_ids):
    results = []
    seen = set()
    for value in raw:
        atom = IndependentAssertion.model_validate(value)
        if atom.assertion_id in seen:
            raise ValueError('Duplicate independent atomic assertion ID')
        seen.add(atom.assertion_id)
        if atom.reviewer_type not in {'human','ai'} or atom.decision not in {'COVERED','UNCOVERED','DISPUTED','UNVERIFIED'}:
            raise ValueError('Invalid atomic reviewer/coverage decision')
        for span in atom.source_spans:
            if not 0 <= span.start < span.end <= len(source.text) or source.text[span.start:span.end] != span.quote:
                raise ValueError('Independent atomic assertion source mismatch')
        if not set(atom.covered_by_fact_ids) <= set(fact_ids):
            raise ValueError('Atomic coverage names unknown fact IDs')
        if (atom.decision == 'COVERED') != bool(atom.covered_by_fact_ids):
            raise ValueError('Only an explicit COVERED decision may link covering facts')
        results.append(atom.model_dump())
    return results


def checklist(packet, independent_assertions=()):
    independent = checked_assertions(independent_assertions, packet.source, [f.fact_id for f in packet.facts])
    units = []
    for unit in source_index(packet.source.document())['source_catalogue']:
        overlap = [f.fact_id for f in packet.facts if any(p.start < unit['end'] and unit['start'] < p.end for p in f.assertion.provenance)]
        atom_ids = [a['assertion_id'] for a in independent if any(s['start'] < unit['end'] and unit['start'] < s['end'] for s in a['source_spans'])]
        units.append({**unit, 'unit_id': 'unit-'+digest([packet.source.sha256,unit['start'],unit['end']])[:20],
            'citing_fact_ids': overlap, 'independent_assertion_ids': atom_ids,
            'citation_status': 'CITED' if overlap else 'UNCITED', 'semantic_coverage': 'UNVERIFIED'})
    predictions = [{'assertion_id': 'prediction-'+f.fact_id, 'fact_id': f.fact_id,
        'category': f.assertion.category, 'concept': f.assertion.concept,
        'experiencer': f.assertion.experiencer, 'polarity': f.assertion.polarity,
        'temporality': f.assertion.temporality, 'attributes': f.assertion.attributes.model_dump() if f.assertion.attributes else {},
        'source_spans': [{'start': p.start,'end': p.end,'quote': p.quote} for p in f.assertion.provenance],
        'semantic_support': 'UNVERIFIED'} for f in packet.facts]
    value = {'version': VERSION, 'source_sha256': packet.source.sha256,
        'source_units': units, 'prediction_assertions': predictions,
        'independent_source_assertions': independent, 'speaker_annotations': speaker_annotations(packet.source.document()),
        'semantic_completeness': 'UNVERIFIED', 'reference_type': 'explicit_source_grounded_review_or_unverified',
        'limitation': 'Citation overlap never establishes semantic support or completeness; unenumerated assertions remain unknown.'}
    if packet.extraction_metadata.get('soap_projection_version') == 'soap/v5':
        value['version'] = VERIFIED_VERSION
        value['automatic_source_coverage'] = automatic_source_coverage(packet)
        value['reference_type'] = 'partial_bounded_source_enumeration_and_explicit_independent_review'
    return value


def automatic_source_coverage(packet):
    """Enumerate the entire immutable source, including already-cited sentences.

    A partial lexical grammar is an explicit bounded check, not a second clinical
    extractor. Missing candidates remain separate and cannot directly enter SOAP.
    The same package is loaded by the CareFlow adapter.
    """
    from ..evidence_bridge import verification_package
    core = verification_package()
    source = core.Source(source_id=packet.source.document_id, text=packet.source.text,
        sha256=packet.source.sha256, patient_id=packet.patient_id,
        encounter_id=packet.case_id, available_at=None, input_kind=packet.source.input_kind)
    claims = []
    for item in packet.facts:
        fact = item.assertion
        attributes = {k:v for k,v in (fact.attributes.model_dump() if fact.attributes else {}).items() if v is not None}
        claims.append(core.Claim(claim_id=item.fact_id, source_id=source.source_id,
            patient_id=packet.patient_id, encounter_id=source.encounter_id,
            category=fact.category, concept=fact.concept,
            spans=[core.Span(start=p.start,end=p.end,quote=p.quote,source_id=source.source_id) for p in fact.provenance],
            experiencer=fact.experiencer, reporting_basis=fact.assertion_basis or 'unknown',
            polarity=fact.polarity, temporality=fact.temporality, attributes=attributes))
    external=packet.extraction_metadata.get('source_atomic_enumeration')
    independent=[]
    if external is not None:
        expected_fields={'source_id','source_sha256','patient_id','encounter_id','assertions','method','raw_response_sha256','request_uid'}
        if not isinstance(external,dict) or set(external)!=expected_fields:
            raise ValueError('Source-first model enumeration requires complete audit envelope')
        if (external['source_id']!=source.source_id or external['source_sha256']!=source.sha256 or
            external['patient_id']!=source.patient_id or external['encounter_id']!=source.encounter_id):
            raise ValueError('Source-first model enumeration identity/hash mismatch')
        if not external['method'] or not external['request_uid'] or not isinstance(external['raw_response_sha256'],str) or len(external['raw_response_sha256'])!=64 or any(c not in '0123456789abcdef' for c in external['raw_response_sha256']):
            raise ValueError('Source-first model enumeration missing original request/raw-response identity')
        if not isinstance(external['assertions'],list):
            raise ValueError('Source-first model enumeration assertions must be a list')
        independent=external['assertions']
    enumeration = core.enumerate_source_assertions(source,independent_assertions=independent)
    coverage = core.align_coverage(enumeration, claims)
    value = coverage.model_dump(mode='json')
    if external is not None:
        value['source_enumerator_audit']={k:v for k,v in external.items() if k!='assertions'}
        value['source_enumerator_audit']['reference_type']='independent_model_candidates_not_clinical_gold'
    value['claim_verifications'] = [core.EvidenceVerifier().verify(source,claim).model_dump(mode='json') for claim in claims]
    verified_candidates = []
    for candidate in coverage.omission_candidates:
        result = core.EvidenceVerifier().verify(source,candidate)
        verified_candidates.append({'assertion':candidate.model_dump(mode='json'),
            'source_verification':result.model_dump(mode='json'),
            'allow_fact_completion':False,
            'routing':'CORRECTION_CANDIDATE' if result.status=='SUPPORTED_BY_SOURCE' else result.risk_route,
            'reason':'A supported omitted source assertion still requires a targeted append/review workflow; no proposal is silently replaced.'})
    value['verified_omission_candidates'] = verified_candidates
    return value


def validate_checklist(value, packet):
    expected_version = VERIFIED_VERSION if packet.extraction_metadata.get('soap_projection_version') == 'soap/v5' else VERSION
    if value.get('version') != expected_version or value.get('source_sha256') != packet.source.sha256:
        raise ValueError('Atomic checklist version/source mismatch')
    original = packet.model_copy(deep=True)
    for fact in original.facts:
        from .evidence import ground_fact
        fact.assertion, _ = ground_fact(fact.original_fact, original.source)
    expected = checklist(original, value.get('independent_source_assertions', []))
    if expected != value:
        raise ValueError('Atomic checklist does not match original source/proposals')
    action = packet.extraction_metadata.get('action_state_checklist')
    if action is not None:
        from .action_state import inspect_action
        action_version = action.get('version')
        if action != {'version': action_version, 'assertions': [inspect_action(item,original.source,version=action_version) for item in original.facts],
                'interpretation': 'Lexical detector candidates are unverified; no clinical accuracy claim.'}:
            raise ValueError('Action checklist differs from original source/proposals')


def coverage_report(packet):
    value = packet.extraction_metadata.get('atomic_source_checklist')
    if not value:
        return {'version': VERSION, 'semantic_completeness': 'UNVERIFIED', 'independent_assertions': 0}
    atoms = value['independent_source_assertions']
    decisions = {k: sum(a['decision']==k for a in atoms) for k in ('COVERED','UNCOVERED','DISPUTED','UNVERIFIED')}
    report = {'version': value['version'], 'semantic_completeness': 'UNVERIFIED',
        'source_units': len(value['source_units']), 'cited_source_units': sum(bool(u['citing_fact_ids']) for u in value['source_units']),
        'independent_assertions': len(atoms), 'coverage_decisions': decisions,
        'uncovered_assertion_ids': [a['assertion_id'] for a in atoms if a['decision']=='UNCOVERED'],
        'unresolved_assertion_ids': [a['assertion_id'] for a in atoms if a['decision'] in {'DISPUTED','UNVERIFIED'}],
        'reference_types': sorted({a['reviewer_type'] for a in atoms}),
        'note': 'Counts describe supplied independent assertions only; no inferred complete source denominator.'}
    if value['version'] == VERIFIED_VERSION:
        automatic = value['automatic_source_coverage']
        report['automatic_source_coverage'] = {'semantic_completeness':automatic['semantic_completeness'],
            'enumerated_assertions':len(automatic['enumeration']['assertions']),
            'omission_candidates':len(automatic['verified_omission_candidates']),
            'supported_omission_candidate_ids':[c['assertion']['claim_id'] for c in automatic['verified_omission_candidates']
                if c['source_verification']['status']=='SUPPORTED_BY_SOURCE'],
            'misaligned_claim_ids':automatic['misaligned_claim_ids'],
            'unsupported_claim_ids':automatic['unsupported_claim_ids'],
            'unmatched_claim_ids':automatic['unmatched_claim_ids'],
            'duplicate_claim_groups':automatic['duplicate_claim_groups'],
            'unrepresented_attributes':automatic['unrepresented_attributes'],
            'unresolved_attributes':automatic['unresolved_attributes'],
            'unresolved_units':len(automatic['enumeration']['unresolved_units'])}
        report['note'] = 'Automatic counts use only a partial, independently source-enumerated denominator; supplied judgments and unknown source meanings stay separate.'
    return report
