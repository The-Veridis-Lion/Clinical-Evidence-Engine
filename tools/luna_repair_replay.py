"""One real runtime repair of a saved proposal; not a new end-to-end extraction.

Inputs are original text, actual prompt/schema and raw responses, never gold.
All historical files stay immutable. Validation acceptance is not semantic proof.
"""
import argparse
import copy
import json
from pathlib import Path
from time import perf_counter
from clinical_intelligence.domain import RegisteredDocument
from clinical_intelligence.luna_candidates import CandidateExtractor
from clinical_intelligence.provider import ProviderConfig
from luna_experiment import RecordingProvider, code_identity, digest, dump


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--call',type=Path,required=True)
    p.add_argument('--observations',type=Path)
    p.add_argument('--configuration',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    text=a.source.read_text(encoding='utf-8')
    prompt=(a.call/'prompt.txt').read_text(encoding='utf-8')
    schema=json.loads((a.call/'schema.json').read_text(encoding='utf-8'))
    proposal=json.loads((a.call/'answer.json').read_text(encoding='utf-8'))
    if a.observations:
        observations=json.loads(a.observations.read_text(encoding='utf-8'))
        proposal['extractions']=[r for r in proposal['extractions'] if r['kind']!='observation']+observations['extractions']
    cfg=json.loads(a.configuration.read_text(encoding='utf-8'))
    provider=RecordingProvider(ProviderConfig(model='gpt-6-luna',reasoning_effort=cfg.get('reasoning','high')),a.output)
    e=CandidateExtractor(provider,cfg)
    doc=RegisteredDocument(document_id=digest(text),fingerprint=digest(text),source_names=[a.source.name],text=text)
    result=dict(scope='Saved extraction plus at most one real runtime repair; not independent extraction',code=code_identity(),
        inputs={k:str(v) for k,v in vars(a).items()},source_sha256=digest(text),proposal_sha256=digest(proposal),configuration=cfg,backend='unavailable')
    started=perf_counter()
    try:
        try:
            ext=e.from_result(doc,e.convert(doc,copy.deepcopy(proposal)),started)
            result['trigger']=None
        except (ValueError,KeyError) as error:
            result['trigger']=str(error)
            fixed=provider.structured_output(prompt+'\nValidation failed. Correct the complete proposal using SOURCE.\nERROR:\n'+str(error)+'\nPROPOSAL:\n'+json.dumps(proposal),schema,purpose='validation_repair')
            ext=e.from_result(doc,e.convert(doc,fixed),started)
        result.update(validation='accepted',extraction=ext.model_dump(mode='json'))
    except Exception as error:
        result.update(validation='failed',failure=str(error))
    result.update(usage=provider.usage(perf_counter()-started).model_dump(mode='json'),cli_invocations=provider.invocations)
    dump(a.output/'result.json',result)
    print(json.dumps({k:result.get(k) for k in ('validation','trigger','failure','cli_invocations')}))
    return 0 if result['validation']=='accepted' else 1


if __name__=='__main__':raise SystemExit(main())
