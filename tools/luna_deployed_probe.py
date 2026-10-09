"""Run the actual deployed CLI with request logging and a fresh output namespace.

Only run_cli instrumentation is replaced. Extraction, SQLite, defaults, factories,
and CLI parameters use the production path. Sources/responses remain ignored.
"""
import argparse
import json
import os
import tempfile
from itertools import count
from threading import Lock
from clinical_intelligence import cli, provider
from luna_experiment import ROOT, RecordingProvider, code_identity, dump


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--input',required=True)
    parser.add_argument('--db',required=True)
    args=parser.parse_args()
    output=ROOT/'artifacts/luna-20261008'/args.run
    output.mkdir(parents=True,exist_ok=False)
    scratch=ROOT/'artifacts/luna-20261008/tmp';scratch.mkdir(parents=True,exist_ok=True)
    os.environ['TMP']=os.environ['TEMP']=str(scratch);tempfile.tempdir=str(scratch)
    sequence=count();lock=Lock()
    def recording(config):
        with lock:number=next(sequence)
        directory=output/f'provider-{number:03d}';directory.mkdir()
        return RecordingProvider(config,directory)
    provider.CodexCLIProvider=recording
    configuration=json.loads((ROOT/'src/clinical_intelligence/contracts/luna_best.json').read_text())
    dump(output/'manifest.json',dict(experiment=args.run,kind='deployment_smoke',code=code_identity(),
        candidates={'deployed_best':configuration},model='gpt-6-luna',backend='unavailable',
        application_cache='actual CLI behavior, reported in process.json',arguments=vars(args)))
    raise SystemExit(cli.main(['--db',args.db,'--output',str(output/'process.json'),
        'process','--input',args.input]))
