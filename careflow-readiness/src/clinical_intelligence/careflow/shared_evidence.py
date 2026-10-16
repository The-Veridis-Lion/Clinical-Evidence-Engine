"""Read saved Copilot revisions; never dispatch a second clinical extraction.

Only the server chooses the database. Immutable, verified source snapshots are
retained inside the ordinary CareFlow revision, including the upstream review
lineage. Public Case/evidence intake already rejects structured context.
"""
from datetime import date
from functools import lru_cache
import importlib
import json
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import Field, model_validator

from ..claims_review.prepare import digest
from .clinical_intake import ClinicalAssociation, clinical_reason_bindings, clinical_target_bindings
from .contracts import Contract, Identifier, Request, Source
from .raw_input import build_case
from .service import RevisionConflict

VERSION = 'careflow-shared-copilot-snapshot/1'


class SavedSourceRef(Contract):
    case_id: Identifier
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


class SharedIntake(Contract):
    schema_version: Literal['careflow-shared-intake/1'] = 'careflow-shared-intake/1'
    case_id: Identifier
    request: Request
    review_as_of: date
    received_at: date
    sources: list[SavedSourceRef] = Field(min_length=1, max_length=100)
    materials: list[Source] = Field(default_factory=list, max_length=200)
    clinical_reason: str | None = Field(default=None, max_length=4000)
    clinical_associations: list[ClinicalAssociation] = Field(default_factory=list, max_length=100)
    summary_case_ids: list[Identifier] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_sources(self):
        ids = [ref.case_id for ref in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError('Select each saved Copilot case once')
        if len(self.summary_case_ids) != len(set(self.summary_case_ids)) or not set(self.summary_case_ids) <= set(ids):
            raise ValueError('Summary attachment must select distinct referenced cases')
        return self


class SharedSync(Contract):
    expected_revision: int = Field(ge=1)
    basis_packet_sha256: Identifier
    sources: list[SavedSourceRef] = Field(min_length=1, max_length=100)
    received_at: date
    # A new active-workflow date is explicit. Omission preserves the old
    # historical cutoff; newly received evidence may then remain out of scope.
    review_as_of: date | None = None
    actor_id: Identifier
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode='after')
    def unique_sources(self):
        if len({ref.case_id for ref in self.sources}) != len(self.sources) or not self.reason.strip():
            raise ValueError('Distinct saved cases and an explicit synchronization reason are required')
        return self


def _copilot(name):
    """Use the installed package, or the sibling product in a source checkout."""
    import clinical_intelligence
    sibling = Path(__file__).resolve().parents[4] / 'clinical-evidence-copilot/src/clinical_intelligence'
    if sibling.is_dir() and str(sibling) not in clinical_intelligence.__path__:
        clinical_intelligence.__path__.append(str(sibling))
    return importlib.import_module('clinical_intelligence.copilot.' + name)


@lru_cache(maxsize=64)
def _verified_chain(serialized):
    models, store = _copilot('models'), _copilot('store')
    packets = [models.Packet.model_validate(raw).verify() for raw in json.loads(serialized)]
    if not packets:
        raise ValueError('Shared evidence requires a saved source lineage')
    previous = None
    for version, packet in enumerate(packets, 1):
        if (packet.version != version or packet.parent_hash != (previous.content_hash if previous else None)
                or previous and (packet.case_id != previous.case_id or packet.patient_id != previous.patient_id
                                 or packet.source != previous.source)):
            raise ValueError('Saved Copilot version chain is inconsistent')
        metadata = packet.extraction_metadata
        if (metadata.get('evidence_usage') == 'offline-evaluation/1'
                or metadata.get('source_verification_reviews')
                or metadata.get('source_review_import_audit')
                or metadata.get('mode', '').startswith('offline_')):
            raise ValueError('Offline source judgments are not shared product evidence')
        if previous:
            processing = _copilot('reprocessing')
            if metadata.get(processing.EVENTS, []) != previous.extraction_metadata.get(processing.EVENTS, []):
                processing.validate_program_revision(previous, packet)
            elif previous.extraction_metadata.get('soap_projection_version') in {'soap/v5', 'soap/v6'}:
                if packet.reviews[:-1] != previous.reviews or len(packet.reviews) != len(previous.reviews) + 1:
                    raise ValueError('Saved Copilot review lineage is inconsistent')
                store.validate_verified_revision(previous, packet, packet.reviews[-1])
            else:
                store.CaseStore.validate_legacy_revision(previous, packet)
        elif packet.reviews or metadata.get('program_reprocessing_events'):
            raise ValueError('First saved packet cannot contain unlinked review history')
        previous = packet
    return packets


