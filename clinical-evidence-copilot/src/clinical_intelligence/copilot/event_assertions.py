"""Versioned event/citation proposals layered on the existing fact contract."""
from .models import digest
from .source_adapter import TASK_VERSION, STRUCTURED_TASK_VERSION


def checked_anchors(packet):
    contract=packet.extraction_metadata.get('event_assertion_contract')
    if contract is None:
        return {}
    if (not isinstance(contract,dict) or set(contract)!={'version','source_sha256','assertions'} or
            contract['version'] not in {TASK_VERSION,STRUCTURED_TASK_VERSION} or contract['source_sha256']!=packet.source.sha256 or
            not isinstance(contract['assertions'],list)):
        raise ValueError('Event assertion contract differs from the original source/version')
    facts={f.fact_id:f for f in packet.facts};records={}
    for record in contract['assertions']:
        if (set(record)!={'fact_id','primary_source_id','selected_source_ids'} or
                record['fact_id'] not in facts or record['fact_id'] in records):
            raise ValueError('Event assertion has unknown or duplicate fact identity')
        fact=facts[record['fact_id']]
        selected=[p['source_id'] for p in fact.original_fact['provenance']]
        expected=record['selected_source_ids']
        adopted=(packet.extraction_metadata.get('structured_extraction_contract',{}).get(
            'primary_reference_application')=='model-selected-primary/1')
        if contract['version']==STRUCTURED_TASK_VERSION and adopted and record['primary_source_id'] is not None:
            primary=record['primary_source_id']
            expected=[primary]+[identity for identity in expected if identity!=primary]
        if expected!=selected or (
                record['primary_source_id'] is not None and record['primary_source_id'] not in selected):
            raise ValueError('Primary source proposal must retain original ordered citations')
        records[record['fact_id']]=record
    return records


def source_annotations(packet,item,claim,result,anchor,main_result=None):
    """Support comes from the verifier; a model-selected anchor stays a proposal."""
    dimensions={key:claim.get(key) for key in ('category','concept','experiencer','temporality',
        'event_time','action_type','action_state','completion_scope','polarity')}
    identity={'patient_id':packet.patient_id,'source_id':packet.source.document_id,
              'encounter_id':packet.case_id,**dimensions}
    refs=[];seen=set()
    for scope,proof in [('full_assertion',result),('main_assertion',main_result)]:
        if not proof or proof['status']!='SUPPORTED_BY_SOURCE':
            continue
        for span in proof.get('supporting_spans',[]):
            start,end,quote=span['start'],span['end'],span['quote']
            if not (0<=start<end<=len(packet.source.text) and packet.source.text[start:end]==quote):
                raise ValueError('Semantic support span does not match immutable source')
            key=(start,end,scope)
            if key in seen:
                continue
            seen.add(key)
            refs.append({'source_id':packet.source.document_id,'source_sha256':packet.source.sha256,
                'start':start,'end':end,'quote':quote,'support_scope':scope,
                'original_evidence_ids':[e.evidence_id for e in packet.evidence
                    if e.evidence_id in item.evidence_ids and e.start<end and start<e.end]})
    refs.sort(key=lambda r:(r['start'],r['end'],r['support_scope']))
    primary=next((p for p in item.original_fact['provenance']
                  if p['source_id']==anchor['primary_source_id']),None)
    return {'event_identity':{'version':'clinical-event-identity/1','proposal':identity,
                'identity':digest(identity),'deduplication_permitted':False},
            'primary_reference_proposal':{**anchor,'status':'PROPOSED_ANCHOR_NOT_SOURCE_PROOF',
                'span':primary,'original_reference_order_preserved':True},
            'semantic_support_refs':refs,
            'semantic_support_refs_version':'source-verified-support-refs/1'}
