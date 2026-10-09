import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from clinical_intelligence.luna_candidates import CandidateExtractor, typed_schema
from clinical_intelligence.domain import RegisteredDocument, ServiceClaim, ServiceSource, AssessmentClaim
from clinical_intelligence.reconcile import reconcile
from clinical_intelligence.semantic_contract import project_payload
from test_luna_contract import provider


def test_source_metadata_projects_original_signature_and_preserves_raw_input():
    raw=dict(source=dict(content_kind='attendance',transmission_status='retransmitted',original_signed=True,current_signed=False,source_disposition='Attended'))
    saved=deepcopy(raw);value=project_payload('service',raw)
    assert raw==saved
    assert value['evidence_kind']=='retransmission' and value['signed'] is True
    assert value['source']['current_signed'] is False
    unknown=project_payload('service',dict(source=dict(saved['source'],original_signed=None)))
    assert unknown['signed'] is None


def test_model_schema_separates_axes_only_for_new_contract():
    old=typed_schema('Exact line','span_id')
    new=typed_schema('Exact line','span_id',semantic=True)
    def service(schema):return next(v['properties']['data'] for v in schema['properties']['extractions']['items']['anyOf'] if v['properties']['kind']['enum']==['service'])
    assert 'source' not in service(old)['properties']
    assert {'signed','evidence_kind'} <= service(old)['properties'].keys()
    assert 'source' in service(new)['required']
    assert 'signed' not in service(new)['properties'] and 'evidence_kind' not in service(new)['properties']
    assert service(new)['properties']['source']['properties']['transmission_status']['enum']==['original','retransmitted','unknown']


def fixed_packet():
    text=('Document ID: PACK-1 | MRN: PAT-1 | Patient: Test Person\n'
          'OLD ATTACHMENT Encounter: EVT-1 | 2026-03-01 | Original signed 10:45.\n'
          'Copied attendance patient contact 10:00 to 10:20.\n'
          'Retransmission for Encounter EVT-1 dated 2026-03-01, no new signature.\n'
          'NEW ENTRY Encounter: EVT-1 | 2026-03-01 | Signed 11:00.\n'
          'New patient contact 10:20 to 10:40.\n')
    doc=RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text=text)
    identity=dict(kind='patient',span_id='L0001',context_span_ids=[],data=dict(patient_id='PAT-1',name='Test Person',dob=None,declared_id='PACK-1'))
    base=dict(service_date='2026-03-01',encounter_ref='EVT-1',service_type='individual',patient_present=True,delivered=True,statement='Supported contact')
    old=dict(kind='service',span_id='L0003',context_span_ids=['L0002'],data=dict(base,actual_intervals=[dict(start='10:00',end='10:20')],source=dict(content_kind='attendance',transmission_status='retransmitted',original_signed=True,current_signed=False,source_disposition=None)))
    new=dict(kind='service',span_id='L0006',context_span_ids=['L0005'],data=dict(base,actual_intervals=[dict(start='10:20',end='10:40')],source=dict(content_kind='clinical',transmission_status='original',original_signed=None,current_signed=True,source_disposition=None)))
    relation=dict(kind='relationship',span_id='L0004',context_span_ids=[],data=dict(statement='Old attachment retransmitted',relation='retransmits',target_encounter='EVT-1',service_date='2026-03-01',field='record',signed=False))
    return doc,dict(identity=identity,extractions=[old,new,relation])


def test_mixed_packet_excludes_old_attachment_but_keeps_new_same_encounter():
    doc,proposal=fixed_packet();e=CandidateExtractor(provider(),dict(schema='typed',evidence='span_id',identity_object=True,semantic_contract='v1'))
    extraction=e.from_result(doc,e.convert(doc,proposal),0)
    assert len(extraction.claims[0].passages)==2
    event=reconcile([extraction]).events[0]
    assert event.minute_options==[20] and event.countable is True
    sources={c.claim_id:c for c in extraction.claims}
    excluded=next(d for d in event.decisions if d.rule=='evidence_role')
    assert all(sources[c].source.transmission_status=='retransmitted' for c in excluded.claim_ids)


def test_historical_score_stays_auditable_without_creating_completion_or_trend():
    from clinical_intelligence.domain import DocumentExtraction,Patient,SourcePassage
    p=SourcePassage(document_id='d',start=0,end=4,quote='text',line_start=1,line_end=1)
    base=dict(document_id='d',patient_id='PAT-1',passages=[p],statement='Referenced score',instrument='PHQ-9',reporter='not specified',experiencer='patient')
    current=AssessmentClaim(**base,claim_id='current',form_ref='FORM-1',score=12,assessment_date='2026-03-05')
    history=AssessmentClaim(**base,claim_id='old',score=18,source_role='historical_mention',reference_date='2026-02-01',assessment_date=None,copied=True)
    abstraction=reconcile([DocumentExtraction(document_id='d',extraction_key='x',declared_id='DOC-1',patient=Patient(patient_id='PAT-1',name='Test'),claims=[current,history],usage=provider().usage(0))])
    assert len(abstraction.assessments)==1
    assert abstraction.historical_assessments==[history]
    assert history.assessment_date is None


