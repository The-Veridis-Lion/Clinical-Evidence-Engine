"""Freeze selected candidates before the sealed evaluation; no inference."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
from luna_experiment import code_identity,CANDIDATES,digest,datasets,dump

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates',nargs='+',required=True,choices=CANDIDATES)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    target=Path(args.output)
    if target.exists():raise ValueError('Freeze files are immutable; use a new filename')
    dump(target,dict(created=datetime.now(timezone.utc).isoformat(),code=code_identity(),
        candidates={c:CANDIDATES[c] for c in args.candidates},sealed_dataset_sha256=digest(datasets(['sealed']))))
    print(str(target.resolve()))
