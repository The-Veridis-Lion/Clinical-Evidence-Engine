"""Explicit zero-call program revisions in the existing immutable case lineage.

This is not a reviewer decision. SQLite validates the saved result by replaying
the deterministic transformation from the previous snapshot, including its source.
"""
from pydantic import Field
import hashlib
from pathlib import Path

from .models import Model, digest, now

VERSION = 'copilot-program-reprocessing/1'
EVENTS = 'program_reprocessing_events'


def implementation_hashes():
    root = Path(__file__).parent
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in ('reprocessing.py','source_derivations.py','service.py','defaults.py')}


class ReprocessRequest(Model):
    base_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


def apply_current_processing(packet):
    """Apply only the promoted current processor, never caller-supplied answers."""
    from . import defaults
    from .runtime import product_evidence_metadata
    from .service import COURSE_ADOPTION_VERSION
    from ..evidence_bridge import verification_contextual_configuration, verification_event_configuration
    # This function is called only by an explicit program revision or a newly
    # created default packet. Reading an old sealed version never reaches here.
    packet.extraction_metadata.update(product_evidence_metadata())
    if packet.extraction_metadata.get('extraction_task_version')=='clinical-structured-extraction/1':
        packet.extraction_metadata['completion_scope_adoption_version']=COURSE_ADOPTION_VERSION
    configuration = verification_contextual_configuration()
    configuration.update(verification_event_configuration(),
        evidence_usage='luna-only-product/1',
        source_interpretation_version=packet.extraction_metadata['source_interpretation_version'],
        source_semantics_correction_version=packet.extraction_metadata['source_semantics_correction_version'],
        source_event_comparability_version=('distinct-source-event-comparability/4'
            if packet.extraction_metadata.get('extraction_task_version') in {'clinical-event-assertions/1','clinical-structured-extraction/1'}
            else 'distinct-source-event-comparability/2'),
        main_assertion_scope_version='action-proposition-scope/2')
    packet.extraction_metadata['evidence_verification'] = {'configuration': configuration}
    if defaults.SOURCE_DERIVATIONS_ENABLED:
        apply_source_derivations(packet)
    if defaults.LOCAL_PROOF_ENABLED:
        from ..evidence_bridge import verification_local_configuration
        configuration = verification_local_configuration()
        configuration.update(verification_event_configuration(), evidence_usage='luna-only-product/1',
            source_semantics_correction_version=packet.extraction_metadata['source_semantics_correction_version'],
            source_interpretation_version=packet.extraction_metadata.get(
                'source_interpretation_version', 'bounded-source-grammar/4'),
            source_event_comparability_version='distinct-source-event-comparability/4',
            main_assertion_scope_version='action-proposition-scope/2')
        packet.extraction_metadata['evidence_verification'] = {'configuration': configuration}
    return packet


def apply_source_derivations(packet):
    from .source_derivations import derive_source_proposals
    from .models import Assertion
    from .semantics import SemanticsRecord
    from .evidence import ground_fact
    plan = derive_source_proposals(packet)
    records = packet.extraction_metadata.setdefault('clinical_semantics_v2', [])
    by_id = {r['fact_id']: r for r in records}
    for update in plan['semantic_updates']:
        record = by_id[update['fact_id']]
        if record['semantics'] != update['before']:
            raise ValueError('Derived attribute is not based on the retained proposal')
        record.update(semantics=update['after'], origin='program_source_derivation/1')
    for derived in plan['derived_facts']:
        f, spans = ground_fact(derived['original_fact'], packet.source)
        identity = 'f-' + digest([packet.case_id, derived['derivation_id']])[:20]
        if any(item.fact_id == identity for item in packet.facts):
            raise ValueError('Duplicate program-derived identity')
        packet.facts.append(Assertion(fact_id=identity, original_fact=f.model_dump(),
            assertion=f, evidence_ids=[e.evidence_id for e in spans]))
        for span in spans:
            if span not in packet.evidence:
                packet.evidence.append(span)
        records.append(SemanticsRecord(fact_id=identity, source_sha256=packet.source.sha256,
            semantics=derived['semantics'], origin='program_source_derivation/1').model_dump(mode='json'))
    if plan['semantic_updates'] or plan['derived_facts'] or plan['unresolved']:
        packet.extraction_metadata.setdefault('source_derivation_events', []).append(plan)
    return packet