class SharedEvidenceReader:
    def __init__(self, database):
        self.path = Path(database).resolve()

    def read(self, refs, patient_id):
        # mode=ro and query_only prohibit initialization, migration and writes.
        with sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            result = []
            for ref in refs:
                rows = conn.execute('SELECT * FROM versions WHERE case_id=? ORDER BY version', (ref.case_id,)).fetchall()
                if not rows:
                    raise ValueError('Referenced saved Copilot case does not exist')
                if rows[-1]['version'] != ref.version:
                    raise RevisionConflict('Shared Copilot reference is stale; reload current saved versions')
                serialized = json.dumps([json.loads(row['payload']) for row in rows], sort_keys=True)
                packets = _verified_chain(serialized)
                for row, packet in zip(rows, packets):
                    if any(row[key] != value for key, value in {
                        'case_id': packet.case_id, 'version': packet.version, 'patient_id': packet.patient_id,
                        'source_hash': packet.source.sha256, 'content_hash': packet.content_hash,
                        'parent_hash': packet.parent_hash, 'created_at': packet.created_at}.items()):
                        raise ValueError('Saved Copilot row differs from its verified packet')
                current = packets[-1]
                if current.patient_id != patient_id:
                    raise ValueError('Saved Copilot source belongs to a different patient')
                if current.content_hash != ref.content_hash:
                    raise ValueError('Saved Copilot content hash differs from the requested reference')
                result.append((current, json.loads(serialized)))
            return result


def _current_extraction(packet):
    # Copy the current assertion, never the original proposal after correction.
    return {'document_id': packet.source.document_id,
            'facts': [item.assertion.model_dump(mode='json') for item in packet.facts],
            'relationships': [row['original'] for row in packet.relationships]}


def checked_snapshot(context, source):
    """Reconstruct per-fact consumption from the retained real saved lineage.

    This is an immutable snapshot contract, not a caller trust bit. The intake
    reads the database first; ordinary create/update reject structured contexts.
    """
    retained = context.structured_extraction
    if set(retained) != {'version', 'packets'} or retained['version'] != VERSION:
        raise ValueError('Invalid shared Copilot snapshot contract')
    packets = _verified_chain(json.dumps(retained['packets'], sort_keys=True))
    packet = packets[-1]
    locator = source.original_locator or {}
    ref = {key: locator.get(key) for key in ('case_id', 'version', 'content_hash')}
    if (ref != {'case_id': packet.case_id, 'version': packet.version, 'content_hash': packet.content_hash}
            or source.patient_id != packet.patient_id or source.content != packet.source.text
            or locator.get('source_sha256') != packet.source.sha256
            or locator.get('document_id') != packet.source.document_id
            or context.extraction.model_dump(mode='json') != _current_extraction(packet)):
        raise ValueError('Shared source/current assertions differ from saved Copilot packet')
    records = {row['fact_id']: row for row in packet.extraction_metadata.get('evidence_verification', {}).get('assertions', [])}
    originals = {row['fact_id']: row for row in packet.extraction_metadata.get('structured_extraction_contract', {}).get('assertions', [])}
    semantics = _copilot('semantics').checked_records(packet)
    result = {}
    for index, item in enumerate(packet.facts):
        record = records.get(item.fact_id, {})
        semantic = semantics.get(item.fact_id)
        # The saved verifier records whether the original sidecar became stale.
        # It also retains any explicit human semantic amendment separately.
        applied = semantic if record.get('semantic_application') != 'UNAPPLIED_AFTER_FACT_CORRECTION' else None
        original = originals.get(item.fact_id)
        changed = (item.assertion.model_dump() != item.original_fact
                   or applied is not None and applied.get('origin') != 'original_structured_extraction')
        model_proposal = bool(original and not changed)
        claim = record.get('adopted_claim', record.get('proposed_claim', {}))
        value = dict(applied['semantics']) if applied else {}
        # Use the current saved adopted claim for all applied event dimensions;
        # in particular, a stale completed-course sidecar cannot regain support.
        if claim:
            value.update({key: claim.get(key) for key in ('event_time', 'action_type', 'action_state', 'completion_scope')})
            value.update(duration=claim.get('attributes', {}).get('duration'),
                         frequency=claim.get('attributes', {}).get('frequency'),
                         assertion_basis=claim.get('reporting_basis', 'unknown'))
        provenance = [p.model_dump(mode='json') for p in item.assertion.provenance]
        primary = (original.get('primary_source_id') if model_proposal else None)
        # An invalid/missing original model anchor remains invalid. Only a
        # changed current assertion can select its own current cited span for
        # the independent source recheck; there is no repaired Luna proposal.
        if not model_proposal and primary not in {p['source_id'] for p in provenance}:
            primary = provenance[0]['source_id'] if provenance else None
        human_correction = next((review.model_dump(mode='json') for review in reversed(packet.reviews)
            if review.fact_id == item.fact_id and review.action == 'correct'
            and review.reviewer.reviewer_type == 'human'
            and review.after == item.assertion.model_dump()), None)
        upstream = {'case_id': packet.case_id, 'version': packet.version, 'content_hash': packet.content_hash,
                    'document_id': packet.source.document_id, 'fact_id': item.fact_id,
                    'source_sha256': packet.source.sha256,
                    'upstream_request_key': packet.extraction_metadata.get('request_key'),
                    'original_extraction_sha256': digest(packet.extraction_metadata.get('structured_extraction_contract')),
                    'current_assertion_sha256': digest(item.assertion.model_dump(mode='json')),
                    'current_semantic_record': applied,
                    'semantic_application': record.get('semantic_application'),
                    'current_human_correction': human_correction,
                    'consumption': 'saved_structured_model_proposal' if model_proposal else 'current_saved_assertion_source_recheck',
                    'clinical_expert_validation': 'NOT_ESTABLISHED', 'new_model_calls': 0}
        result[index] = {'task_version': packet.extraction_metadata.get('extraction_task_version'),
            # CaseStore stores a durable normalized extraction and request key;
            # a raw-response hash is reported only when actually retained.
            'raw_response_sha256': packet.extraction_metadata.get('raw_response_sha256'),
            'source_sha256': packet.source.sha256, 'semantics': value,
            'anchor': {'fact_index': index, 'wire_fact_id': (original or {}).get('wire_fact_id', item.fact_id),
                       'primary_source_id': primary, 'selected_source_ids': [p['source_id'] for p in provenance]},
            'invalid_fields': applied.get('invalid_fields', []) if applied else [],
            'shared_evidence': upstream}
    return result


