"""Supplemental source review; preserve every original critical-fields-9 score.

Common quantitative fields use the unchanged legacy field projection. Newly
introduced metadata is a separate dimension. No gold enters model inference.
"""
import argparse
import json
import re
from pathlib import Path
from collections import Counter
from clinical_intelligence.domain import DocumentExtraction
from clinical_intelligence.reconcile import reconcile
from luna_experiment import dump, digest, summarize

VERSION='semantic-source-review-1'
HISTORY=r'\b(?:intake|prior|previous|historical)\b.{0,35}\bscore\b'


def historical(claim):
    return claim.get('kind')=='assessment' and (claim.get('source_role')=='historical_mention' or
        re.search(HISTORY,claim.get('statement',''),re.I) and
        any(re.search(HISTORY,p['quote'],re.I) for p in claim.get('passages',[])))


def supplement(row, result):
    raw=result.get('extraction') or {};claims=raw.get('claims',[])
    extras=[];reviewed=[];history_errors=[]
    for mismatch in result['score']['mismatches']:
        if mismatch['field']=='extra_claim' and historical(mismatch['actual']):
            extras.append(dict(category='source-supported historical mention outside prior measurement granularity',claim=mismatch['actual']))
        else:reviewed.append(mismatch)
    for claim in claims:
        if historical(claim):
            if claim.get('assessment_date') is not None:
                quote=' '.join(p['quote'] for p in claim['passages'])
                if not re.search(r'complet',quote,re.I):history_errors.append(dict(field='historical_completion_date',claim_id=claim['claim_id']))
            if (claim.get('recorded_at') or '').endswith('T00:00:00') or (claim.get('recorded_at') or '').endswith('T00:00'):
                if not any('00:00' in p['quote'] for p in claim['passages']):history_errors.append(dict(field='invented_midnight',claim_id=claim['claim_id']))
    constraints=[]
    for target in row.get('semantic_constraints',[]):
        if 'historical_score' in target:
            matched=[c for c in claims if historical(c) and c.get('score')==target['historical_score']]
            okay=any(c.get('source_role')=='historical_mention' and c.get('assessment_date')==target['completion_date'] and c.get('reference_date')==target['reference_date'] for c in matched)
        else:
            matched=[c for c in claims if c['kind']=='service' and c.get('encounter_ref')==target['encounter']]
            okay=any(all((c.get('source') or {}).get(k if k!='transmission' else 'transmission_status')==v
                if k in {'transmission','current_signed','original_signed','content_kind'} else c.get(k)==v for k,v in target.items() if k!='encounter') for c in matched)
        new_metadata=any(k in target for k in ('historical_score','transmission','current_signed','original_signed','content_kind'))
        available=not new_metadata or bool(result.get('configuration',{}).get('semantic_contract'))
        constraints.append(dict(target=target,available=available,correct=okay if available else None))
    abstraction=reconcile([DocumentExtraction.model_validate(raw)]) if raw else None
    return dict(historical_strict=result['score'],common_field_projection='unchanged critical-fields-9 legacy fields for A and B',
        supplemental_version=VERSION,reviewed_correct=bool(raw) and not reviewed and not history_errors,
        remaining_mismatches=reviewed,extra_claim_review=extras,historical_role_errors=history_errors,new_metadata_constraints=constraints,
        events=[dict(encounter=e.encounter_ref,minutes=e.minute_options,countable=e.countable,lower=e.minutes_lower,upper=e.minutes_upper,decisions=[d.model_dump(mode='json') for d in e.decisions],conflicts=[c.model_dump(mode='json') for c in e.conflicts]) for e in abstraction.events] if abstraction else [])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--private',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Supplemental results are immutable')
    rows={r['id']:r for r in json.loads(args.private.read_text(encoding='utf-8'))};records=[];summary={}
    for path in sorted(args.run.glob('*/repeat-*/*/result.json')):
        result=json.loads(path.read_text(encoding='utf-8'));review=supplement(rows[result['sample_id']],result)
        records.append(dict(candidate=result['candidate'],repeat=result['repeat'],sample_id=result['sample_id'],source=result['source'],path=str(path),review=review))
        bucket=summary.setdefault(result['candidate']+'/'+result['source'],Counter())
        bucket.update(documents=1,strict_correct=int(result['score']['document_correct']),reviewed_correct=int(review['reviewed_correct']),history_errors=len(review['historical_role_errors']),supported_history_extras=len(review['extra_claim_review']),new_constraints=len(review['new_metadata_constraints']),new_constraints_correct=sum(c['correct'] is True for c in review['new_metadata_constraints']),new_constraints_unobserved=sum(not c['available'] for c in review['new_metadata_constraints']),calls=result['cli_invocations'])
    dump(args.output,dict(version=VERSION,labels_sha256=digest(list(rows.values())),summary=summary,records=records,scope='AI-assisted supplemental review; historical strict scores unchanged; metadata denominator separate'))
    print(json.dumps(summary,indent=2))
