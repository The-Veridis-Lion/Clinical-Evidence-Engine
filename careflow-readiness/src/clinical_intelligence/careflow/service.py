"""Request lifecycle; reviews cannot override deterministic readiness."""
import json

from .contracts import Case, Review
from .engine import evaluate
from .storage import Store
from ..claims_review.prepare import digest
from .requirement_support import PRODUCT_SUPPORT_POLICY


class RevisionConflict(ValueError):
    pass


class CareFlow:
    def __init__(self, db):
        self.store = Store(db)

    def create(self, case):
        case = case.model_copy(update={'source_support_policy': PRODUCT_SUPPORT_POLICY})
        packet = evaluate(case)
        with self.store.transaction() as conn:
            if conn.execute('SELECT 1 FROM revisions WHERE case_id=?', (case.case_id,)).fetchone():
                raise RevisionConflict('Case already exists')
            self.store.append_revision(conn, case, packet)
            self.store.append_event(conn, case.case_id, 'CASE_CREATED', {
                'revision': 1, 'packet_sha256': packet['packet_sha256'], 'input_sha256': packet['input_sha256'],
                'ruleset_sha256': packet['ruleset']['sha256'],
            })
        return packet

    def packet(self, case_id, revision=None):
        with self.store.connect() as conn:
            return self.store.load(conn, case_id, revision)[1]

    def validate_review(self, conn, case_id, review):
        original, packet = self.store.load(conn, case_id, review.basis_revision)
        if review.basis_packet_sha256 != packet['packet_sha256']:
            raise ValueError('Review packet hash does not match its basis revision')
        known = {f['fact_id'] for f in packet['facts'] + packet['excluded_facts']}
        known.update(f['context_fact_id'] for c in packet.get('clinical_context', []) for f in c['facts'])
        if not set(review.fact_ids) <= known:
            raise ValueError('Review cites facts absent from the reviewed revision')
        return packet

    def review(self, case_id, review):
        with self.store.transaction() as conn:
            self.validate_review(conn, case_id, review)
            return self.store.append_event(conn, case_id, 'REVIEW_RECORDED', review.model_dump(mode='json'))

    def add_evidence(self, case_id, update):
        with self.store.transaction() as conn:
            return self._add_evidence(conn, case_id, update)

    def add_material_sources(self, case_id, update):
        """Map new original materials and persist their audit in one transaction."""
        from .requirement_support import prepare_material_update
        with self.store.transaction() as conn:
            current, previous = self.store.load(conn, case_id)
            if update.expected_revision != previous['revision']:
                raise RevisionConflict('Stale expected_revision; reload the current packet')
            prepared, receipt = prepare_material_update(
                current, previous, update.sources, review=update.review, intake=update.intake)
            packet = self._add_evidence(conn, case_id, prepared)
            self.store.append_event(conn, case_id, 'MATERIAL_INTAKE_RECORDED', {
                **receipt, 'result_revision': packet['revision'],
                'result_packet_sha256': packet['packet_sha256'],
            })
            return packet

    def _add_evidence(self, conn, case_id, update):
        current, previous = self.store.load(conn, case_id)
        if update.expected_revision != previous['revision']:
            raise RevisionConflict('Stale expected_revision; reload the current packet')
        if update.review is not None:
            self.validate_review(conn, case_id, update.review)
            if update.review.basis_revision != previous['revision']:
                raise RevisionConflict('Evidence updates require a review of the current revision')
        else:
            if update.intake.basis_revision != previous['revision']:
                raise RevisionConflict('Intake basis revision is stale')
            if update.intake.basis_packet_sha256 != previous['packet_sha256']:
                raise ValueError('Intake basis packet hash does not match current revision')
        known_sources = {s['source_id'] for s in current['sources']}
        known_facts = {f['fact_id'] for f in current['facts']}
        known_facts.update(f['context_fact_id'] for c in previous.get('clinical_context', []) for f in c['facts'])
        known_facts.update(f['fact_id'] for f in previous['facts'] + previous['excluded_facts'])
        new_sources = {s.source_id for s in update.sources}
        seen_content = {digest({'patient_id': s['patient_id'], 'content': s['content']}) for s in current['sources']}
        content_by_id = {s.source_id: digest({'patient_id': s.patient_id, 'content': s.content}) for s in update.sources}
        if known_sources & new_sources or known_facts & {f.fact_id for f in update.facts}:
            raise ValueError('Existing source/fact identities cannot be overwritten')
        for fact in update.facts:
            if any(ref.source_id not in new_sources for ref in fact.evidence):
                raise ValueError('New assertions require new source evidence')
            if all(content_by_id[ref.source_id] in seen_content for ref in fact.evidence):
                raise ValueError('Previously received content is not new supporting evidence')
            if fact.authority_ref and fact.authority_ref.source_id not in new_sources:
                raise ValueError('Correction authority must come from a new source')
            if fact.amends_fact_id:
                if fact.amends_fact_id not in update.review.fact_ids:
                    raise ValueError('Correction review must cite the original fact ID')
                if update.review.judgment != 'PROPOSE_CORRECTION':
                    raise ValueError('An amendment requires a reasoned correction review')
        if update.clinical_bindings:
            known_bindings = {b['binding_id'] for b in current.get('clinical_bindings', [])}
            if known_bindings & {b.binding_id for b in update.clinical_bindings}:
                raise ValueError('Existing clinical binding cannot be overwritten')
            for binding in update.clinical_bindings:
                if binding.binding_source_id not in new_sources or content_by_id[binding.binding_source_id] in seen_content:
                    raise ValueError('Clinical associations need genuinely new scope evidence')
        revised = Case.model_validate_json(json.dumps({
            **current, 'sources': current['sources'] + [s.model_dump(mode='json') for s in update.sources],
            'source_support_policy': PRODUCT_SUPPORT_POLICY,
            'facts': current['facts'] + [f.model_dump(mode='json') for f in update.facts],
            **({'clinical_context': current.get('clinical_context', []) +
                                   [c.model_dump(mode='json') for c in update.clinical_context]}
               if current.get('clinical_context') or update.clinical_context else {}),
            **({'clinical_bindings': current.get('clinical_bindings', []) +
                [b.model_dump(mode='json') for b in update.clinical_bindings]}
               if current.get('clinical_bindings') or update.clinical_bindings else {}),
        }))
        packet = evaluate(revised, revision=previous['revision'] + 1)
        # Invalid new evidence is retained, with explicit exclusions and gaps.
        self.store.append_revision(conn, revised, packet)
        if update.review is not None:
            self.store.append_event(conn, case_id, 'REVIEW_RECORDED', update.review.model_dump(mode='json'))
        self.store.append_event(conn, case_id, 'FACT_CORRECTED' if any(f.amends_fact_id for f in update.facts)
                                else 'EVIDENCE_ADDED', {
            'revision': packet['revision'], 'input_sha256': packet['input_sha256'],
            'packet_sha256': packet['packet_sha256'], 'ruleset_sha256': packet['ruleset']['sha256'],
            'added_fact_ids': [f.fact_id for f in update.facts], 'added_source_ids': sorted(new_sources),
            **({'added_binding_ids': [b.binding_id for b in update.clinical_bindings]}
               if update.clinical_bindings else {}),
            **({'reviewer': update.review.model_dump(mode='json')} if update.review is not None else
               {'intake': update.intake.model_dump(mode='json')}),
            'reevaluated_rule_ids': [c['rule_id'] for c in packet['checks']],
        })
        return packet

    def reviews(self, case_id):
        return [e for e in self.audit(case_id)['events'] if e['event_type'] == 'REVIEW_RECORDED']

    def audit(self, case_id):
        return self.store.audit(case_id)

    def risk_review(self, case_id, adapter, *, reviewer_id, model, model_version):
        """Opt-in Luna callback; external evaluators stay in offline tools.

        adapter(packet) returns Review or its JSON object. A risk-free case makes
        zero calls. Exceptions remain visible as PRODUCT_REVIEW_FAILED events.
        No model integration or research request is implicitly constructed.
        """
        if model != 'gpt-6-luna':
            raise ValueError('Product model review accepts gpt-6-luna only; Sol reviews belong to offline evaluation')
        packet = self.packet(case_id)
        if not packet['review_route']['recommended']:
            return {'status': 'SKIPPED_LOW_RISK', 'product_model_calls': 0}
        with self.store.transaction() as conn:
            reservation = self.store.append_event(conn, case_id, 'PRODUCT_REVIEW_RESERVED', {
                'basis_revision': packet['revision'], 'basis_packet_sha256': packet['packet_sha256'],
                'reviewer_id': reviewer_id, 'model': model, 'model_version': model_version,
                'product_model_calls': 1, 'research_model_calls': 0,
            })
        try:
            proposed = adapter(packet)
            review = proposed if isinstance(proposed, Review) else Review.model_validate_json(json.dumps(proposed))
            if (review.reviewer_type != 'advanced_ai' or review.reviewer_id != reviewer_id
                    or review.model != model or review.model_version != model_version
                    or review.basis_revision != packet['revision']
                    or review.basis_packet_sha256 != packet['packet_sha256']):
                raise ValueError('AI review identity/basis differs from reserved request')
            event = self.review(case_id, review)
            with self.store.transaction() as conn:
                self.store.append_event(conn, case_id, 'PRODUCT_REVIEW_COMPLETED', {
                    'reservation_sha256': reservation['event_sha256'], 'review_sha256': event['event_sha256'],
                })
            return {'status': 'REVIEW_RECORDED', 'product_model_calls': 1, 'review': event}
        except Exception as exc:
            with self.store.transaction() as conn:
                self.store.append_event(conn, case_id, 'PRODUCT_REVIEW_FAILED', {
                    'reservation_sha256': reservation['event_sha256'], 'error_type': type(exc).__name__,
                    'usage': 'unknown',
                })
            raise

    def model_calls(self, case_id):
        events = self.audit(case_id)['events']
        return {'research_model_calls': 0,
                'product_model_calls': sum(e['event_type'] == 'PRODUCT_REVIEW_RESERVED' for e in events),
                'failed_product_reviews': sum(e['event_type'] == 'PRODUCT_REVIEW_FAILED' for e in events),
                'incomplete_product_reviews': sum(e['event_type'] == 'PRODUCT_REVIEW_RESERVED' for e in events)
                    - sum(e['event_type'] in {'PRODUCT_REVIEW_COMPLETED', 'PRODUCT_REVIEW_FAILED'} for e in events)}
