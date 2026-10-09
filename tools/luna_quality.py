"""Offline independent numerical oracles and source-reviewed clinical coverage.

These labels never enter inference. Partial corpus groups are diagnostic only.
"""
import json
from pathlib import Path


def independent_scores(root, rows, output):
    from luna_experiment import field_equal
    manual=json.loads((root/'tests/fixtures/luna/query_oracles.json').read_text(encoding='utf-8'))['samples']
    manual.update({
        'robust-1':dict(sessions=[0,1],days=[0,1],minutes=[0,20],minute_alternatives=[0,20]),
        'robust-2':dict(sessions=[0,1],days=[0,1],minutes=[0,35],minute_alternatives=[0,35]),
        'robust-3':dict(sessions=[1,1],days=[1,1],minutes=[40,40],minute_alternatives=[40]),
        'robust-4':dict(sessions=[0,1],days=[0,1],minutes=[0,20],minute_alternatives=[0,20])})
    manual.update({f'robust-{i}':dict(sessions=[0,0],days=[0,0],minutes=[0,0],minute_alternatives=[0]) for i in range(5,9)})
    expected_ids={g:{r['id'] for r in rows if r['group']==g} for g in {r['group'] for r in rows}}
    private_path=root/'artifacts/luna-private/query_oracles.json'
    private=json.loads(private_path.read_text(encoding='utf-8')) if private_path.exists() else {}
    numerical=[]
    for item in output['downstream']:
        ids=expected_ids[item['group']]
        truth=None
        if len(ids)==1 and next(iter(ids)) in manual:
            truth=manual[next(iter(ids))]
        elif item['group']=='DEMO-CEDAR' and len(ids)==7:
            truth=dict(sessions=[2,2],days=[2,2],minutes=[108,120],minute_alternatives=[108,120])
        elif item['group']=='DEMO-JUNIPER':
            truth=dict(sessions=[1,1],days=[1,1],minutes=[23,23],minute_alternatives=[23])
        elif item['group'] in private and ids == set(private[item['group']]['sample_ids']):
            truth=private[item['group']].get('utilization')
        if truth is None:continue
        answer=item.get('answer') or {}
        totals=answer.get('result',{}).get('totals')
        equal=bool(totals) and all([totals[key]['lower'],totals[key]['upper']]==truth[name]
            for name,key in [('sessions','sessions'),('days','distinct_service_days'),('minutes','minutes')]) and totals['minute_alternatives']==truth['minute_alternatives']
        expected_answerable=truth['minutes'][1] is not None
        unknown=not totals or totals['minutes']['upper'] is None
        zero=bool(totals) and totals['minutes']['value']==0 and truth['minutes'][1]!=0
        false_definite=bool(totals) and truth['minutes'][0]!=truth['minutes'][1] and totals['minutes']['value'] is not None
        complete=answer.get('provenance_completeness')=='complete'
        source_errors=any(r['candidate']==item['candidate'] and r['repeat']==item['repeat'] and r['group']==item['group'] and not r['score']['document_correct'] for r in output['results'])
        numerical.append(dict(candidate=item['candidate'],repeat=item['repeat'],group=item['group'],expected=truth,
            actual=totals,correct=equal,unnecessary_unknown=expected_answerable and unknown,misleading_zero=zero,false_definite=false_definite,
            provenance_complete=complete,wrong_answer_marked_complete=complete and not equal,source_errors_marked_complete=complete and source_errors))
    output['independent_query_scores']=numerical
    clinical_queries=[]
    for item in output['downstream']:
        progress=item.get('clinical_progress') or {}
        truth=None
        label=private.get(item['group'], {})
        if set(label.get('sample_ids',[])) == expected_ids[item['group']] and label.get('assessments'):
            truth=[(a['date'],a['scores']) for a in label['assessments']]
            actual=[(str(a['assessment_date']) if a['assessment_date'] is not None else None,a['score_options']) for a in progress.get('assessments',[]) if a['instrument'].casefold()==label['instrument'].casefold()]
        elif item['group']=='robust-patient-6':
            truth=[(None,[11])]
            actual=[(a['assessment_date'],a['score_options']) for a in progress.get('undated_assessments',[])]
        elif item['group']=='robust-patient-7':
            truth=[('2026-08-08',[])]
            actual=[(str(a['assessment_date']) if a['assessment_date'] is not None else None,a['score_options']) for a in progress.get('assessments',[])]
        elif item['group']=='robust-patient-5':
            truth=[('safety','absent',None),('symptom','present',None)]
            actual=sorted((o['category'],o['polarity'],o['observation_date']) for o in progress.get('undated_observations',[]))
        if truth is not None:
            clinical_queries.append(dict(candidate=item['candidate'],repeat=item['repeat'],group=item['group'],
                expected=truth,actual=actual,correct=actual==truth))
    output['independent_clinical_query_scores']=clinical_queries
    supplement=root/'artifacts/luna-private/clinical_supplement.json'
    if supplement.exists():
        labels=json.loads(supplement.read_text(encoding='utf-8'))
        clinical=[]
        for record in output['results']:
            targets=labels['facts'].get(record['sample_id'],[])
            if not targets:continue
            claims=(record.get('extraction') or {}).get('claims',[])
            outcomes=[]
            for target in targets:
                matches=[]
                for claim in claims:
                    statement=claim.get('statement','').casefold()
                    if claim.get('kind')=='observation' and any(word.casefold() in statement for word in target['keywords_any']):
                        matches.append(claim)
                fields=dict(observation_date=target['date'],category=target['category'],polarity=target['polarity'],temporality=target['temporality'])
                exact=any(all(c.get(k) in (v if isinstance(v,list) else [v]) for k,v in fields.items()) and all(field_equal(target[k],c.get(k),k) for k in ['reporter','experiencer']) for c in matches)
                outcomes.append(dict(target=target,covered=exact,mention_present=bool(matches)))
            clinical.append(dict(candidate=record['candidate'],repeat=record['repeat'],sample_id=record['sample_id'],
                required=len(outcomes),covered=sum(x['covered'] for x in outcomes),outcomes=outcomes))
        output['clinical_coverage_scope']=labels['scope']
        output['clinical_coverage']=clinical
    return output
