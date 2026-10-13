"""Original source intake without inventing paperwork from clinical concepts."""
import json

from ..claims_review.facts import source_key
from ..claims_review.prepare import digest
from .contracts import Case
from .requirement_support import VERSION as SUPPORT_VERSION, documentary_facts

VERSION = 'careflow-raw-intake/1'


def json_value(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else value


def build_case(case_id, request, review_as_of, sources, *, extractions=(), clinical_bindings=()):
    """Validate original text/extraction pairs and retain all material candidates.

    ``extractions`` contains the existing ClinicalContext shape:
    ``{'source_id': original_source_id, 'extraction': Extraction JSON}``.
    It can contain retained Luna outputs or explicitly labelled, source-checked
    synthetic structures. This adapter neither invokes a model nor assigns
    documentation semantics to symptoms. Canonical original material envelopes
    are proposed as Facts; the source-semantic gate is authoritative at evaluation.
    Unconfirmed, disputed and rejected candidates stay in the intake receipt.
    """
    if hasattr(review_as_of, 'isoformat'):
        review_as_of = review_as_of.isoformat()
    raw = {'case_id': case_id, 'request': json_value(request), 'review_as_of': review_as_of,
        'sources': [json_value(s) for s in sources], 'facts': [],
        'clinical_context': [json_value(c) for c in extractions],
        'clinical_bindings': [json_value(b) for b in clinical_bindings]}
    # Construct through JSON so strict ISO dates obey the existing public API.
    # No intermediate case is persisted before every source/extraction validates.
    base = Case.model_validate_json(json.dumps(raw))
    facts, decisions = documentary_facts(base)
    raw['facts'] = [f.model_dump(mode='json') for f in facts]
    case = Case.model_validate_json(json.dumps(raw))
    receipt = {'schema_version': VERSION, 'case_id': case_id, 'support_version': SUPPORT_VERSION,
        'input_sha256': digest(case.model_dump(mode='json')),
        'source_identities': [{'source_id': source.source_id,
            'source_sha256': source_key(source.model_dump(mode='json'))} for source in case.sources],
        'source_documents': len(case.sources),
        'clinical_assertions': sum(len(c.extraction.facts) for c in case.clinical_context),
        'clinical_binding_candidates': len(case.clinical_bindings),
        'material_candidates': len(facts), 'material_decisions': decisions,
        'new_model_calls': 0, 'upstream_model_calls': None,
        'source_checked_precision': None, 'source_checked_recall': None,
        'boundary': 'Original structured material or retained clinical extraction; no payer approval or independent medical accuracy claim.'}
    return case, receipt
