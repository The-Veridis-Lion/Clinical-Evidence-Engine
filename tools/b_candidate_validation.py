import os
"""Fixed new-material validation using the existing bounded runner and original B.

Inference reads only input cases. Labels are opened only by preflight and scoring.
No prompt/schema/runtime tuning, transport retries, hidden sample selection or
historical ledger consumption. The candidate entry explicitly defaults to B;
the product CLI and run_review continue to default to A.
"""
import argparse
import copy
import hashlib
import json
import random
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import luna_bounded_ab as bounded
from luna_ab_rescore import score_output, digest, read, save, sha
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.note_extractor import PROMPT, note_request
from clinical_intelligence.claims_review.note_prompt_b import PROMPT_B
from clinical_intelligence.claims_review.prepare import prepare_case
from clinical_intelligence.claims_review.review import run_review, load_policy

VERSION = 'b-candidate-new-validation/1'
ROOT = Path(__file__).resolve().parents[1]
STOP = {'B_READY_FOR_REVIEWED_MERGE', 'B_NOT_READY', 'INCONCLUSIVE_SCORER',
        'DATA_OR_SCORER_NOT_READY', 'TIME_LIMIT', 'BLOCKED'}


def guard(directory, *, data=False):
    state = read(directory / 'round_state.json')
    if state.get('terminal_status') in STOP:
        raise RuntimeError('Round is terminal; no further experiment is authorized')
    deadline = state['data_gate_deadline'] if data else state['work_deadline']
    if datetime.now(timezone.utc) >= datetime.fromisoformat(deadline):
        state['terminal_status'] = 'DATA_OR_SCORER_NOT_READY' if data else 'TIME_LIMIT'
        save(directory / 'round_state.json', state)
        raise RuntimeError('Persistent deadline reached')
    if state['attempts'] > 96:
        raise RuntimeError('Request ceiling violated')
    return state


def fixed_plan():
    plan = []
    for repeat in [1, 2]:
        cases = list(range(1, 13))
        random.Random(202610091 + repeat).shuffle(cases)
        for j, n in enumerate(cases):
            for candidate in (['A', 'B'] if (j + repeat) % 2 else ['B', 'A']):
                plan.append(dict(execution_id=f'n{n:02}-{candidate}-r{repeat}',
                    split='new', case_id=f'N{n:02}', candidate=candidate,
                    repeat=repeat, status='pending', calls=[]))
    return plan


def candidate_review(case, *, note_prompt='B', **kwargs):
    """Shared deployment path with explicit candidate provenance; no clinical edits."""
    packet = run_review(case, note_prompt=note_prompt, **kwargs)
    base = PROMPT if note_prompt == 'A' else PROMPT_B
    identity = {'note_prompt': note_prompt,
                'base_prompt_sha256': hashlib.sha256(base.encode()).hexdigest()}
    packet.execution['note_prompt_selection'] = identity
    packet.identity['candidate_request_sha256'] = digest({
        'review_input_sha256': packet.identity['review_input_sha256'], **identity})
    return packet


def prepared(path):
    case = CaseInput.model_validate_json(path.read_bytes())
    notes = [s for s in prepare_case(case, load_policy(), input_label=path.stem)
             ['source_candidates'] if s['source_kind'] == 'synthetic_note']
    if len(notes) != 1:
        raise ValueError('Each execution requires exactly one full eligible note')
    return case, notes[0]


