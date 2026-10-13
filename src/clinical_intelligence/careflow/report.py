"""Human-readable rendering of the same immutable machine review packet."""
import json
import re


def cell(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', ' ')


def literal(value, language=''):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    longest = max((len(m.group()) for m in re.finditer(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}{language}\n{text}\n{fence}\n'


def markdown(packet, reviews=()):
    r = packet['request']
    out = [f"# CareFlow Evidence Review Packet — {cell(packet['case_id'])}\n",
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
    if packet.get('clinical_mapping'):
        out += ['## Clinical evidence mapping\n', literal(packet['clinical_mapping'], 'json')]
    for fact in packet['facts'] + packet['excluded_facts']:
        label = 'EXCLUDED: ' + fact['reason'] if 'reason' in fact else fact['reconciliation_status']
        out += [f"### {cell(fact['fact_id'])} — {fact['requirement']} — {label}\n",
                f"Assertion: {fact['assertion_status']} · effective: {fact.get('effective_assertions', 'excluded')} · origin: {fact['interpretation_origin']}\n",
                literal(fact['statement']),
                f"Request/patient/service: {cell(fact['request_id'])} / {cell(fact['patient_id'])} / {cell(fact['code_system'])}:{cell(fact['service_code'])}\n",
                f"Amends: {cell(fact['amends_fact_id'])}\n"]
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
