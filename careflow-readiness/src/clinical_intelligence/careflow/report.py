"""Human-readable rendering of the same immutable machine review packet."""
from copy import deepcopy
import json
import re

from ..claims_review.prepare import digest
from .requirement_support import support_manifest

SUPPORT_VIEW_VERSION = 'careflow-packet-support-view/1'


def packet_support_view(packet):
    """Describe saved semantic-contract identity without reevaluating decisions.

    Historical readiness, original manifests, packet hashes and audit entries
    remain immutable. A matching manifest indicates only the saved software
    contract, at the saved review date; it is not independent clinical gold.
    """
    current = support_manifest()
    saved = packet.get('requirement_support_manifest')
    manifest_valid = (isinstance(saved, dict) and isinstance(saved.get('version'), str)
        and saved['version'].startswith('careflow-requirement-support/')
        and isinstance(saved.get('code_sha256'), str)
        and re.fullmatch(r'[0-9a-f]{64}', saved['code_sha256']) is not None
        and saved.get('sha256') == digest({k: v for k, v in saved.items() if k != 'sha256'}))
    packet_valid = (isinstance(packet.get('packet_sha256'), str)
        and packet['packet_sha256'] == digest({k: v for k, v in packet.items() if k != 'packet_sha256'}))
    if not manifest_valid or not packet_valid:
        status = 'HISTORICAL_UNVERIFIED'
    elif saved == current:
        status = 'CURRENT_SOURCE_SUPPORT_CONTRACT'
    else:
        status = 'HISTORICAL_SUPPORT_CONTRACT'
    return {
        'schema_version': SUPPORT_VIEW_VERSION,
        'case_id': packet['case_id'], 'revision': packet['revision'],
        'review_as_of': packet['review_as_of'], 'status': status,
        'saved_packet_sha256': packet.get('packet_sha256'),
        'saved_readiness': packet['readiness'],
        'saved_requirement_support_manifest': deepcopy(saved),
        'current_requirement_support_manifest': current,
        'saved_packet_integrity_valid': packet_valid,
        'saved_manifest_integrity_valid': manifest_valid,
        # A support-manifest identity check cannot certify the entire current
        # engine/rules/mapping or provide external clinical certification.
        'current_ready_certification': False,
        'documentation_ready_under_saved_as_of': packet['readiness'] == 'DOCUMENTATION_READY',
        'support_contract_matches_current': status == 'CURRENT_SOURCE_SUPPORT_CONTRACT',
        'decision_recomputed': False,
        'boundary': 'Saved source-support-contract identity and readiness at the recorded review date only. '
                    'Historical decisions do not establish current-contract readiness. '
                    'The project contract is not independent clinical gold or medical-accuracy certification; '
                    'this view does not recompute evidence, certify the entire current engine/rules/mapping, '
                    'authenticate signatures or predict insurer approval.',
    }