def preflight(directory):
    guard(directory, data=True)
    expected = read(directory / 'expected.json')
    manifest = read(directory / 'dataset_manifest.json')
    if len(manifest['cases']) != 12 or len(expected['cases']) != 12:
        raise ValueError('Fixed twelve-material dataset required')
    checks = []
    for item in manifest['cases']:
        case, source = prepared(directory / 'inputs' / (item['case_id'] + '.json'))
        spec = expected['cases'][case.case_id]
        if digest(source) != spec['source_sha256']:
            raise ValueError('Source review hash differs')
        facts = spec['correct_fixture']
        good = score_output(facts, source, spec)
        if not good['complete_common_scored_constraints']:
            raise ValueError('Correct fixture rejected: ' + case.case_id)
        variant = copy.deepcopy(facts)
        variant.reverse()
        for fact in variant:
            fact['statement'] = 'Documented assertion: ' + fact['statement']
            # Add harmless title context, not a competing clinical event.
            fact['span_ids'].append(source['line_anchors'][0]['span_id'])
        same = score_output(variant, source, spec)
        if good['metrics'] != same['metrics']:
            raise ValueError('Order/paraphrase/context invariance failed: ' + case.case_id)
        negative_count = 0
        for j, fact in enumerate(facts):
            for field, allowed in spec['facts'][j]['fields'].items():
                if field in spec['facts'][j].get('unresolved_fields', {}):
                    continue
                bad = copy.deepcopy(facts)
                value = allowed[0]
                changed = None if value is not None else False
                if field == 'value' and spec['facts'][j].get('numeric_value'):
                    changed = '6.7 mg/dL'
                bad[j][field] = changed
                result = score_output(bad, source, spec)
                if result['complete_common_scored_constraints']:
                    raise ValueError(f'Wrong {field} accepted: {case.case_id}')
                negative_count += 1
            bad = copy.deepcopy(facts)
            bad[j]['span_ids'] = ['WRONG-SOURCE:L001']
            if score_output(bad, source, spec)['complete_common_scored_constraints']:
                raise ValueError('Wrong reference accepted')
            wrong_identity = {'patient_id': 'OTHER', 'source_id': source['source_id']}
            if score_output(facts, source, spec, proposal_identity=wrong_identity)['complete_common_scored_constraints']:
                raise ValueError('Wrong patient accepted')
            negative_count += 2
        if not facts:
            bad = [dict(kind='order_intent', statement='HbA1c ordered.', value=True,
                        span_ids=[source['line_anchors'][0]['span_id']])]
            if score_output(bad, source, spec)['extras'][0]['category'] != 'UNSUPPORTED':
                raise ValueError('Invented target accepted in control')
            negative_count += 1
        checks.append({'case_id': case.case_id, 'correct': True,
                       'paraphrase_context_order': True, 'negative_controls': negative_count,
                       'source_sha256': digest(source), 'predeclared_unresolved':
                       sum(len(s.get('unresolved_fields', {})) for s in spec['facts'])})
    save(directory / 'preflight.json', {'version': VERSION, 'passed': True,
         'checks': checks, 'provider_calls': 0, 'reviewer_type': 'AI_ASSISTED'})
    print('DATA PREFLIGHT PASSED: twelve notes, positive and negative controls; zero live calls')


