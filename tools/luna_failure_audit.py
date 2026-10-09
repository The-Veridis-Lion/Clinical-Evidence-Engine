"""Build a restricted, traceable audit from immutable historical artifacts (zero calls)."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from time import perf_counter
from clinical_intelligence.domain import RegisteredDocument
from clinical_intelligence.provider import CodexCLIProvider, ProviderConfig
from clinical_intelligence.luna_candidates import CandidateExtractor
from luna_experiment import score, dump, digest, code_identity


def collect(history, runs, rows, candidates):
    by_id={r['id']:r for r in rows};records=[]
    for name in runs:
        folder=history/'artifacts/luna-20261008'/name
        paths=list(folder.glob('analysis-critical-fields-9-replay.json')) or list(folder.glob('analysis-critical-fields-9.json'))
        if not paths:
            manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            paths=list(folder.glob(f"analysis-{manifest['scorer']}-replay.json")) or list(folder.glob(f"analysis-{manifest['scorer']}.json"))
        if not paths:raise FileNotFoundError(f'Historical analysis missing: {folder}')
        data=json.loads(paths[0].read_text(encoding='utf-8'))
        for result in data['results']:
            if result['sample_id'] not in by_id or result['candidate'] not in candidates or result['score']['document_correct']:continue
            row=by_id[result['sample_id']]
            directory=folder/result['candidate']/f"repeat-{result['repeat']:02d}"/result['sample_id']
            locations=list(directory.glob('attempt-*/call-*'))
            if not locations:
                locations=[d for d in folder.glob('provider-*/call-*') if (d/'prompt.txt').exists()
                    and row['text'].splitlines()[0] in (d/'prompt.txt').read_text(encoding='utf-8').split('SOURCE DOCUMENT:\n')[-1]]
            provider=object.__new__(CodexCLIProvider);provider.config=ProviderConfig();provider.cli_version='historical-replay';provider.reset_usage()
            config=result.get('configuration')
            if config is None:
                manifest=json.loads((folder/'manifest.json').read_text())
                config=manifest['candidates'][result['candidate']]
            extractor=CandidateExtractor(provider,config)
            document=RegisteredDocument(document_id=hashlib.sha256(row['text'].encode()).hexdigest(),fingerprint=digest(row['text']),source_names=[row['id']],text=row['text'])
            calls=[];merged=None
            for path in sorted(locations):
                missing=[str(path/f) for f in ['prompt.txt','schema.json','answer.json','request.json'] if not (path/f).exists()]
                if missing:
                    calls.append(dict(path=str(path),missing=missing,earliest_stage='unconfirmed'));continue
                prompt=(path/'prompt.txt').read_text(encoding='utf-8')
                answer=json.loads((path/'answer.json').read_text(encoding='utf-8'))
                stage='repair' if 'Validation failed.' in prompt else 'observations' if 'ONLY these kinds' in prompt else 'extraction'
                call=dict(path=str(path),stage=stage,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),schema=json.loads((path/'schema.json').read_text()),raw=answer,request=json.loads((path/'request.json').read_text()))
                if stage=='observations' and merged is not None:
                    merged['extractions']=[r for r in merged['extractions'] if r['kind']!='observation']+answer['extractions']
                else:merged=copy.deepcopy(answer)
                try:
                    extracted=extractor.from_result(document,extractor.convert(document,copy.deepcopy(merged)),perf_counter())
                    call['validation']='accepted';call['score']=score(row,extracted);call['adapter_result']=extracted.model_dump(mode='json')
                except Exception as error:call['validation']='failed';call['first_error']=str(error)
                calls.append(call)
            records.append(dict(run=name,candidate=result['candidate'],repeat=result['repeat'],sample_id=result['sample_id'],scorer=data['scorer'],analysis_path=str(paths[0]),source=row['text'],gold=row,result=result,calls=calls))
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history-root',type=Path,required=True);parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--runs',nargs='+',required=True);parser.add_argument('--candidates',nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Audit output is immutable; choose a fresh path')
    rows=json.loads(args.private.read_text(encoding='utf-8'))
    records=collect(args.history_root,args.runs,rows,args.candidates)
    dump(args.output,dict(kind='offline historical replay, no inference',code=code_identity(),records=records,annotation_status='Requires explicitly labelled AI-assisted or human source review'))
    print(json.dumps(dict(failures=len(records),calls=sum(len(r['calls']) for r in records),new_model_calls=0)))