def cell(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', ' ')


def literal(value, language=''):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    longest = max((len(m.group()) for m in re.finditer(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}{language}\n{text}\n{fence}\n'


def markdown(packet, reviews=()):
    r = packet['request']
    view = packet_support_view(packet)
    support_notice = (f"**Semantic contract: {view['status']}**. "
        'The project contract is not independent clinical gold. ')
    if view['status'] != 'CURRENT_SOURCE_SUPPORT_CONTRACT':
        support_notice += ('**Historical decision: saved readiness below is preserved and does not certify '
                           'readiness under the current source-support contract.** ')
    else:
        support_notice += 'Readiness below is the saved decision at its recorded review date. '
    support_notice += 'No evidence recomputation or signature authentication occurs in this report.\n'
    out = [f"# CareFlow Evidence Review Packet — {cell(packet['case_id'])}\n",
           support_notice,
           f"**{packet['readiness']}** · revision {packet['revision']} · as of {packet['review_as_of']}\n",
           f"Request: {cell(r['request_id'])} · type: {r['request_type']} · patient: {cell(r['patient_id'])} · encounter: {cell(r['encounter_id'])}\n",
           f"Service: {cell(r['code_system'])} / {cell(r['service_code'])} · requested date: {r['requested_service_date']}\n",
           f"Rules: {cell(packet['ruleset']['ruleset_id'])} / {packet['ruleset']['version']} · {packet['ruleset']['status']}\n",
           f"Packet SHA-256: {packet['packet_sha256']}\nRules SHA-256: {packet['ruleset']['sha256']}\n",
           packet['decision_boundary'] + '\n', packet['interpretation_limit'] + '\n',
           '## Documentation checks\n', '| Rule / version | Requirement | Trigger | Result | Fact IDs |',
           '| --- | --- | --- | --- | --- |']
    for check in packet['checks']:
        out.append(f"| {check['rule_id']} / {check['rule_version']} | {check['requirement']} | {cell(check['trigger_condition'])}; value={check['derivation']['trigger']} | {check['status']} | {cell(', '.join(check['fact_ids']) or 'none')} |")
    out.append('\n## Check details and actionable review questions\n')
    for check in packet['checks']:
        out += [f"### {check['rule_id']} — {check['status']}\n", check['description'] + '\n', check['reason'] + '\n']
        for question in check['review_questions']:
            out.append('- ' + cell(question))
        if check['conflicts']:
            out.append(literal(check['conflicts'], 'json'))
    out.append('\n## Evidence gaps\n')
    out.append(literal(packet['gaps'], 'json') if packet['gaps'] else 'No missing requirements under this exact checklist.\n')
    out.append('## Assertions and exact evidence\n')
    if packet.get('requirement_support_manifest'):
        out += ['## Requirement support verification\n', literal(packet['requirement_support_manifest'], 'json')]
    if packet.get('clinical_mapping'):
        out += ['## Clinical evidence mapping\n', literal(packet['clinical_mapping'], 'json')]
    for fact in packet['facts'] + packet['excluded_facts']:
        label = 'EXCLUDED: ' + fact['reason'] if 'reason' in fact else fact['reconciliation_status']
        out += [f"### {cell(fact['fact_id'])} — {fact['requirement']} — {label}\n",
                f"Assertion: {fact['assertion_status']} · effective: {fact.get('effective_assertions', 'excluded')} · origin: {fact['interpretation_origin']}\n",
                literal(fact['statement']),
                f"Request/patient/service: {cell(fact['request_id'])} / {cell(fact['patient_id'])} / {cell(fact['code_system'])}:{cell(fact['service_code'])}\n",
                f"Amends: {cell(fact['amends_fact_id'])}\n"]
        if fact.get('requirement_support'):
            out.append(literal(fact['requirement_support'], 'json'))
            support = fact['requirement_support']
            if 'primary_evidence_semantic_status' in support:
                out.append('Original primary-reference support: ' + support['primary_evidence_semantic_status'] +
                    '. Exact offsets validate location; they do not certify every selected quote.\n')
            for span in support.get('preferred_source_evidence', []):
                out += [f"Source-supported passage: {cell(span['source_id'])} · Unicode offsets: [{span['start']}, {span['end']})\n",
                        literal(span['quote'])]
        for citation in fact['citations']:
            out += [f"Source: {cell(citation['source_id'])} · locator: {cell(citation['locator'])} · hash: {citation['source_sha256']}\n",
                    f"Unicode offsets: [{citation['start']}, {citation['end']}) · method: {citation['method']}\n",
                    literal(citation['quote'] if citation['quote'] is not None else citation['raw_value']),
                    literal(citation['original_locator'], 'json') if citation['original_locator'] else '']
        if fact['grounding_errors']:
            out.append(literal(fact['grounding_errors'], 'json'))
    out += ['## Unresolved conflicts and source relationships\n',
            literal(packet['unresolved_conflicts'], 'json'), literal(packet['source_relationships'], 'json'),
            '## Optional risk review\n', literal(packet['review_route'], 'json'),
            '## Reviewer opinions (separate from rule results)\n']
    if reviews:
        for review in reviews:
            out.append(literal(review, 'json'))
    else:
        out.append('No reviewer opinions recorded. Reviewer sign-off is not a prerequisite for deterministic documentation readiness.\n')
    out.append('## Preserved original documents\n')
    if packet.get('clinical_context'):
        out += ['## Clinical context (source validated; separate from documentation checks)\n',
                literal(packet['clinical_context'], 'json')]
    out.append(literal(packet.get('source_screening', []), 'json'))
    for source in packet['sources']:
        out += [f"### {cell(source['source_id'])}\n", literal(source, 'json')]
    return '\n'.join(out) + '\n'
