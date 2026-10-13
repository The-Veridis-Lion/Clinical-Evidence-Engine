import argparse
import json
from pathlib import Path

from .datasets import freeze_augmented,freeze_aci,load_augmented_partition
from .execution import execute,freeze_run,rescore_cache


def main():
    ap=argparse.ArgumentParser(description='Frozen Clinical Evidence Copilot evaluation')
    sub=ap.add_subparsers(dest='command',required=True)
    freeze=sub.add_parser('freeze-augmented')
    freeze.add_argument('source'); freeze.add_argument('--output',required=True)
    freeze.add_argument('--used-id',action='append',default=[])
    aci=sub.add_parser('freeze-aci'); aci.add_argument('folder'); aci.add_argument('--output',required=True)
    batch=sub.add_parser('run-development')
    batch.add_argument('--source',required=True); batch.add_argument('--manifest',required=True)
    batch.add_argument('--root',required=True)
    batch.add_argument('--slots',default='../artifacts/clinical-luna-shared.sqlite3')
    batch.add_argument('--without-review',action='store_true')
    rescore=sub.add_parser('rescore-cache')
    rescore.add_argument('--source',required=True); rescore.add_argument('--manifest',required=True)
    rescore.add_argument('--root',required=True); rescore.add_argument('--cache-root',required=True)
    rescore.add_argument('--without-review',action='store_true')
    rescore.add_argument('--prior-review-root')
    candidate_parser=sub.add_parser('freeze-candidate')
    candidate_parser.add_argument('--manifest',required=True)
    candidate_parser.add_argument('--development-root',required=True)
    candidate_parser.add_argument('--output',required=True)
    final=sub.add_parser('run-final')
    final.add_argument('--source',required=True); final.add_argument('--manifest',required=True)
    final.add_argument('--candidate',required=True); final.add_argument('--root',required=True)
    final.add_argument('--access-ledger',default='../artifacts/copilot-final-access.sqlite3')
    final.add_argument('--slots',default='../artifacts/clinical-luna-shared.sqlite3')
    audit=sub.add_parser('audit-saved-review')
    audit.add_argument('root'); audit.add_argument('--output',required=True)
    matcher_audit=sub.add_parser('audit-saved-matching')
    matcher_audit.add_argument('roots',nargs='+'); matcher_audit.add_argument('--output',required=True)
    aci_run=sub.add_parser('run-aci-development')
    aci_run.add_argument('--folder',required=True);aci_run.add_argument('--manifest',required=True)
    aci_run.add_argument('--root',required=True);aci_run.add_argument('--slots',default='../artifacts/clinical-luna-shared.sqlite3')
    aci_run.add_argument('--without-review',action='store_true')
    args=ap.parse_args()
    if args.command=='freeze-augmented':
        result=freeze_augmented(args.source,args.output,used_ids=args.used_id)
        print(json.dumps({'manifest_hash':result['manifest_hash'],'development':len(result['development']),'final':len(result['final'])}))
    elif args.command=='freeze-aci':
        result=freeze_aci(args.folder,args.output)
        print(json.dumps({'manifest_hash':result['manifest_hash']}))
    elif args.command=='freeze-candidate':
        from .candidate import freeze_candidate
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        result=freeze_candidate(manifest,args.development_root,args.output)
        print(json.dumps({'candidate_hash':result['candidate_hash']}))
    elif args.command=='run-aci-development':
        from .aci import run_aci_development
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        result=run_aci_development(args.folder,manifest,args.root,slots_path=args.slots,review=not args.without_review)
        print(json.dumps(result,indent=2))
    elif args.command=='audit-saved-review':
        from .audit import audit_saved_reviews
        result=audit_saved_reviews(args.root,args.output)
        print(json.dumps(result['summary'],indent=2))
    elif args.command=='audit-saved-matching':
        from .audit import audit_saved_matching
        result=audit_saved_matching(args.roots,args.output)
        print(json.dumps([dict(root=r['root'],summary=r['summary'],matcher_diagnostics=r['matcher_diagnostics'],
            errors=r['errors']) for r in result['runs']],indent=2))
    else:
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        candidate=None
        if args.command=='run-final':
            from .candidate import reserve_final
            candidate=json.loads(Path(args.candidate).read_text(encoding='utf-8'))
            reserve_final(candidate,manifest,args.access_ledger,args.root)
        records=list(load_augmented_partition(args.source,manifest,'final' if candidate else 'development',candidate=candidate))
        if candidate:
            result=execute(records,args.root,manifest,slots_path=args.slots)
            print(json.dumps(result,indent=2)); return
        result=rescore_cache(records,args.cache_root,args.root,manifest,review=not args.without_review,prior_review_root=args.prior_review_root) if args.command=='rescore-cache' else execute(records,args.root,manifest,slots_path=args.slots,review=not args.without_review)
        print(json.dumps(result,indent=2))


if __name__=='__main__': main()
