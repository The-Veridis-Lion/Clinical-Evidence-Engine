import argparse
from pathlib import Path
from .runtime import initialize,execute,integrity
from .evaluation import evaluate,select
from .reporting import audit_queue,report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['init','compare','evaluate-comparison','select','final','evaluate-final','audit-comparison','audit-final','report','integrity'])
    p.add_argument('--approach',choices=['direct','indexed_two_stage'])
    p.add_argument('--limit',type=int)
    p.add_argument('--root',type=Path,default=Path('artifacts/luna-round2-v1'))
    a=p.parse_args();repo=Path.cwd();root=a.root.resolve()
    if a.action=='init':initialize(repo,root)
    elif a.action=='compare':
        if not a.approach:p.error('--approach required')
        execute(repo,root,'comparison',a.approach,limit=a.limit)
    elif a.action=='final':
        from ..simsum_comparison.execution import read
        execute(repo,root,'final',read(root/'winner-freeze.json')['winner'],limit=a.limit)
    elif a.action.startswith('evaluate-'):evaluate(repo,root,a.action.split('-')[1])
    elif a.action=='select':select(root)
    elif a.action.startswith('audit-'):audit_queue(repo,root,a.action.split('-')[1])
    elif a.action=='report':report(repo,root)
    else:
        m=integrity(repo,root);print({'protected_files_verified':len(m['protected_files'])})

if __name__=='__main__':main()
