"""Frozen five-state acceptance with source/rule checks and one-use holdout."""
from datetime import datetime, timezone
import json
from pathlib import Path

from ...claims_review.facts import source_key
from ...claims_review.prepare import digest
from ..contracts import Case
from ..engine import evaluate
from ..rules import manifests
from .corpus import canonical, sha, write_once

STATES = ('SUPPORTED', 'NOT_SUPPORTED', 'INSUFFICIENT_EVIDENCE', 'CONFLICTED', 'NOT_APPLICABLE')
TARGETS = {'criteria_macro_f1': 0.98, 'serious_false_ready': 0,
           'source_reference_validation_rate': 1.0, 'rule_reference_validation_rate': 1.0}


def freeze_materials(scenarios, root):
    if not scenarios or len({r['scenario_id'] for r in scenarios}) != len(scenarios):
        raise ValueError('Nonempty unique frozen scenarios required')
    patient_partitions, source_partitions = {}, {}
    for row in scenarios:
        case = Case.model_validate_json(json.dumps(row['case']))
        if row['partition'] not in {'development', 'holdout'}:
            raise ValueError('Unknown material partition')
        previous = patient_partitions.setdefault(case.request.patient_id, row['partition'])
        if previous != row['partition']:
            raise ValueError('Patient group leakage across material partitions')
        for source in case.sources:
            fingerprint = digest(source.content)
            previous = source_partitions.setdefault(fingerprint, row['partition'])
            if previous != row['partition']:
                raise ValueError('Duplicate document leakage across material partitions')
        if not row['expected_checks'] or any(v not in STATES for v in row['expected_checks'].values()):
            raise ValueError('Frozen reference checks must use the five documentation states')
    raw = ('\n'.join(canonical(row) for row in sorted(scenarios, key=lambda r: r['scenario_id'])) + '\n').encode('utf-8')
    manifest = {'schema_version': 'careflow-material-acceptance/2', 'scenarios_sha256': sha(raw),
                'case_count': len(scenarios), 'criterion_denominator': sum(len(r['expected_checks']) for r in scenarios),
                'partitions': {p: [r['scenario_id'] for r in scenarios if r['partition'] == p] for p in ('development', 'holdout')},
                'patient_partitions': patient_partitions, 'targets': TARGETS, 'rulesets': manifests(),
                'reference_origin': 'explicit versioned documentation requirements; synthetic mechanical oracles, no insurance approval labels'}
    manifest['manifest_sha256'] = digest(manifest)
    root = Path(root)
    write_once(root / 'scenarios.jsonl', raw)
    write_once(root / 'manifest.json', (canonical(manifest) + '\n').encode('utf-8'))
    return manifest


def implementation_hashes():
    package = Path(__file__).resolve().parents[2]
    return {path.relative_to(package).as_posix(): sha(path.read_bytes().replace(b'\r\n', b'\n'))
            for path in sorted(package.rglob('*.py'))}


def seal_candidate(root):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    seal = {'manifest_sha256': manifest['manifest_sha256'], 'implementation': implementation_hashes(),
            'model_dispatch': 'none; deterministic readiness candidate'}
    seal['candidate_sha256'] = digest(seal)
    write_once(root / 'candidate-seal.json', (canonical(seal) + '\n').encode('utf-8'))
    return seal


def resolve_pointer(packet, pointer):
    current = packet
    for part in pointer.strip('/').split('/'):
        token = part.replace('~1', '/').replace('~0', '~')
        current = current[int(token)] if isinstance(current, list) else current[token]
    return current


