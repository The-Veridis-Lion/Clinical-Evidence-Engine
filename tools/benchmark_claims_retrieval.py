"""Fixed original-row oracle, separate from retrieval implementation/output."""
import argparse
import csv
import io
import json
import zipfile
from datetime import date
from pathlib import Path
from clinical_intelligence.claims_review.retrieval import retrieve, RetrievalQuery, sha
from clinical_intelligence.claims_review.contracts import CaseInput
from clinical_intelligence.claims_review.review import run_review


def expected_rows(archive, gold, task):
    # Known clinical row IDs were inspected/transcribed before runtime retrieval.
    with zipfile.ZipFile(archive) as z:
        tables = {name:list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8'),newline='')))
                  for name in ['observations.csv','conditions.csv','medications.csv','encounters.csv']}
    selected = [('observations.csv',i) for i in task['expected_hba1c_rows']]
    selected += [('conditions.csv',i) for i in gold['diabetes_condition_rows']]
    selected += [('medications.csv',i) for i in gold['metformin_rows']
                 if task['history_start'] <= tables['medications.csv'][i-1]['START'][:10] <= task['history_end']]
    links = {tables[t][i-1]['ENCOUNTER'] for t,i in selected}
    selected += [('encounters.csv',i) for i,row in enumerate(tables['encounters.csv'],1)
                 if row['PATIENT']==gold['patient_id'] and row['Id'] in links and
                 task['history_start']<=row['START'][:10]<=task['history_end']]
    assert all(tables[t][i-1]['PATIENT']==gold['patient_id'] for t,i in selected)
    return {f'SYNTHEA-{Path(t).stem.upper()}-{i}' for t,i in selected}


def benchmark(archive, query_path, gold_path, output):
    archive=Path(archive);gold=json.loads(Path(gold_path).read_text(encoding='utf-8'))
    if sha(archive.read_bytes()) != gold['archive_sha256']:
        raise ValueError('Dataset changed; frozen original-row oracle does not apply')
    base=json.loads(Path(query_path).read_text(encoding='utf-8'));results=[];output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    for task in gold['tasks']:
        body=json.loads(json.dumps(base));body['case_id']=task['id']
        body['review_context'].update(history_start=task['history_start'],history_end=task['history_end'])
        query=RetrievalQuery.model_validate_json(json.dumps(body))
        expected=expected_rows(archive,gold,task)  # established before running this task
        actual=retrieve(archive,query,snapshot_available_at=date(2026,10,9))
        ids=set(actual['matched_source_ids']);candidates=actual['prepared']['source_candidates']
        critical={f'SYNTHEA-OBSERVATIONS-{i}' for i in task['expected_hba1c_rows']}
        # Linkage remains unknown in original CSV; no source is promoted to a proved
        # independent test count merely from its row, date, or encounter.
        review=run_review(CaseInput.model_validate_json(json.dumps(actual['case'])))
        metrics={'task':task['id'],'expected_source_ids':sorted(expected),'actual_source_ids':sorted(ids),
                 'critical_recall_numerator':len(ids & critical),'critical_recall_denominator':len(critical),
                 'retrieval_misses':sorted(expected-ids),'retrieval_false_positives':sorted(ids-expected),
                 'wrong_patient_inclusions':sum(s['patient_id']!=gold['patient_id'] for s in candidates),
                 'source_availability_violations':sum(s['available_at'] is None or s['available_at']>base['review_context']['as_of'] for s in candidates),
                 'date_scope_violations':sum(s['record_type'] in {'observation','encounter','medication_order'} and s['event_date'] is not None and not task['history_start']<=s['event_date']<=task['history_end'] for s in candidates),
                 'duplicate_event_counting_errors':sum(e['counted_as_tests'] is not None for e in review.timeline),
                 'uncertain_event_groups':len(review.timeline),'excluded_rows':len(actual['excluded_sources']),
                 'associated_unverified_claim_rows':len(actual['linked_records']),'retrieval_latency_seconds':actual['latency_seconds'],
                 'review_status':review.status,'actual_provider_calls':0}
        (output/(task['id']+'.json')).write_text(json.dumps(actual,indent=2)+'\n',encoding='utf-8')
        results.append(metrics)
    summary={'version':'retrieval-benchmark/1','dataset_sha256':gold['archive_sha256'],'oracle_method':gold['method'],
             'human_reviewed':False,'evaluation_type':'original_archive_retrieval_development_not_independent_confirmation',
             'tasks':results,'critical_source_task_pairs_retrieved':sum(t['critical_recall_numerator'] for t in results),
             'critical_source_task_pairs_expected':sum(t['critical_recall_denominator'] for t in results),
             'unique_critical_original_rows':len(gold['hba1c_rows']),
             'correlation_note':'Overlapping windows for one patient; source-task pairs are not independent patients.',
             'passed':all(not t['retrieval_misses'] and not t['retrieval_false_positives'] and not t['wrong_patient_inclusions'] and not t['source_availability_violations'] and not t['date_scope_violations'] and not t['duplicate_event_counting_errors'] for t in results)}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--query',default='examples/claims_review/raw/target-query.json')
    p.add_argument('--gold',default='tests/fixtures/claims_review/retrieval_expected.json')
    p.add_argument('--output',default='artifacts/raw-source/benchmark')
    a=p.parse_args();s=benchmark(a.archive,a.query,a.gold,a.output)
    print(json.dumps({k:v for k,v in s.items() if k!='tasks'},indent=2))
    raise SystemExit(int(not s['passed']))
