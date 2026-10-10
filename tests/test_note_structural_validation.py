"""Offline structural controls; clinical interpretation is outside validation."""
from datetime import date
import pytest
from clinical_intelligence.claims_review.note_extractor import (
    RuntimeValidationError, adapt, extract_note, preserves, validate_proposal,
)
from clinical_intelligence.claims_review.prepare import line_anchors
from test_claims_review_integration import FixtureProvider


def source(text='Dr. Imani Shah withdrew the HbA1c order on 2026-09-19.'):
    return dict(patient_id='P', source_id='NOTE', encounter_id=None,
                recorded_at='2026-10-10', available_at='2026-10-10',
                event_link_id=None, content=text, source_kind='synthetic_note',
                line_anchors=line_anchors('NOTE', text))


def row(**updates):
    result = dict(kind='test_mention', statement='An assertion from the note.',
                  value=None, fact_date=None, date_role='unknown',
                  temporal_status='unknown', target_date=None, test_specific=None,
                  provider=None, reporter=None, authenticated=None,
                  span_ids=['NOTE:L001'])
    result.update(updates)
    return result


def proposal(*rows):
    return dict(patient_id='P', source_id='NOTE', facts=list(rows))


def validate(raw, note=None):
    return validate_proposal(raw, note or source(), date(2026, 10, 10))


@pytest.mark.parametrize('field', ['patient_id', 'source_id'])
def test_wrong_identity_rejected(field):
    raw = proposal(row())
    raw[field] = 'OTHER'
    with pytest.raises(RuntimeValidationError, match=f'{field} must match'):
        validate(raw)


@pytest.mark.parametrize('raw', ['{invalid json', 'null', [], None])
def test_invalid_json_or_envelope_rejected(raw):
    with pytest.raises(RuntimeValidationError):
        validate(raw)


@pytest.mark.parametrize('updates', [dict(authenticated='true'), dict(test_specific=1),
    dict(value={}), dict(provider=2), dict(statement=''), dict(span_ids=[]),
    dict(span_ids=[1]), dict(kind='test_event'), dict(date_role='signature'),
    dict(temporal_status='completed'), dict(unexpected='field')])
def test_invalid_field_types_and_enums_rejected(updates):
    with pytest.raises(RuntimeValidationError):
        validate(proposal(row(**updates)))


def test_required_nullable_field_cannot_be_omitted():
    raw = proposal(row())
    del raw['facts'][0]['target_date']
    with pytest.raises(RuntimeValidationError):
        validate(raw)


@pytest.mark.parametrize('span', ['MISSING', 'OTHER-DOCUMENT:L001'])
def test_unknown_or_foreign_span_rejected(span):
    with pytest.raises(RuntimeValidationError, match='unknown span ID'):
        validate(proposal(row(span_ids=[span])))


@pytest.mark.parametrize('updates', [dict(start=-1), dict(end=10000), dict(start=True),
    dict(start=2,end=1), dict(start='0'), dict(quote='Altered source quote')])
def test_corrupted_source_offsets_and_quotes_rejected(updates):
    note = source()
    note['line_anchors'][0].update(updates)
    with pytest.raises(RuntimeValidationError, match='anchor slice mismatch'):
        validate(proposal(row()), note)


@pytest.mark.parametrize('field', ['fact_date', 'target_date'])
@pytest.mark.parametrize('value', ['2026-02-30', '20260920', '2026-09-20T00:00:00',
                                  '09/20/2026', '2026-9-20', 1790000000])
def test_dates_require_valid_iso_calendar_date(field, value):
    with pytest.raises(RuntimeValidationError):
        validate(proposal(row(**{field:value})))


@pytest.mark.parametrize('value', [None, False, 0, 0.0, True, 7.3, 'HbA1c'])
def test_values_preserve_exact_types_through_validation_and_adaptation(value):
    note = source()
    parsed = validate(proposal(row(value=value)), note)
    assert parsed.facts[0].value == value
    assert type(parsed.facts[0].value) is type(value)
    fact = adapt(parsed, note)[0]
    assert fact.value == value and type(fact.value) is type(value)
    assert fact.fact_date is None and fact.authenticated is None
    assert 'clinical correctness is not verified' in fact.details['structural_validation']


@pytest.mark.parametrize('kind,value', [('purpose','unsupported_enum'),
    ('clinical_rationale','unsupported_enum'), ('order_intent',0),
    ('diabetes_context','true'), ('regimen_change',1)])
def test_kind_specific_types_and_value_enums_are_still_structural(kind,value):
    with pytest.raises(RuntimeValidationError):
        validate(proposal(row(kind=kind,value=value)))


@pytest.mark.parametrize('wording', ["Dr. Imani Shah withdrew the HbA1c order.",
    'The physician rescinded the request.', 'The request was called off.',
    'No order paperwork is available.'])
def test_no_keyword_gate_on_negative_order_intent(wording):
    note = source(wording)
    raw = proposal(row(kind='order_intent', value=False, statement=wording))
    facts, record = extract_note(FixtureProvider(raw), note, {}, date(2026,10,10))
    assert record['status'] == 'completed' and record['calls'] == 1
    assert len(facts) == 1 and facts[0].value is False


def test_validator_does_not_infer_clinical_scope_or_temporal_authentication_meaning():
    note = source('A prior discussion.\nHbA1c is named in a different paragraph.')
    asserted = row(kind='order_intent', value=True, test_specific=True,
                   fact_date='2027-01-01', target_date='2027-02-01',
                   temporal_status='actual', provider='A differently worded name', authenticated=True)
    parsed = validate(proposal(asserted), note)
    assert parsed.facts[0].model_dump(mode='json') == asserted


def test_validation_never_calls_semantic_grounding_helpers(monkeypatch):
    from clinical_intelligence.claims_review import note_extractor
    def forbidden(*args, **kwargs):
        raise AssertionError('Semantic helper called during structural validation')
    for name in ['terminology', 'supports_monitoring_test', 'explicit_dates']:
        monkeypatch.setattr(note_extractor, name, forbidden)
    assert validate(proposal(row(kind='order_intent', value=False))).facts[0].value is False


@pytest.mark.parametrize('repair', [proposal(), RuntimeError('Mock provider failed')])
def test_structurally_valid_rows_survive_other_row_failure_and_bounded_repair(repair):
    note = source()
    valid = row(kind='order_intent', value=False)
    invalid = row(span_ids=['MISSING'])
    provider = FixtureProvider(proposal(valid, invalid), repair)
    facts, record = extract_note(provider, note, {}, date(2026,10,10))
    assert record['status'] == 'failed' and len(provider.requests) == 2
    assert any(f.kind=='order_intent' and f.value is False for f in facts)


def test_repair_cannot_confuse_false_with_zero():
    original = row(value=False)
    assert not preserves(original, [row(value=0)])
    assert not preserves(row(value=0), [row(value=False)])
    note = source()
    provider = FixtureProvider(proposal(original, row(span_ids=['MISSING'])), proposal(row(value=0)))
    facts, record = extract_note(provider, note, {}, date(2026,10,10))
    assert record['status']=='failed'
    assert any(f.value is False for f in facts)
