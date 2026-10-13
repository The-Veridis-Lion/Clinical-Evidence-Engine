"""Declared policy prerequisites, separate from evidence conclusions."""

VERSION = 'claims-review-applicability/1'


def check(case, policy, criterion, requested_policy=None):
    reasons = []
    for prerequisite in criterion['prerequisites']:
        if prerequisite == 'service_date':
            if case.claim.service_date is None:
                reasons.append('Service date unknown: policy/date selection unresolved.')
            elif case.claim.service_date > case.review_context.as_of:
                reasons.append('Future service date: retrospective review not evaluable.')
        elif prerequisite == 'monitoring_concept':
            if case.claim.service_concept != policy['supported_service_concept']:
                reasons.append('Requested service concept outside/unresolved for this policy.')
        elif prerequisite == 'policy_version':
            if requested_policy is not None and requested_policy != policy['registry_version']:
                reasons.append('Requested registry version is not mapped.')
            # This only validates the NCD narrative boundary, not billing files
            # or historical applicability of educational MLN publications.
            ncd = next(s for s in policy['sources'] if s['source_id'] == 'CMS_NCD_190_21_V1')
            if case.claim.service_date and case.claim.service_date.isoformat() < ncd['effective_from']:
                reasons.append('Service predates the inspected NCD narrative version.')
        elif prerequisite == 'patient_identity':
            if not case.claim.patient_id.strip():
                reasons.append('Patient identity unresolved.')
        else:
            raise ValueError(f'Undeclared prerequisite implementation: {prerequisite}')
    return {'version': VERSION, 'status': 'UNRESOLVED' if reasons else 'EVALUABLE',
            'required': criterion['prerequisites'], 'reasons': reasons,
            'limit': 'Draft scope/version selection only; not full legal or billing applicability.'}