def test_retransmission_cannot_be_asserted_without_linked_record_relation():
    doc,proposal=fixed_packet();proposal['extractions']=proposal['extractions'][:2]
    e=CandidateExtractor(provider(),dict(schema='typed',evidence='span_id',identity_object=True,semantic_contract='v1'))
    with pytest.raises(ValueError,match='explicitly linked retransmits'):
        e.from_result(doc,e.convert(doc,proposal),0)


def test_semantic_examples_have_no_redundant_projected_source_fields():
    doc,_=fixed_packet();cfg=json.loads((Path(__file__).resolve().parents[1]/'src/clinical_intelligence/contracts/luna_semantic.json').read_text())
    prompt,schema=CandidateExtractor(provider(),cfg).request(doc)
    examples=json.loads(prompt.split('Examples:\n')[1].split('\nFor this input')[0])
    for example in examples:
        for row in example['extractions']:
            assert 'context_span_ids' in row
            if row['kind']=='service':
                assert 'source' in row['data'] and 'signed' not in row['data'] and 'evidence_kind' not in row['data']


def test_new_source_metadata_has_distinct_cache_identity():
    a=CandidateExtractor(provider(),dict(schema='typed'))
    b=CandidateExtractor(provider(),dict(schema='typed',semantic_contract='v1'))
    assert a.key!=b.key


def test_additional_evidence_from_another_claim_does_not_share_claim_id():
    doc,proposal=fixed_packet();e=CandidateExtractor(provider(),dict(schema='typed',evidence='span_id',identity_object=True,semantic_contract='v1'))
    a=e.from_result(doc,e.convert(doc,deepcopy(proposal)),0)
    proposal['extractions'][1]['context_span_ids'].append('L0001')
    b=e.from_result(doc,e.convert(doc,proposal),0)
    assert a.claims[1].claim_id!=b.claims[1].claim_id


def test_readable_negative_statement_is_not_negated_again_by_query():
    from clinical_intelligence.query import QuerySpec,query_patient
    p=provider();doc=RegisteredDocument(document_id='d',fingerprint='d',source_names=['d'],text='Document ID: DOC-1 | MRN: PAT-1 | Patient: Test Person\nPatient has not established a routine. Report date 2026-03-01.\n')
    identity=dict(kind='patient',span_id='L0001',data=dict(patient_id='PAT-1',name='Test Person',dob=None,declared_id='DOC-1'))
    obs=dict(kind='observation',span_id='L0002',data=dict(statement='Patient has not established a routine.',observation_date='2026-03-01',category='function',reporter='patient',experiencer='patient',polarity='absent',temporality='current'))
    e=CandidateExtractor(p,dict(schema='typed',evidence='span_id',identity_object=True))
    extraction=e.from_result(doc,e.convert(doc,dict(identity=identity,extractions=[obs])),0)
    result=query_patient(reconcile([extraction]),QuerySpec(family='progress',start='2026-03-01',end='2026-03-02'))['result']
    assert result['observations'][0]['polarity']=='absent'
    assert result['observations'][0]['statement']=='Patient has not established a routine.'


def test_single_runtime_repair_receives_all_independent_source_violations():
    doc, proposal = fixed_packet()
    doc.text += 'Appointment EVT-1 links the new contact.\n'
    proposal['extractions'][1]['data']['source']['source_disposition'] = 'Completed contact'
    calls = []
    p = provider()

    def output(prompt, schema, *, purpose):
        calls.append(purpose)
        if purpose == 'extraction':
            return deepcopy(proposal)
        if purpose == 'clinical_assertions':
            return dict(extractions=[])
        error = prompt.split('ERROR:\n')[1].split('\nPROPOSAL:')[0]
        assert 'Explicit appointment ID omitted' in error
        assert 'Literal source disposition lacks linked evidence' in error
        assert 'EVT-1' in error and 'Completed contact' in error
        fixed = deepcopy(proposal)
        fixed['extractions'][1]['data']['appointment_ref'] = 'EVT-1'
        fixed['extractions'][1]['data']['source']['source_disposition'] = 'New patient contact'
        return fixed

    p.structured_output = output
    e = CandidateExtractor(p, dict(schema='typed', evidence='span_id', identity_object=True,
        semantic_contract='v1', flow='clinical_partition', observation_scope=True))
    result = e.extract(doc)
    assert calls == ['extraction', 'clinical_assertions', 'validation_repair']
    assert result.usage.retry_count == 1
    assert result.claims[1].appointment_ref == 'EVT-1'
    assert result.claims[1].source.source_disposition == 'New patient contact'
    # A repair cannot pass by fixing just the first issue.
    invalid = deepcopy(proposal)
    invalid['extractions'][1]['data']['appointment_ref'] = 'EVT-1'
    with pytest.raises(ValueError, match='Literal source disposition'):
        e.from_result(doc, e.convert(doc, invalid), 0)
