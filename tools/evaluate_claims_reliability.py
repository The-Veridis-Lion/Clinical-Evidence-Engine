"""Freeze/predict/evaluate a versioned synthetic suite without holdout tuning.

Expectations are read only by freeze (byte hashes) and evaluate (constraints).
Prediction uses inputs only. AI-authored constraints are not human clinical gold.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from clinical_intelligence.claims_review.contracts import CaseInput, ReviewPacket
from clinical_intelligence.claims_review.review import run_review
from audit_claims_packet import audit

VERSION='claims-reliability-evaluation/1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def now():return datetime.now(timezone.utc).isoformat()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['freeze','predict','evaluate'])
    p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ledger',type=Path);p.add_argument('--traces',type=Path)
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    if a.phase=='freeze':
        if (a.output/'freeze.json').exists():raise ValueError('Use a new result directory')
        files=[*sorted((root/'src').rglob('*.py')),*sorted((root/'src').rglob('*.json')),Path(__file__).resolve(),root/'tools/audit_claims_packet.py']
        state=dict(version=VERSION,created_at=now(),commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                   runtime={str(f.relative_to(root)):sha(f) for f in files},
                   inputs={f.name:sha(f) for f in sorted((a.suite/'inputs').glob('*.json'))},
                   expected_sha256=sha(a.suite/'expected.json'),
                   method='AI-assisted fact-first synthetic constraints; engineer authored inputs/constraints; model sees inputs only. Not human gold or author-blind evaluation.')
        save(a.output/'freeze.json',state);print('Frozen');return
    freeze=json.loads((a.output/'freeze.json').read_text())
    assert all(sha(root/f)==h for f,h in freeze['runtime'].items()),'Frozen runtime changed'
    assert all(sha(a.suite/'inputs'/f)==h for f,h in freeze['inputs'].items()),'Frozen inputs changed'
    assert sha(a.suite/'expected.json')==freeze['expected_sha256'],'Frozen constraints changed'
    if a.phase=='predict':
        if not a.ledger or not a.traces:raise ValueError('Explicit original persistent ledger and traces required')
        if (a.output/'prediction-seal.json').exists():raise ValueError('Predictions already sealed; no selective reruns')
        results=[]
        for filename in freeze['inputs']:
            path=a.suite/'inputs'/filename;out=a.output/'predictions'/filename
            if out.exists():raise ValueError('Never overwrite a prediction')
            case=CaseInput.model_validate_json(path.read_bytes())
            # Eligibility is runtime preparation metadata, never expected labels.
            from clinical_intelligence.claims_review.prepare import prepare_case
            from clinical_intelligence.claims_review.review import load_policy
            live=any(s['source_kind']=='synthetic_note' for s in prepare_case(case,load_policy(),input_label=str(path))['source_candidates'])
            before=len(json.loads(a.ledger.read_text())['calls'])
            if live and before>=20:
                results.append(dict(case=filename,status='BUDGET_BLOCKED'));continue
            command=[sys.executable,'-m','clinical_intelligence.claims_review','run','--case',str(path),'--mode','live' if live else 'structured-only',
                     '--model','gpt-6-luna','--reasoning','high','--timeout','180','--ledger',str(a.ledger),'--trace-directory',str(a.traces),'--output',str(out)]
            from time import perf_counter
            started=perf_counter();r=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=430)
            after=len(json.loads(a.ledger.read_text())['calls'])
            results.append(dict(case=filename,exit_code=r.returncode,calls=after-before,call_numbers=list(range(before+1,after+1)),
                                seconds=perf_counter()-started,stderr=r.stderr,command=command,sha256=sha(out) if out.exists() else None))
            save(a.output/'progress.json',results);print(filename,r.returncode,after-before,flush=True)
        save(a.output/'prediction-seal.json',dict(sealed_at=now(),results=results,expected_values_read_by_predict=False,
             outputs={f.name:sha(f) for f in (a.output/'predictions').glob('*.json')},ledger_sha256=sha(a.ledger)))
        return
    seal=json.loads((a.output/'prediction-seal.json').read_text());assert all(sha(a.output/'predictions'/f)==h for f,h in seal['outputs'].items())
    # First semantic access by the evaluator, after every first-pass output sealed.
    save(a.output/'expected-open-event.json',{'opened_at':now(),'seal_sha256':sha(a.output/'prediction-seal.json')})
    expected=json.loads((a.suite/'expected.json').read_text());rows=[]
    for filename in freeze['inputs']:
        identifier=Path(filename).stem;e=expected['cases'][identifier];output=a.output/'predictions'/filename
        if not output.exists():rows.append({'case_id':identifier,'execution_failed':True});continue
        data=json.loads(output.read_text())
        if 'facts' not in data:rows.append({'case_id':identifier,'execution_failed':True,'output':data});continue
        packet=ReviewPacket.model_validate_json(output.read_bytes());case=CaseInput.model_validate_json((a.suite/'inputs'/filename).read_bytes())
        actual={r.criterion_id:r.status for r in packet.criteria}
        observed=[]
        for constraint in e['facts']:
            family=[f for f in packet.facts if f.source_id==constraint['source_id'] and f.kind==constraint['kind']]
            for field,value in constraint['fields'].items():
                values=[f.model_dump(mode='json')[field] for f in family]
                observed.append(dict(source_id=constraint['source_id'],kind=constraint['kind'],field=field,expected=value,actual=values,
                                     correct=value in values,false_certainty=any(v is not None and v!=value for v in values),
                                     unnecessary_unknown=value is not None and (not values or all(v is None for v in values))))
        events=[]
        for c in e.get('events',[]):
            event=next((g for g in packet.timeline if g['event_key']==c['event_key']),None)
            events.append({'expected':c,'actual':event,'passed':bool(event and all(event[k]==v for k,v in c.items()))})
        binding=audit(case,packet)
        rows.append(dict(case_id=identifier,expected=e['criteria'],actual=actual,criterion_matches=sum(actual[k]==v for k,v in e['criteria'].items()),
                         criterion_total=len(e['criteria']),fields=observed,events=events,binding_audit=binding,execution_failed=packet.execution['execution_failed'],
                         usage=packet.execution['usage'],note_sources=packet.execution['note_sources'],
                         complete=all(actual[k]==v for k,v in e['criteria'].items()) and all(x['correct'] and not x['false_certainty'] for x in observed) and all(x['passed'] for x in events) and binding['passed'] and not packet.execution['execution_failed']))
    fields=[f for r in rows for f in r.get('fields',[])]
    matched=sum(f['correct'] for f in fields)
    known=[f for f in fields if f['expected'] is not None]
    tp=sum(f['correct'] for f in known);fp=sum(sum(v is not None and v!=f['expected'] for v in f['actual']) for f in fields)
    result=dict(version=VERSION,method=freeze['method'],cases=rows,cases_total=len(rows),complete=sum(r.get('complete',False) for r in rows),
                criterion_matches=sum(r.get('criterion_matches',0) for r in rows),criterion_total=sum(r.get('criterion_total',0) for r in rows),
                labelled_field_matches=matched,labelled_field_total=len(fields),false_certain_fields=sum(f['false_certainty'] for f in fields),
                unnecessary_unknown=sum(f['unnecessary_unknown'] for f in fields),
                constraint_projection_precision={'numerator':tp,'denominator':tp+fp},constraint_projection_recall={'numerator':tp,'denominator':len(known)},
                projection_limit='Selected independently specified known field constraints only; not exhaustive clinical fact precision/recall. Null expectations scored separately.',
                semantic_citation_precision=None,human_review_completed=False,clinical_expert_review_completed=False)
    save(a.output/'evaluation.json',result);print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))


if __name__=='__main__':main()
