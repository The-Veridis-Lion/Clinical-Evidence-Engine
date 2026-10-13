"""Versioned project documentation checklists; never a payer policy crosswalk."""
from dataclasses import asdict, dataclass

from ..claims_review.prepare import digest


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
