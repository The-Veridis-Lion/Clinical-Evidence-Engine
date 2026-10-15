"""Versioned project documentation checklists; never a payer policy crosswalk."""
from dataclasses import asdict, dataclass

from ..claims_review.prepare import digest


def documentation_decision(support_state, *, trigger_state=None):
    """Pure checklist logic over states, never a source-verification shortcut.

    Production supplies states obtained from independently checked materials.
    Offline historical rule fixtures may supply their predeclared truth states;
    that result has no document/source certificate and must not be persisted as a
    clinical review packet. Neither this function nor the HTTP schema accepts an
    assertion boolean as verified documentary evidence.
    """
    states = {'SUPPORTED', 'NOT_SUPPORTED', 'INSUFFICIENT_EVIDENCE', 'CONFLICTED'}
    if support_state not in states or trigger_state is not None and trigger_state not in states:
        raise ValueError('A verified truth state is required for deterministic rule evaluation')
    reason = {
        'SUPPORTED': 'Traceable assertions support the required document or fact.',
        'NOT_SUPPORTED': 'Explicit contrary evidence is documented; this is not an absence inference.',
        'INSUFFICIENT_EVIDENCE': 'Required material is missing, unknown, unavailable, or not grounded.',
        'CONFLICTED': 'Relevant assertions or amendment authority remain unresolved.',
    }[support_state]
    trigger_value = True if trigger_state is None or trigger_state == 'SUPPORTED' else (
        False if trigger_state == 'NOT_SUPPORTED' else None)
    if trigger_state == 'CONFLICTED':
        return 'CONFLICTED', 'The requirement trigger has unresolved contradictory evidence.', trigger_value
    if trigger_value is False:
        return 'NOT_APPLICABLE', 'Source-linked explicit false trigger establishes inapplicability.', trigger_value
    if trigger_value is None:
        return 'INSUFFICIENT_EVIDENCE', 'Applicability is unknown; missing triggers cannot waive a requirement.', trigger_value
    return support_state, reason, trigger_value


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: str
    requirement: str
    description: str
    trigger_requirement: str | None = None


COMMON = (
    Rule('CF-DOC-001', '1.0.0', 'request_intent', 'Request-specific provider intent is documented.'),
    Rule('CF-DOC-002', '1.0.0', 'referral_reason', 'The requested service has a documented clinical reason.'),
    Rule('CF-DOC-003', '1.0.0', 'clinical_summary', 'A request-specific clinical summary is available.'),
    Rule('CF-DOC-004', '1.0.0', 'investigation_result',
         'Attach results when the documented request requires an investigation.', 'investigation_required'),
    Rule('CF-DOC-005', '1.0.0', 'therapy_completed',
         'Attach documented prior therapy when the request explicitly requires it.', 'therapy_required'),
)
REGISTRY = {
    ('careflow-referral', '1.0.0'): ('referral', COMMON + (
        Rule('CF-REF-001', '1.0.0', 'destination', 'Referral destination is documented.'),
    )),
    ('careflow-pa', '1.0.0'): ('prior_authorization', COMMON + (
        Rule('CF-PA-001', '1.0.0', 'pa_form', 'A request-specific PA form is available.'),
        Rule('CF-PA-002', '1.0.0', 'payer_context', 'The supplied payer/request identifiers are documented.'),
    )),
}


def ruleset(identifier, version, request_type):
    entry = REGISTRY.get((identifier, version))
    if entry is None or entry[0] != request_type:
        raise ValueError('Unsupported ruleset/version/request-type combination')
    rules = entry[1]
    manifest = {
        'ruleset_id': identifier, 'version': version, 'request_type': request_type,
        'status': 'synthetic_project_checklist',
        'requirements_authority': 'CareFlow demo documentation specification; no insurer policy authority.',
        'rules': [asdict(rule) for rule in rules],
        'boundary': 'Documentation readiness only; no medical approval, payment eligibility or compliance certification.',
    }
    return rules, {**manifest, 'sha256': digest(manifest)}


def manifests():
    return [ruleset(key[0], key[1], entry[0])[1] for key, entry in REGISTRY.items()]
