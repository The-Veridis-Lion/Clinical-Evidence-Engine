import json
from pathlib import Path
import pytest
from clinical_intelligence.domain import AssessmentClaim, PlanClaim, FieldUncertainty, TimeInterval, Patient, CorrectionRelationship
from clinical_intelligence.luna_candidates import CandidateExtractor, typed_schema
from clinical_intelligence.query import QuerySpec, query_patient
from clinical_intelligence.reconcile import reconcile
from clinical_intelligence.uncertainty_contract import field_state
from test_luna_contract import provider


def utilization(extraction):
    return query_patient(reconcile([extraction]), QuerySpec(family='utilization', start='2026-02-01', end='2026-02-28'))['result']['totals']


@pytest.mark.parametrize('signed,present,delivered', [(True, True, True), (False, False, False), (None, None, None)])
def test_boolean_source_values_survive_adapter_and_reconciliation(evidence, service, signed, present, delivered):
    ext = evidence('d', [service(signed=signed, patient_present=present, delivered=delivered)])
    claim = ext.claims[0]
    assert (claim.signed, claim.patient_present, claim.delivered) == (signed, present, delivered)
    totals = utilization(ext)
    if signed is True:
        assert totals['minutes']['value'] == 45
    elif present is False:
        assert totals['minutes']['value'] == 0
    else:
        assert totals['minutes']['value'] is None and totals['minutes']['upper'] == 45


def test_known_contact_retained_when_signature_is_undocumented(evidence, service):
    ext=evidence('d',[service(signed=None)])
    a=reconcile([ext]);e=a.events[0]
    assert e.patient_present is True and e.delivered is True
    assert e.countable is None and e.minute_options == [45]
    assert utilization(ext)['minutes'] == dict(lower=0, upper=45, value=None)


@pytest.mark.parametrize('target',['SYN-E1',None])
def test_unknown_correction_signature_does_not_certify_original_or_zero(evidence,service,target):
    ext=evidence('d',[service(),dict(factory=CorrectionRelationship,relation='corrects',signed=None,target_encounter=target,field='minutes',replacement_minutes=30,service_date='2026-02-02')])
    a=reconcile([ext])
    assert a.source_claims[0].actual_intervals[0].end == 585
    assert a.relationships[0].signed is None and a.relationships[0].replacement_minutes == 30
    assert utilization(ext)['minutes']['value'] is None


@pytest.mark.parametrize('state',['not_documented','ambiguous','not_applicable'])
def test_missing_field_state_keeps_supported_other_fields(evidence, service, state):
    ext=evidence('d',[service(service_date=None, uncertainty_notes=[dict(field='service_date',state=state,explanation='Source scope does not establish a service date.')])])
    c=ext.claims[0]
    assert field_state(c,'service_date') == state
    assert field_state(c,'signed') == 'known'
    assert c.delivered is True and c.actual_intervals[0].start == 540
    assert utilization(ext)['minutes']['value'] is None


def test_real_conflict_retains_both_sources_instead_of_collapsing_to_null(evidence, service):
    a=reconcile([evidence('d1',[service(actual_intervals=[],reported_minutes=40)]),evidence('d2',[service(actual_intervals=[],reported_minutes=50)])])
    e=a.events[0]
    assert e.state == 'conflicted' and e.minute_options == [40,50]
    assert {c.reported_minutes for c in a.source_claims} == {40,50}


def test_incomplete_clock_is_retained_and_cannot_certify_zero_duration(evidence, service):
    ext=evidence('d',[service(actual_intervals=[dict(start=540,end=None)])])
    assert ext.claims[0].actual_intervals[0].start == 540
    assert ext.claims[0].actual_intervals[0].end is None
    assert utilization(ext)['minutes'] == dict(lower=0, upper=None, value=None)


@pytest.mark.parametrize('field',['actual_intervals','actual_intervals[0].end'])
def test_partial_interval_note_cannot_discard_known_start(evidence,service,field):
    ext=evidence('d',[service(actual_intervals=[dict(start=540,end=None)],uncertainty_notes=[dict(field=field,state='not_documented',explanation='End not documented.')])])
    assert ext.claims[0].actual_intervals[0].start == 540
    assert utilization(ext)['minutes']['upper'] is None


def test_partial_plan_keeps_known_threshold_without_imputing_missing_zero(evidence):
    ext=evidence('d',[dict(factory=PlanClaim,signed=True,effective_start='2026-02-02',required_days=2,required_minutes=None,service_types=['individual'],week_basis='monday_sunday')])
    a=reconcile([ext]);c=a.source_claims[0]
    assert c.required_days == 2 and c.required_minutes is None
    result=query_patient(a,QuerySpec(family='compliance',start='2026-02-02',end='2026-02-08'))['result']['weeks'][0]
    assert result['status'] == 'cannot_determine' and result['requirement'] is None


def test_assessment_missing_instrument_score_and_copy_status_survives_queries(evidence):
    ext=evidence('d',[dict(factory=AssessmentClaim,instrument=None,score=None,copied=None,reporter='not specified',experiencer='not specified')])
    a=reconcile([ext]);assert a.assessments[0].score_options == []
    result=query_patient(a,QuerySpec(family='assessments',start='2026-02-01',end='2026-02-28'))['result']
    assert result['undated_assessments'][0]['instrument'] is None and result['score_changes'] == []
    assert a.source_claims[0].copied is None