def rebuild_checklists(packet):
    from .atomic import checklist
    from .evidence import ground_fact
    from .action_state import inspect_action, VERSION as action_version
    original = packet.model_copy(deep=True)
    for fact in original.facts:
        fact.assertion, _ = ground_fact(fact.original_fact, original.source)
    packet.extraction_metadata['atomic_source_checklist'] = checklist(original,
        packet.extraction_metadata.get('atomic_source_checklist', {}).get('independent_source_assertions', []))
    packet.extraction_metadata['action_state_checklist'] = {'version': action_version,
        'assertions': [inspect_action(item, original.source) for item in original.facts],
        'interpretation': 'Lexical detector candidates are unverified; no clinical accuracy claim.'}


def process_new_packet(packet):
    from . import defaults
    from .service import project
    if not (defaults.SOURCE_DERIVATIONS_ENABLED or defaults.LOCAL_PROOF_ENABLED):
        return packet
    apply_current_processing(packet)
    packet.extraction_metadata['soap_projection_version'] = 'soap/v6'
    packet.extraction_metadata['default_processing_profile'] = defaults.PROFILE_VERSION
    rebuild_checklists(packet)
    return project(packet)


def reprocess_packet(old, request, *, recorded_at=None):
    from . import defaults
    from .service import project
    old.verify()
    request = ReprocessRequest.model_validate(request)
    if request.base_version != old.version or not request.reason.strip():
        raise ValueError('Program reprocessing requires the current base version and a reason')
    if old.extraction_metadata.get('evidence_usage') != 'luna-only-product/1':
        raise ValueError('Program reprocessing is restricted to retained product inputs')
    if old.extraction_metadata.get('soap_projection_version') not in {'soap/v5', 'soap/v6'}:
        raise ValueError('Historical legacy projections remain readable; re-import their original input explicitly')
    p = old.model_copy(deep=True)
    apply_current_processing(p)
    p.version = old.version + 1
    p.parent_hash = old.content_hash
    p.created_at = recorded_at or now()
    # v6 can carry the original legacy fact without inventing missing sidecars.
    p.extraction_metadata['soap_projection_version'] = 'soap/v6'
    rebuild_checklists(p)
    project(p)
    before = {f.fact_id: f.model_dump(mode='json') for f in old.facts}
    after = {f.fact_id: f.model_dump(mode='json') for f in p.facts}
    changes = [{'fact_id': identity, 'before': before.get(identity), 'after': after.get(identity)}
               for identity in dict.fromkeys([*before, *after]) if before.get(identity) != after.get(identity)]
    event = {'version': VERSION, 'actor_type': 'program', 'reason': request.reason,
        'recorded_at': p.created_at, 'base_version': old.version, 'applied_version': p.version,
        'parent_hash': old.content_hash, 'source_sha256': old.source.sha256,
        'original_proposals_sha256': digest([f.original_fact for f in old.facts]),
        'original_request_key': old.extraction_metadata.get('request_key'),
        'profile_version': defaults.PROFILE_VERSION,
        'processor_implementation_sha256': implementation_hashes(),
        'profile': {'semantics_version': defaults.SEMANTICS_VERSION, 'task_version': defaults.TASK_VERSION,
                    'local_proof': defaults.LOCAL_PROOF_ENABLED, 'source_derivations': defaults.SOURCE_DERIVATIONS_ENABLED},
        'previous_configuration_sha256': digest(old.extraction_metadata.get('evidence_verification', {}).get('configuration')),
        'configuration_sha256': digest(p.extraction_metadata.get('evidence_verification', {}).get('configuration')),
        'changes': changes, 'model_calls': 0, 'human_review_created': False,
        'clinical_certification': False}
    p.extraction_metadata[EVENTS] = [*old.extraction_metadata.get(EVENTS, []), event]
    return p.seal().verify()


def validate_program_revision(old, packet):
    previous = old.extraction_metadata.get(EVENTS, [])
    events = packet.extraction_metadata.get(EVENTS, [])
    if (events[:len(previous)] != previous or len(events) != len(previous) + 1
            or packet.reviews != old.reviews):
        raise ValueError('Program events append exactly once and cannot manufacture reviewer decisions')
    event = events[-1]
    expected = reprocess_packet(old, {'base_version': old.version, 'reason': event.get('reason')},
                                recorded_at=event.get('recorded_at'))
    if packet != expected:
        raise ValueError('Program revision differs from deterministic current-source reprocessing')