def _assemble(intake, loaded):
    from ..claims_review.facts import source_key
    from .requirement_support import material_envelope
    sources, contexts, identities = [], [], []
    for packet, chain in loaded:
        ref = {'case_id': packet.case_id, 'version': packet.version, 'content_hash': packet.content_hash}
        source_id = 'shared-' + digest([ref, intake.received_at.isoformat()])[:24]
        source = {'source_id': source_id, 'patient_id': packet.patient_id,
            # A saved document does not acquire the request's encounter identity.
            'encounter_id': None, 'available_at': intake.received_at.isoformat(),
            'origin': 'request_intake', 'source_kind': 'clinical_text', 'record_type': 'note',
            'recorded_at': None, 'event_date': None, 'event_link_id': None,
            'availability_basis': 'explicit_case_metadata', 'content': packet.source.text,
            'original_locator': {**ref, 'document_id': packet.source.document_id, 'dataset': 'copilot',
                'input_kind': packet.source.input_kind, 'source_sha256': packet.source.sha256,
                'encounter_time': packet.source.encounter_time, 'shared_contract': VERSION}}
        sources.append(source)
        contexts.append({'source_id': source_id, 'extraction': _current_extraction(packet),
            'source_index_version': 'copilot-source-index/v1',
            'structured_extraction': {'version': VERSION, 'packets': chain}})
        identities.append({**ref, 'document_id': packet.source.document_id,
            'source_id': source_id, 'source_sha256': packet.source.sha256,
            'fact_ids': [f.fact_id for f in packet.facts]})
        if packet.case_id in intake.summary_case_ids:
            attachment_id = source_id + ':summary'
            scope = {key: getattr(intake.request, key) for key in ('patient_id', 'request_id', 'service_code', 'code_system')}
            sources.append({**source, 'source_id': attachment_id, 'source_kind': 'structured_record',
                'record_type': 'order', 'original_locator': None,
                'content': {'material': {**scope, 'document_type': 'clinical_summary',
                    'document_role': 'clinical_summary', 'summary_source_id': source_id,
                    'summary_sha256': source_key(source)},
                    'requirement_support': material_envelope(intake.request.model_dump(mode='json'),
                        'clinical_summary', 'clinical_summary', {'source_id': attachment_id, 'field': 'material'}),
                    'intake_declaration': 'Explicitly attached saved source as clinical summary; no independent clinical certification.'}})
    shared_source_ids = [s['source_id'] for s in sources]
    case, receipt = build_case(intake.case_id, intake.request, intake.review_as_of,
                              [*sources, *intake.materials], extractions=contexts)
    reason_sources, bindings, decisions = clinical_reason_bindings(case, intake.clinical_reason, received_at=intake.received_at)
    target_sources, target_bindings, target_decisions = clinical_target_bindings(case, intake.clinical_associations, received_at=intake.received_at)
    shared_source_ids.extend(s.source_id for s in [*reason_sources, *target_sources])
    case, receipt = build_case(intake.case_id, intake.request, intake.review_as_of,
        [*case.sources, *reason_sources, *target_sources], extractions=case.clinical_context,
        clinical_bindings=[*bindings, *target_bindings])
    return case, receipt, {'schema_version': VERSION, 'sources': identities, 'model_calls': 0,
        'clinical_associations': [*decisions, *target_decisions],
        'shared_source_ids': shared_source_ids,
        'shared_binding_ids': [b.binding_id for b in [*bindings, *target_bindings]],
        'intake_configuration': intake.model_dump(mode='json', exclude={'materials'}),
        'boundary': 'Saved current Copilot assertions and source-linked amendments; original clinical validation is not upgraded. Independent order/form/payer materials remain required.'}