def freeze(directory):
    state = guard(directory, data=True)
    if (directory / 'freeze.json').exists() or state['attempts']:
        raise ValueError('Never replace freeze or reset requests')
    if not read(directory / 'preflight.json')['passed']:
        raise ValueError('Data/scorer gate is not satisfied')
    if not read(directory / 'wiring-tests.json')['passed']:
        raise ValueError('Wiring/self-tests must pass before freeze')
    old = ROOT / 'artifacts/luna-bounded-ab-round-01'
    for candidate, text in [('A', PROMPT), ('B', PROMPT_B)]:
        if (old / f'prompt_{candidate}.txt').read_text(encoding='utf-8') != text:
            raise ValueError('Measured original base prompt changed')
    plan = fixed_plan()
    if [(p['execution_id'], p['candidate'], p['repeat']) for p in plan] != [
            (p['execution_id'], p['candidate'], p['repeat']) for p in state['schedule']]:
        raise ValueError('Original execution schedule changed')
    for path, value in state['historical_ledgers'].items():
        if sha(path) != value:
            raise ValueError('Historical ledger changed')
    state.update(plan=plan, phase='FROZEN', seed=202610091, calls=[],
        start_utc=state['started_at'], execution_deadline=state['work_deadline'],
        model='gpt-6-luna', reasoning='high', request_timeout_seconds=180)
    ledger = Path(os.environ['CLINICAL_HISTORICAL_LEDGER'])
    state['historical_ledger'] = {'path': str(ledger), 'sha256': sha(ledger),
                                'count': len(read(ledger)['calls']), 'limit': 20}
    requests = {}
    for path in sorted((directory / 'inputs').glob('*.json')):
        case, source = prepared(path)
        for candidate in ['A', 'B']:
            prompt, schema = note_request(source, case.claim.model_dump(mode='json'), prompt_variant=candidate)
            folder = directory / 'requests' / case.case_id / candidate
            folder.mkdir(parents=True)
            (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
            save(folder / 'schema.json', schema)
            requests[case.case_id + '-' + candidate] = {'prompt_sha256': sha(folder / 'prompt.txt'),
                'schema_sha256': sha(folder / 'schema.json')}
    files = [*sorted((ROOT / 'src').rglob('*.py')), *sorted((ROOT / 'src').rglob('*.json')),
             ROOT / 'tools/luna_bounded_ab.py', ROOT / 'tools/luna_ab_rescore.py', Path(__file__),
             ROOT / 'tests/test_b_candidate_validation.py', directory / 'expected.json',
             directory / 'scope.md', directory / 'dataset_manifest.json',
             *sorted((directory / 'inputs').glob('*.json'))]
    frozen = {'version': VERSION,
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'files': {str(p.resolve()): sha(p) for p in files}, 'requests': requests,
        'prompts': {c: hashlib.sha256(t.encode()).hexdigest() for c, t in [('A', PROMPT), ('B', PROMPT_B)]},
        'limits': {k: state[k] for k in ['start_utc', 'execution_deadline', 'delivery_deadline', 'max_provider_requests', 'model', 'reasoning']},
        'plan_sha256': digest(plan), 'adoption_gates': read(directory / 'adoption-gates.json'),
        'method': 'Prospective new constructed materials; AI-assisted nonblind author; no expected labels in inference'}
    save(directory / 'round_state.json', state)
    save(directory / 'freeze.json', frozen)
    print('FROZEN: 12 x A/B x 2; <=96 requests, 180-second timeout, no transport retry')


def predict(directory):
    state = guard(directory)
    if state['phase'] not in {'FROZEN', 'PREDICTING'}:
        raise ValueError('Frozen unfinished inference phase required')
    # Inject only the new fixed plan and candidate wrapper into the existing
    # serial bounded engine. Its persistent reservation/timeout/watchdog remain.
    bounded.fixed_plan = fixed_plan
    bounded.run_review = candidate_review
    bounded.predict(directory)


def score(directory):
    state = guard(directory)
    if state['full_score_passes'] >= 2:
        raise ValueError('Two scoring passes already exhausted')
    if not (directory / 'prediction-seal.json').exists():
        raise ValueError('Predictions must be sealed before totals are opened')
    frozen = read(directory / 'freeze.json')
    if any(sha(p) != h for p, h in frozen['files'].items()):
        raise ValueError('Frozen evaluator/runtime/data drift')
    state['full_score_passes'] += 1
    save(directory / 'round_state.json', state)
    expected = read(directory / 'expected.json')
    rows = []
    for item in state['plan']:
        case, source = prepared(directory / 'inputs' / (item['case_id'] + '.json'))
        labels = expected['cases'][case.case_id]
        stages = []
        for n in item['calls']:
            folder = directory / 'calls' / f'call-{n:03}'
            answer = read(folder / 'answer.json') if (folder / 'answer.json').exists() else None
            prompt = (folder / 'prompt.txt').read_text(encoding='utf-8')
            stages.append({'call': n, 'raw': answer, 'raw_sha256': digest(answer),
                'prompt_path': str(folder / 'prompt.txt'),
                'visible_response_path': str(folder / 'visible_answer.txt'),
                'validation_error_before_this_call': prompt.split('RUNTIME VALIDATION ERRORS:\n', 1)[1].split('\nPREVIOUS PROPOSAL:', 1)[0] if 'RUNTIME VALIDATION ERRORS:\n' in prompt else None})
        raw = stages[0]['raw'] if stages else None
        packet = read(item['output']) if item.get('output') else None
        first = score_output(raw.get('facts', []) if isinstance(raw, dict) else [], source, labels, proposal_identity=raw)
        final = score_output(packet['facts'] if packet else [], source, labels)
        rows.append({**item, 'source': source, 'source_sha256': digest(source), 'stages': stages,
            'first': first, 'final': final, 'packet': packet,
            'family': labels['family'], 'length_stratum': labels['length_stratum'],
            'execution_failed': packet['execution']['execution_failed'] if packet else True,
            'predeclared_unresolved': sum(len(s.get('unresolved_fields', {})) for s in labels['facts'])})
    groups = {}
    for candidate in ['A', 'B']:
        selected = [r for r in rows if r['candidate'] == candidate]
        groups[candidate] = {'executions': len(selected), 'execution_failures': sum(r['execution_failed'] for r in selected)}
        for stage in ['first', 'final']:
            counts = Counter()
            extras = Counter()
            for row in selected:
                counts.update(row[stage]['metrics'])
                extras.update(e['category'] for e in row[stage]['extras'])
            groups[candidate][stage] = {'metrics': dict(counts), 'extra_categories': dict(extras)}
    pairs = []
    for case in sorted(expected['cases']):
        for repeat in [1, 2]:
            a = next(r for r in rows if r['case_id'] == case and r['repeat'] == repeat and r['candidate'] == 'A')
            b = next(r for r in rows if r['case_id'] == case and r['repeat'] == repeat and r['candidate'] == 'B')
            pair = dict(case_id=case, repeat=repeat, family=a['family'], length_stratum=a['length_stratum'])
            for stage in ['first', 'final']:
                cells = lambda r: {(c['constraint_id'], f['field']): f['status'] for c in r[stage]['constraints'] for f in c['fields']}
                ac, bc = cells(a), cells(b)
                common = [k for k in ac if ac[k] != 'UNRESOLVED' and bc[k] != 'UNRESOLVED']
                pair[stage] = {'common_fields': len(common), 'A_errors': sum(ac[k] != 'CORRECT' for k in common),
                    'B_errors': sum(bc[k] != 'CORRECT' for k in common),
                    'changes': [{'constraint_id': k[0], 'field': k[1], 'A': ac[k], 'B': bc[k]} for k in common if ac[k] != bc[k]],
                    'unresolved': [list(k) for k in ac if k not in common]}
            pairs.append(pair)
    calls = []
    for record in state['calls']:
        u = read(Path(record['folder']) / 'usage.json')
        metrics = u.get('call_metrics', [])
        calls.append({**record, 'usage': metrics[-1].get('tokens') if metrics else None})
    result = {'version': VERSION, 'analysis': 'PROSPECTIVE_CONSTRUCTED_NOTE_COMPARISON',
        'groups': groups, 'rows': rows, 'pairs': pairs, 'actual_provider_requests': state['attempts'],
        'calls': calls, 'original_full_text_notes': 0, 'constructed_notes': 12,
        'human_review_completed': False, 'reviewer_type': 'AI_ASSISTED', 'author_blind': False,
        'semantic_citation_precision': 'UNAVAILABLE: extras need bounded source review, not positional verification',
        'overall_fact_precision_recall': 'UNAVAILABLE: finite selected constraints are not exhaustive independent labels'}
    out = directory / f'score-pass-{state["full_score_passes"]:02}.json'
    save(out, result)
    print(json.dumps({'groups': groups, 'requests': state['attempts']}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['preflight', 'freeze', 'predict', 'score'])
    parser.add_argument('--round', type=Path, required=True)
    args = parser.parse_args()
    globals()[args.phase](args.round.resolve())


if __name__ == '__main__':
    main()
