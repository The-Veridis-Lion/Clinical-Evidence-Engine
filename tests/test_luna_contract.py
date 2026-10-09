from types import SimpleNamespace
import pytest
from clinical_intelligence.provider import CodexCLIProvider, ProviderConfig
from clinical_intelligence.luna_candidates import typed_schema, CandidateExtractor
from clinical_intelligence.domain import RegisteredDocument


def provider():
    p=object.__new__(CodexCLIProvider)
    p.config=ProviderConfig();p.cli_version='fixed';p.reset_usage()
    return p


@pytest.mark.parametrize('option',['temperature','top_p','made_up_parameter'])
def test_requested_generation_parameter_is_rejected_before_a_call(option):
    p=provider();model=p.language_model([], 'source')
    with pytest.raises(ValueError,match='does not support'):
        list(model.infer(['request'],**{option:0.1}))
    assert p.usage(0).model_calls==0


def test_typed_generation_contract_constrains_clinical_fields():
    schema=typed_schema('original line','span_id')
    service=next(v for v in schema['properties']['extractions']['items']['anyOf'] if v['properties']['kind']['enum']==['service'])
    data=service['properties']['data']
    assert data['type']=='object'
    assert 'encounter_ref' in data['required'] and 'patient_present' in data['required']
    assert 'document_id' not in data['properties']
    assert data['properties']['actual_intervals']['items']['properties']['start']['type']=='string'


def test_cli_version_invalidates_extraction_identity():
    a=provider();b=provider();b.cli_version='different'
    assert CandidateExtractor(a,{'schema':'typed'}).key!=CandidateExtractor(b,{'schema':'typed'}).key


def test_unknown_candidate_parameter_cannot_be_silently_ignored():
    with pytest.raises(ValueError,match='Unsupported extraction configuration'):
        CandidateExtractor(provider(),{'temperature':0})


def test_clinical_partition_keeps_full_input_but_only_observation_output():
    doc=RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text='Patient P-1\nPatient contact 10:00 to 10:30.\nPatient denies suicidal thoughts.\n')
    e=CandidateExtractor(provider(),dict(schema='typed',prompt='concise',examples='documents',
        aligned_examples=True,identity_object=True,evidence='span_id'))
    prompt,schema=e.request(doc,kinds=['observation'])
    assert 'Patient contact 10:00' in prompt
    assert 'identity' not in schema['properties']
    assert [v['properties']['kind']['enum'] for v in schema['properties']['extractions']['items']['anyOf']]==[['observation']]


def test_span_reference_maps_duplicate_to_its_original_occurrence():
    doc=RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text='same\nsame\n')
    e=CandidateExtractor(provider(),{'schema':'typed','evidence':'span_id'})
    result=e.convert(doc,{'extractions':[{'kind':'service','data':{},'span_id':'L0002'}]})
    value=result.extractions[0]
    assert doc.text[value.char_interval.start_pos:value.char_interval.end_pos]==value.extraction_text=='same'
    assert value.char_interval.start_pos==5


def test_fixed_clinical_partition_preserves_contact_and_replaces_wrong_negation():
    from copy import deepcopy
    p=provider();calls=[]
    doc=RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text=
        'MRN: P-1 | Patient: Test Person | Document ID: D-1\n'
        'Signed individual Encounter E-1 on 2026-03-01; patient contact 10:00 to 10:20.\n'
        'Patient denies suicidal thoughts.\n')
    patient=dict(kind='patient',span_id='L0001',data=dict(patient_id='P-1',name='Test Person',dob=None,declared_id='D-1'))
    service=dict(kind='service',span_id='L0002',data=dict(statement='Patient contact',encounter_ref='E-1',
        service_date='2026-03-01',service_type='individual',evidence_kind='clinical',signed=True,
        patient_present=True,delivered=True,actual_intervals=[dict(start='10:00',end='10:20')]))
    observation=dict(kind='observation',span_id='L0003',data=dict(statement='Patient denies suicidal thoughts.',
        observation_date='2026-03-01',category='safety',reporter='patient',experiencer='patient',
        polarity='absent',temporality='current'))
    def output(prompt,schema,*,purpose):
        calls.append(purpose)
        if purpose=='extraction':
            wrong=deepcopy(observation);wrong['data']['polarity']='present'
            return dict(identity=patient,extractions=[service,wrong])
        return dict(extractions=[observation])
    p.structured_output=output
    e=CandidateExtractor(p,dict(schema='typed',prompt='concise',examples='documents',evidence='span_id',
        identity_object=True,aligned_examples=True,flow='clinical_partition',observation_scope=True))
    result=e.extract(doc)
    assert calls==['extraction','clinical_assertions']
    assert len(result.claims)==2
    assert result.claims[0].actual_intervals[0].end-result.claims[0].actual_intervals[0].start==20
    assert result.claims[1].polarity=='absent'


@pytest.mark.parametrize('schema',['typed'])
def test_aligned_full_examples_and_required_identity_can_be_requested(schema):
    import json
    doc=RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text='Document ID: D-1\nMRN: P-1\nEncounter: E-1\n')
    e=CandidateExtractor(provider(),dict(schema=schema,prompt='concise',examples='documents',
        expanded_examples=True,aligned_examples=True,evidence='span_id',identity_object=True))
    prompt,contract=e.request(doc)
    assert 'identity' in contract['required']
    assert all(v['properties']['kind']['enum']!=['patient'] for v in contract['properties']['extractions']['items']['anyOf'])
    examples=json.loads(prompt.split('Examples:\n',1)[1].split('\nFor this input',1)[0])
    assert all('identity' in item for item in examples)
    for item in examples:
        for row in item['extractions']+[item['identity']]:
            assert 'span_id' in row and 'quote' not in row
            assert row['span_id']+':' in item['text']