def shared_intake(app, intake, reader):
    from .engine import evaluate
    case, receipt, shared = _assemble(intake, reader.read(intake.sources, intake.request.patient_id))
    packet = evaluate(case)
    with app.store.transaction() as conn:
        if conn.execute('SELECT 1 FROM revisions WHERE case_id=?', (case.case_id,)).fetchone():
            raise RevisionConflict('Case already exists')
        app.store.append_revision(conn, case, packet)
        app.store.append_event(conn, case.case_id, 'CASE_CREATED', {
            'revision': 1, 'packet_sha256': packet['packet_sha256'], 'input_sha256': packet['input_sha256'],
            'ruleset_sha256': packet['ruleset']['sha256']})
        app.store.append_event(conn, case.case_id, 'SHARED_EVIDENCE_IMPORTED', shared)
    return {'packet': packet, 'intake_receipt': receipt, 'shared_evidence_receipt': shared}


def sync_shared(app, case_id, sync, reader):
    from .contracts import Case
    from .clinical_context import prepared_context
    from ..claims_review.facts import source_key
    from .engine import evaluate
    with app.store.transaction() as conn:
        current, previous = app.store.load(conn, case_id)
        if (sync.expected_revision != previous['revision']
                or sync.basis_packet_sha256 != previous['packet_sha256']):
            raise RevisionConflict('Shared synchronization refers to a stale revision or packet hash')
        events = conn.execute("SELECT event_json FROM events WHERE case_id=? ORDER BY sequence DESC", (case_id,)).fetchall()
        shared = next((json.loads(row[0])['payload'] for row in events
                       if json.loads(row[0])['event_type'] in {'SHARED_EVIDENCE_IMPORTED', 'SHARED_EVIDENCE_SYNCED'}), None)
        if shared is None:
            raise ValueError('This request was not created from shared saved evidence')
        configuration = shared['intake_configuration']
        if {ref.case_id for ref in sync.sources} != {ref['case_id'] for ref in configuration['sources']}:
            raise ValueError('Synchronize the complete previously bound source set')
        removed = set(shared['shared_source_ids'])
        # These are active snapshots. Their historical versions remain immutable
        # in older revisions; keeping both active would resurrect stale facts.
        materials = [s for s in current['sources'] if s['source_id'] not in removed]
        intake = SharedIntake.model_validate_json(json.dumps({**configuration,
            'sources': [ref.model_dump(mode='json') for ref in sync.sources],
            'received_at': sync.received_at.isoformat(),
            'review_as_of': (sync.review_as_of.isoformat() if sync.review_as_of is not None
                             else configuration['review_as_of']),
            'materials': materials}))
        case, receipt, updated = _assemble(intake, reader.read(sync.sources, intake.request.patient_id))
        raw = case.model_dump(mode='json')
        preserved = [f for f in current['facts'] if not any(ref['source_id'] in removed
            for ref in f['evidence'] + ([f['authority_ref']] if f.get('authority_ref') else []))]
        existing_ids = {f['fact_id'] for f in preserved}
        raw['facts'] = preserved + [f for f in raw['facts'] if f['fact_id'] not in existing_ids]
        raw['clinical_context'] += [c for c in current.get('clinical_context', []) if c['source_id'] not in removed]
        # A user may have selected an exact fact after initial intake. Its
        # request relevance follows the same durable Copilot fact identity,
        # while every clinical qualifier is still recomputed from the new
        # assertion. Content hashes/context IDs themselves never get reused.
        previous_identities = {fact['context_fact_id']: (upstream['case_id'], upstream['fact_id'])
            for context in previous.get('clinical_context', []) for fact in context['facts']
            if (upstream := (fact.get('structured_clinical_proposal') or {}).get('shared_evidence'))}
        current_identities = {(upstream['case_id'], upstream['fact_id']): fact['context_fact_id']
            for context in prepared_context(case) for fact in context['facts']
            if (upstream := (fact.get('structured_clinical_proposal') or {}).get('shared_evidence'))}
        source_by_id = {source['source_id']: source for source in current['sources']}
        rebound = []
        raw.setdefault('clinical_bindings', [])
        for binding in current.get('clinical_bindings', []):
            if binding['binding_id'] in shared['shared_binding_ids']:
                continue
            fact_ids = [current_identities[previous_identities[identity]]
                if identity in previous_identities else identity for identity in binding['clinical_fact_ids']]
            if fact_ids == binding['clinical_fact_ids']:
                raw['clinical_bindings'].append(binding)
                continue
            identity = digest([binding, fact_ids, sync.received_at.isoformat()])[:24]
            updated_binding = {**binding, 'binding_id': 'shared-selected-' + identity,
                'binding_source_id': 'shared-selection-' + identity, 'clinical_fact_ids': fact_ids}
            original_source = source_by_id[binding['binding_source_id']]
            selection = {'previous_binding_id': binding['binding_id'],
                'current_binding_id': updated_binding['binding_id'],
                'previous_clinical_fact_ids': binding['clinical_fact_ids'], 'current_clinical_fact_ids': fact_ids,
                'basis_revision': previous['revision'], 'basis_packet_sha256': previous['packet_sha256'],
                'actor_id': sync.actor_id, 'reason': sync.reason, 'new_model_calls': 0}
            raw['sources'].append({**original_source,
                'source_id': updated_binding['binding_source_id'], 'available_at': sync.received_at.isoformat(),
                'content': {**original_source['content'], 'clinical_binding': updated_binding,
                            'shared_fact_selection_sync': selection}})
            raw['clinical_bindings'].append(updated_binding)
            rebound.append(selection)
        updated['rebound_fact_selections'] = rebound
        case = Case.model_validate_json(json.dumps(raw))
        receipt.update(input_sha256=digest(case.model_dump(mode='json')),
            source_documents=len(case.sources),
            source_identities=[{'source_id': source.source_id,
                'source_sha256': source_key(source.model_dump(mode='json'))} for source in case.sources],
            clinical_assertions=sum(len(c.extraction.facts) for c in case.clinical_context),
            clinical_binding_candidates=len(case.clinical_bindings),
            preserved_existing_fact_count=len(preserved))
        packet = evaluate(case, revision=previous['revision'] + 1)
        app.store.append_revision(conn, case, packet)
        app.store.append_event(conn, case_id, 'PROGRAM_RECALCULATED', {
            'revision': packet['revision'], 'packet_sha256': packet['packet_sha256'],
            'input_sha256': packet['input_sha256'], 'ruleset_sha256': packet['ruleset']['sha256'],
            'basis_revision': previous['revision'], 'basis_packet_sha256': previous['packet_sha256'],
            'previous_review_as_of': previous['review_as_of'],
            'review_as_of': packet['review_as_of'], 'received_at': sync.received_at.isoformat(),
            'actor_id': sync.actor_id, 'reason': sync.reason, 'new_model_calls': 0,
            'previous_shared_sources': shared['sources'], 'current_shared_sources': updated['sources']})
        app.store.append_event(conn, case_id, 'SHARED_EVIDENCE_SYNCED', updated)
    return {'packet': packet, 'intake_receipt': receipt, 'shared_evidence_receipt': updated}
