"""Offline uncertainty checks; original labels/scores remain immutable."""
import argparse
import json
from collections import Counter
from pathlib import Path
from luna_experiment import dump, digest, fact_view, field_equal

VERSION = 'uncertainty-checks-1'


def evaluate(row, result):
    raw = result.get('extraction')
    claims = fact_view(raw.get('claims', [])) if raw else []
    outcomes = []
    for check in row.get('uncertainty_checks', []):
        matched = [c for c in claims if all(c.get(k) == v for k,v in check['selector'].items())]
        actual = matched[0].get(check['field']) if len(matched) == 1 else None
        if check['selector'].get('kind') == 'patient':
            matched = [raw['patient']] if raw else []
            actual = raw['patient'].get(check['field']) if raw else None
        expected = check['value']
        correct = len(matched) == 1 and field_equal(expected, actual, check['field'])
        outcomes.append(dict(check=check, actual=actual, correct=correct,
            omission=not matched, false_certainty=bool(matched) and expected is None and actual is not None,
            unnecessary_abstention=bool(matched) and expected is not None and actual is None,
            wrong_known=bool(matched) and expected is not None and actual is not None and not correct))
    return outcomes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--private',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Results are immutable; use a fresh output path')
    rows={r['id']:r for r in json.loads(a.private.read_text(encoding='utf-8'))};records=[];summary={}
    for path in sorted(a.run.glob('*/repeat-*/*/result.json')):
        result=json.loads(path.read_text(encoding='utf-8'));outcomes=evaluate(rows[result['sample_id']], result)
        bucket=summary.setdefault(result['candidate'],Counter())
        bucket.update(documents=1,strict_correct=int(result['score']['document_correct']),validation_blocks=int(result['extraction'] is None),
            checked_fields=len(outcomes),correct_fields=sum(o['correct'] for o in outcomes),omissions=sum(o['omission'] for o in outcomes),
            false_certainty=sum(o['false_certainty'] for o in outcomes),unnecessary_abstention=sum(o['unnecessary_abstention'] for o in outcomes),wrong_known=sum(o['wrong_known'] for o in outcomes),calls=result['cli_invocations'])
        records.append(dict(candidate=result['candidate'],repeat=result['repeat'],sample_id=result['sample_id'],path=str(path),outcomes=outcomes))
    dump(a.output,dict(version=VERSION,labels_sha256=digest(list(rows.values())),summary=summary,records=records,
        scope='AI-assisted fact-first uncertainty annotations; original strict scores retained, no model judge'))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