def verify_packet(packet):
    from ..clinical_context import verify_packet_context
    sources = {s['source_id']: s for s in packet['sources']}
    source_checks, seen = [], set()
    for entry in packet['facts'] + packet['checks']:
        for citation in entry.get('citations', entry.get('clinical_refs', [])):
            key = digest(citation)
            if key in seen:
                continue
            seen.add(key)
            source = sources.get(citation['source_id'])
            valid = bool(source and citation['patient_id'] == source['patient_id']
                         and citation['source_sha256'] == source_key(source))
            if valid:
                if citation['method'] == 'unicode_line_anchor':
                    start, end, text = citation['start'], citation['end'], source['content']
                    valid = (isinstance(text, str) and type(start) is int and type(end) is int
                             and 0 <= start < end <= len(text) and text[start:end] == citation['quote'])
                else:
                    try:
                        valid = resolve_pointer(packet, citation['locator']) == citation['raw_value']
                        tokens = citation['locator'].split('/')
                        valid = valid and packet['sources'][int(tokens[2])]['source_id'] == citation['source_id']
                    except (KeyError, ValueError, IndexError, TypeError):
                        valid = False
            source_checks.append(bool(valid))
    for check in packet['checks']:
        if check['status'] in {'SUPPORTED', 'NOT_APPLICABLE'} and not check['clinical_refs']:
            source_checks.append(False)
    source_checks += verify_packet_context(packet)
    registry = next((r for r in manifests() if r['ruleset_id'] == packet['ruleset']['ruleset_id']
                     and r['version'] == packet['ruleset']['version']), None)
    known = {r['rule_id']: r for r in registry['rules']} if registry else {}
    rule_checks = [bool(registry and packet['ruleset']['sha256'] == registry['sha256']
                        and {c['rule_id'] for c in packet['checks']} == set(known)
                        and len(packet['checks']) == len(known))]
    rule_checks += [bool(c['rule_id'] in known and c['rule_version'] == known[c['rule_id']]['version']
                         and c['criterion_id'] == c['rule_id']) for c in packet['checks']]
    if packet.get('clinical_mapping'):
        from ..mapping import mapping_manifest
        try:
            expected_mapping = mapping_manifest(packet['clinical_mapping'].get('version'))
        except ValueError:
            expected_mapping = None
        rule_checks.append(expected_mapping is not None and packet['clinical_mapping'].get('manifest') == expected_mapping)
    return {'source_checks': source_checks, 'rule_checks': rule_checks}


