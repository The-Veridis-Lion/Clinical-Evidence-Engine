"""Offline candidate wiring and new-material evaluator controls; no real provider."""
import copy
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest
from clinical_intelligence.claims_review import cli
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.note_extractor import PROMPT
from clinical_intelligence.claims_review.note_prompt_b import PROMPT_B
from b_candidate_validation import candidate_review, fixed_plan, guard, prepared
from luna_ab_rescore import score_output, save, numeric_projection

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / 'examples/claims_review/b_candidate_v1'


class Fake:
    def __init__(self, case, facts):
        self.case = case
        self.facts = facts
        self.requests = []

    def structured_output(self, prompt, schema, *, purpose):
        self.requests.append((prompt, schema, purpose))
        return dict(patient_id=self.case.claim.patient_id,
                    source_id=self.case.sources[0].source_id, facts=self.facts)


def test_plan_is_complete_balanced_and_repeat_layered():
    plan = fixed_plan()
    assert len(plan) == 48 and plan == fixed_plan()
    assert len({p['execution_id'] for p in plan}) == 48
    assert all(p['repeat'] == 1 for p in plan[:24])
    assert all(p['repeat'] == 2 for p in plan[24:])
    for a, b in zip(plan[::2], plan[1::2]):
        assert a['case_id'] == b['case_id'] and {a['candidate'], b['candidate']} == {'A', 'B'}


def test_candidate_entry_B_and_A_have_same_context_schema_and_separate_identity():
    case, _ = prepared(ROUND / 'N05.json')
    labels = json.loads((ROUND / 'expected.json').read_text())['cases']['N05']
    a = Fake(case, labels['correct_fixture'])
    b = Fake(case, labels['correct_fixture'])
    pa = candidate_review(case, mode='fixture', provider=a, note_prompt='A')
    pb = candidate_review(case, mode='fixture', provider=b)
    assert len(a.requests) == len(b.requests) == 1
    ap, sa, _ = a.requests[0]
    bp, sb, _ = b.requests[0]
    assert ap.startswith(PROMPT) and bp.startswith(PROMPT_B)
    assert ap[len(PROMPT):] == bp[len(PROMPT_B):] and sa == sb
    assert pa.execution['note_prompt_selection']['note_prompt'] == 'A'
    assert pb.execution['note_prompt_selection']['note_prompt'] == 'B'
    assert pa.identity['candidate_request_sha256'] != pb.identity['candidate_request_sha256']
    assert pa.execution['application_cache_hit'] is pb.execution['application_cache_hit'] is False


@pytest.mark.parametrize('variant', [None, 'A', 'B'])
def test_actual_cli_selector_and_unchanged_default(variant, monkeypatch, tmp_path):
    case, _ = prepared(ROUND / 'N05.json')
    labels = json.loads((ROUND / 'expected.json').read_text())['cases']['N05']
    fake = Fake(case, labels['correct_fixture'])
    monkeypatch.setattr(cli, 'live_provider', lambda args: (fake, None))
    args = ['run', '--case', str(ROUND / 'N05.json'), '--mode', 'live', '--output', str(tmp_path / 'packet.json')]
    if variant:
        args += ['--note-prompt', variant]
    assert cli.main(args) == 0
    assert fake.requests[0][0].startswith(PROMPT if variant == 'A' else PROMPT_B)


def test_terminal_deadline_guard_never_reopens(tmp_path):
    state = {'terminal_status': 'B_NOT_READY', 'attempts': 48,
             'work_deadline': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    save(tmp_path / 'round_state.json', state)
    with pytest.raises(RuntimeError, match='terminal'):
        guard(tmp_path)
    state['terminal_status'] = None
    state['work_deadline'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    save(tmp_path / 'round_state.json', state)
    with pytest.raises(RuntimeError, match='deadline'):
        guard(tmp_path)


def test_new_source_conflict_cannot_hide_behind_one_correct_assertion():
    _, source = prepared(ROUND / 'N01.json')
    labels = json.loads((ROUND / 'expected.json').read_text())['cases']['N01']
    facts = copy.deepcopy(labels['correct_fixture'])
    wrong = copy.deepcopy(facts[0])
    wrong['value'] = False
    facts.append(wrong)
    scored = score_output(facts, source, labels)
    assert not scored['complete_common_scored_constraints']
    assert scored['metrics']['contradictory_propositions'] >= 1


def test_wrong_units_and_noncurrent_events_remain_distinct():
    assert numeric_projection('7.2 mg/dL')['status'] == 'INVALID'
    _, source = prepared(ROUND / 'N03.json')
    labels = json.loads((ROUND / 'expected.json').read_text())['cases']['N03']
    facts = copy.deepcopy(labels['correct_fixture'])
    facts[0]['span_ids'] = [source['line_anchors'][2]['span_id']]
    scored = score_output(facts, source, labels)
    assert not scored['complete_common_scored_constraints']


def test_bool_null_zero_missing_and_wrong_date_roles_are_not_interchangeable():
    _, source = prepared(ROUND / 'N08.json')
    labels = json.loads((ROUND / 'expected.json').read_text())['cases']['N08']
    for value in [True, None, 0]:
        facts = copy.deepcopy(labels['correct_fixture'])
        facts[0]['value'] = value
        assert not score_output(facts, source, labels)['complete_common_scored_constraints']
    _, source = prepared(ROUND / 'N01.json')
    labels = json.loads((ROUND / 'expected.json').read_text())['cases']['N01']
    facts = copy.deepcopy(labels['correct_fixture'])
    facts[1]['date_role'] = 'order_issued'
    assert not score_output(facts, source, labels)['complete_common_scored_constraints']
    del facts[1]['value']
    assert score_output(facts, source, labels)['metrics']['missing_fields'] >= 1