def test_unknown_instrument_can_coexist_with_named_assessment(evidence):
    ext=evidence('d',[dict(factory=AssessmentClaim,instrument=instrument,score=None,copied=None,
        reporter='not specified',experiencer='not specified') for instrument in (None,'PHQ-9')])
    a=reconcile([ext])
    assert {item.instrument for item in a.assessments} == {None,'PHQ-9'}
    assert all(item.state == 'insufficient_evidence' for item in a.assessments)


def test_pure_administration_can_have_no_service_and_zero_qualifying_care(evidence):
    ext=evidence('d',[])
    assert reconcile([ext]).events == [] and utilization(ext)['minutes']['value'] == 0


def test_unlinked_documents_persist_separately_without_inventing_patient_ids(tmp_path,evidence,service):
    from clinical_intelligence.storage import SQLiteStore
    from clinical_intelligence.pipeline import load_patient
    with SQLiteStore(tmp_path/'unlinked.sqlite') as store:
        extractions=[]
        for i in (1,2):
            doc,_=store.register(f'd{i}',f'Anonymous clinical document {i}')
            ext=evidence(doc.document_id,[service(quote=doc.text)]);ext.patient=Patient()
            ext.claims[0].patient_id=None;store.save_extraction(ext);extractions.append(ext)
        ids=store.patient_ids()
        assert len(ids)==2 and all(i.startswith('unlinked:') for i in ids)
        assert load_patient(store,ids[0]).patient.patient_id is None
        with pytest.raises(ValueError,match='Unlinked documents cannot be merged'):
            reconcile(extractions)


def test_nullable_generation_contract_requires_keys_and_has_aligned_unknown_example():
    old=typed_schema('source','span_id');new=typed_schema('source','span_id',uncertainty=True)
    for kind in ('service','plan','assessment','observation','relationship'):
        node=next(v['properties']['data'] for v in new['properties']['extractions']['items']['anyOf'] if v['properties']['kind']['enum']==[kind])
        assert node['required'] == list(node['properties'])
    service_schema=next(v['properties']['data'] for v in new['properties']['extractions']['items']['anyOf'] if v['properties']['kind']['enum']==['service'])
    assert any(v.get('type')=='null' for v in service_schema['properties']['signed']['anyOf'])
    assert service_schema['properties']['actual_intervals']['items']['properties']['end']['type'] == ['string','null']
    from clinical_intelligence.domain import RegisteredDocument
    cfg=json.loads((Path(__file__).resolve().parents[1]/'src/clinical_intelligence/contracts/luna_uncertainty.json').read_text())
    prompt,_=CandidateExtractor(provider(),cfg).request(RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text='MRN: P-1\n'))
    assert 'Do not guess, but do not abstain when the evidence is sufficient.' in prompt
    examples=json.loads(prompt.split('Examples:\n')[1].split('\nFor this input')[0])
    unknown=examples[-1]['extractions'][0]['data']
    assert unknown['signed'] is None and unknown['actual_intervals'][0]['end'] is None


def test_all_unknown_interval_and_false_surrogates_are_rejected(evidence,service):
    with pytest.raises(ValueError,match='source-supported endpoint'):
        TimeInterval(start=None,end=None)
    with pytest.raises(ValueError):
        evidence('d',[service(signed=0)])
    with pytest.raises(ValueError):
        evidence('d',[dict(factory=AssessmentClaim,instrument='PHQ-9',score=False,reporter='patient',experiencer='patient')])
    zero=evidence('d',[dict(factory=AssessmentClaim,instrument='PHQ-9',score=0,reporter='patient',experiencer='patient')])
    assert zero.claims[0].score == 0
    with pytest.raises(ValueError,match='Empty text is not an unknown'):
        evidence('d',[service(appointment_ref='')])


def test_known_patient_role_and_name_are_symmetric_in_shared_scoring(evidence):
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
    from luna_experiment import score
    ext=evidence('d',[dict(factory=AssessmentClaim,instrument='PHQ-9',form_ref='F-1',score=5,reporter='Taylor Example',experiencer='Taylor Example')],declared_id='D-1')
    row=dict(patient=ext.patient.model_dump(mode='json'),declared_id='D-1',text=ext.claims[0].passages[0].quote,facts=[dict(kind='assessment',form_ref='F-1',reporter='patient',experiencer='patient')],exhaustive=True)
    assert score(row,ext)['document_correct']
    row['facts'][0]['experiencer']='partner'
    assert not score(row,ext)['document_correct']


def test_unknown_example_roundtrips_real_adapter_without_dropping_other_facts():
    from clinical_intelligence.domain import RegisteredDocument
    from clinical_intelligence.uncertainty_contract import uncertainty_examples
    raw=uncertainty_examples([])[0]
    doc=RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text=raw['text'])
    from clinical_intelligence.luna_candidates import source_lines
    for row in raw['extractions']:
        quote=row.pop('quote')
        row['span_id']=next(k for k,v in source_lines(doc.text).items() if v[0]==quote)
    proposal=dict(identity=raw['extractions'][0],extractions=raw['extractions'][1:])
    e=CandidateExtractor(provider(),dict(schema='typed',evidence='span_id',identity_object=True,uncertainty_contract='v1'))
    result=e.from_result(doc,e.convert(doc,proposal),0)
    assert result.claims[0].signed is None and result.claims[0].patient_present is True
    assert result.claims[0].actual_intervals[0].start==600 and result.claims[0].actual_intervals[0].end is None
    assert result.claims[1].score is None and result.claims[1].copied is None