def evaluate_materials(root, output, *, partition, evaluator=evaluate):
    root, output = Path(root), Path(output)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if digest({k: v for k, v in manifest.items() if k != 'manifest_sha256'}) != manifest['manifest_sha256']:
        raise ValueError('Frozen manifest hash mismatch')
    raw = (root / 'scenarios.jsonl').read_bytes()
    if sha(raw) != manifest['scenarios_sha256']:
        raise ValueError('Frozen scenario hash mismatch')
    if partition not in manifest['partitions']:
        raise ValueError('Unknown material partition')
    candidate = None
    if partition == 'holdout':
        seal_path = root / 'candidate-seal.json'
        if not seal_path.exists():
            raise ValueError('Holdout requires a frozen candidate seal')
        candidate = json.loads(seal_path.read_text(encoding='utf-8'))
        if (candidate['manifest_sha256'] != manifest['manifest_sha256']
                or candidate['implementation'] != implementation_hashes()
                or digest({k: v for k, v in candidate.items() if k != 'candidate_sha256'}) != candidate['candidate_sha256']):
            raise ValueError('Frozen candidate changed')
        receipt = root / 'holdout-reservation.json'
        if receipt.exists():
            raise ValueError('Holdout already reserved; never resample the final set')
        write_once(receipt, (canonical({'candidate_sha256': candidate['candidate_sha256'],
                                       'reserved_at': datetime.now(timezone.utc).isoformat()}) + '\n').encode('utf-8'))
    scenarios = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    selected = [r for r in scenarios if r['partition'] == partition]
    if not selected:
        raise ValueError('Empty material partition')
    output.mkdir(parents=True, exist_ok=False)
    pairs, source_checks, rule_checks, rows = [], [], [], []
    failed, serious, overall_errors = 0, 0, 0
    for row in selected:
        prediction = {}
        try:
            packet = evaluator(Case.model_validate_json(json.dumps(row['case'])))
            packet_file = 'packet-' + digest(row['scenario_id']) + '.json'
            write_once(output / packet_file, (canonical(packet) + '\n').encode('utf-8'))
            prediction = {c['rule_id']: c['status'] for c in packet['checks']}
            mechanical = verify_packet(packet)
            source_checks += mechanical['source_checks']
            rule_checks += mechanical['rule_checks']
            severe = (packet['readiness'] == 'DOCUMENTATION_READY'
                      and (row['expected_readiness'] in {'NEEDS_EVIDENCE', 'CONFLICTED'}
                           or any(s in {'INSUFFICIENT_EVIDENCE', 'CONFLICTED'} for s in row['expected_checks'].values())))
            serious += severe
            overall_errors += packet['readiness'] != row['expected_readiness']
            receipt = {'scenario_id': row['scenario_id'], 'expected_checks': row['expected_checks'],
                       'predicted_checks': prediction, 'expected_readiness': row['expected_readiness'],
                       'readiness': packet['readiness'], 'serious_false_ready': severe,
                       'packet_sha256': packet['packet_sha256'], 'packet_file': packet_file, 'status': 'SUCCESS'}
        except Exception as exc:
            prediction = {}
            failed += 1
            overall_errors += 1
            source_checks.append(False)
            rule_checks.append(False)
            receipt = {'scenario_id': row['scenario_id'], 'status': 'FAILED', 'error_type': type(exc).__name__,
                       'expected_checks': row['expected_checks'], 'predicted_checks': {}}
        pairs += [(expected, prediction.get(rule, '__EXECUTION_FAILED__')) for rule, expected in row['expected_checks'].items()]
        pairs += [('__UNEXPECTED_RULE__', status) for rule, status in prediction.items() if rule not in row['expected_checks']]
        rows.append(receipt)
    scores = {}
    for status in STATES:
        tp = sum(a == b == status for a, b in pairs)
        fp = sum(b == status and a != status for a, b in pairs)
        fn = sum(a == status and b != status for a, b in pairs)
        scores[status] = {'tp': tp, 'fp': fp, 'fn': fn, 'support': tp + fn,
                          'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}
    macro = sum(s['f1'] for s in scores.values()) / len(STATES)
    source_rate = sum(source_checks) / len(source_checks) if source_checks else 0.0
    rule_rate = sum(rule_checks) / len(rule_checks) if rule_checks else 0.0
    result = {
        'schema_version': 'careflow-acceptance-result/2', 'partition': partition,
        'manifest_sha256': manifest['manifest_sha256'], 'candidate_sha256': candidate['candidate_sha256'] if candidate else None,
        'case_count': len(selected), 'criterion_denominator': sum(len(r['expected_checks']) for r in selected),
        'failed_cases': failed, 'overall_readiness_errors': overall_errors, 'per_state': scores,
        'criteria_macro_f1': macro, 'serious_false_ready': serious,
        'source_reference_denominator': len(source_checks), 'source_reference_validation_rate': source_rate,
        'rule_reference_denominator': len(rule_checks), 'rule_reference_validation_rate': rule_rate,
        'meets_deterministic_targets': macro >= TARGETS['criteria_macro_f1'] and serious == 0
            and source_rate == rule_rate == 1.0 and failed == overall_errors == 0,
        'public_text_extraction_targets': 'NOT_MEASURED_BY_THIS_DETERMINISTIC_EVALUATION',
        'boundary': 'Synthetic documentation rules; no clinical accuracy or insurance approval score.',
    }
    write_once(output / 'case-results.jsonl', ('\n'.join(canonical(r) for r in rows) + '\n').encode('utf-8'))
    write_once(output / 'metrics.json', (canonical(result) + '\n').encode('utf-8'))
    return result
