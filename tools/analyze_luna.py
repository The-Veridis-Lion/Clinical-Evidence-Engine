"""Offline rescore immutable extraction results; never executes inference."""
import argparse
import json
import hashlib
from pathlib import Path
from statistics import median
from clinical_intelligence.domain import DocumentExtraction, RegisteredDocument
from clinical_intelligence.extraction_validation import validate_source_contract
from luna_experiment import ROOT, datasets, score, summarize, downstream, dump, SCORER_VERSION, digest
from luna_quality import independent_scores


def analyze(run, private=None, revalidate=False):
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    args=manifest['arguments']
    rows=datasets(args['splits'],private or args.get('private'))
    retained={s['id'] for s in manifest['samples']}
    rows=[r for r in rows if r['id'] in retained]
    if args.get('samples'):rows=[r for r in rows if r['id'] in args['samples']]
    lookup={r['id']:r for r in rows}
    results=[]
    for path in sorted(run.glob('*/repeat-*/*/result.json')):
        result=json.loads(path.read_text(encoding='utf-8'))
        extraction=DocumentExtraction.model_validate(result['extraction']) if result['extraction'] else None
        if extraction and revalidate:
            source=lookup[result['sample_id']]
            document=RegisteredDocument(document_id=extraction.document_id,fingerprint='replay',source_names=[source['id']],text=source['text'])
            try:validate_source_contract(document,extraction)
            except ValueError as error:
                result['historical_validation']=result['validation'];result['revalidation_failure']=str(error)
                result['validation']='failed';result['raw_extraction']=result['extraction'];result['extraction']=None;extraction=None
        result['score']=score(lookup[result['sample_id']],extraction)
        results.append(result)
    output=dict(scorer=SCORER_VERSION,run=run.name,revalidation=revalidate,replay_new_model_calls=0,evaluation_dataset_sha256=digest(rows),
        runtime_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in list((ROOT/'src/clinical_intelligence').glob('*.py'))+[Path(__file__),ROOT/'tools/luna_quality.py',ROOT/'tools/luna_experiment.py']},
        summary=summarize(results),downstream=downstream(rows,results),results=results)
    output['auxiliary_labels_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [ROOT/'tests/fixtures/luna/query_oracles.json',ROOT/'artifacts/luna-private/query_oracles.json',ROOT/'artifacts/luna-private/clinical_supplement.json'] if p.exists()}
    output['evaluation_sha256']=digest({k:output[k] for k in ['scorer','revalidation','evaluation_dataset_sha256','runtime_sha256','auxiliary_labels_sha256']})
    for candidate in sorted({r['candidate'] for r in results}):
        values=[r['seconds'] for r in results if r['candidate']==candidate]
        output.setdefault('latency',{})[candidate]=dict(median=median(values),max=max(values),total=sum(values))
    return independent_scores(ROOT,rows,output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run');parser.add_argument('--private')
    parser.add_argument('--revalidate',action='store_true')
    args=parser.parse_args();run=ROOT/'artifacts/luna-20261008'/args.run
    output=analyze(run,args.private,args.revalidate)
    version=SCORER_VERSION+('-replay' if args.revalidate else '')
    dump(run/f'analysis-{version}.json',output)
    dump(run/f"analysis-{version}-{output['evaluation_sha256'][:20]}.json",output)
    print(json.dumps({k:{f:v[f] for f in ['documents','correct','accepted','calls','precision','recall']} for k,v in output['summary'].items()},indent=2))
