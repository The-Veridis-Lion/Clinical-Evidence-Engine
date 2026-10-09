"""Offline score a deployed SQLite database with the frozen experiment evaluator.

No inference or source/gold is sent to a model. Use the reviewed private file only
for authorized original-material databases; write detailed output under artifacts.
"""
import argparse
import json
import hashlib
from pathlib import Path
from clinical_intelligence.storage import SQLiteStore
from luna_experiment import ROOT, datasets, score, summarize, downstream, dump, digest, SCORER_VERSION
from luna_quality import independent_scores


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--run',required=True)
    parser.add_argument('--splits',nargs='+',default=['public'])
    parser.add_argument('--private')
    args=parser.parse_args()
    run=ROOT/'artifacts/luna-20261008'/args.run
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    rows=datasets(args.splits,args.private)
    records=[]
    with SQLiteStore(args.db) as store:
        documents=store.documents()
        for row in rows:
            matches=[d for d in documents if d.declared_id==row['declared_id']]
            if len(matches)!=1:
                raise ValueError(f"Expected exactly one persisted document for {row['id']}")
            document=matches[0]
            extraction=store.extraction(document.document_id,document.extraction_key) if document.extraction_key else None
            usage=extraction.usage.model_dump(mode='json') if extraction else {}
            records.append(dict(candidate='deployed_best',repeat=1,sample_id=row['id'],group=row['group'],source=row['source'],
                validation='accepted' if extraction else 'failed',extraction=extraction.model_dump(mode='json') if extraction else None,
                usage=usage,seconds=usage.get('latency_seconds',0),cli_invocations=usage.get('model_calls',0),score=score(row,extraction)))
    output=dict(scorer=SCORER_VERSION,run=args.run,replay_new_model_calls=0,kind='deployed SQLite verification',
        evaluation_dataset_sha256=digest(rows),summary=summarize(records),results=records,downstream=downstream(rows,records))
    output['evaluation_code']=manifest['code']
    output['auxiliary_labels_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [ROOT/'tests/fixtures/luna/query_oracles.json',ROOT/'artifacts/luna-private/query_oracles.json',ROOT/'artifacts/luna-private/clinical_supplement.json'] if p.exists()}
    output['evaluation_sha256']=digest({k:output[k] for k in ['scorer','evaluation_dataset_sha256','evaluation_code','auxiliary_labels_sha256']})
    output=independent_scores(ROOT,rows,output)
    dump(run/'analysis-critical-fields-9.json',output)
    dump(run/f"analysis-critical-fields-9-{output['evaluation_sha256'][:20]}.json",output)
    print(json.dumps(dict(summary=output['summary'],numerical_query_correct=sum(x['correct'] for x in output['independent_query_scores']),
        numerical_query_cases=len(output['independent_query_scores']),clinical_query_correct=sum(x['correct'] for x in output['independent_clinical_query_scores']),
        clinical_query_cases=len(output['independent_clinical_query_scores'])),indent=2))
