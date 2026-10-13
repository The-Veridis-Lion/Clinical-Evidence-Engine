"""Reproducible evaluation commands; no inference is implicit."""
import argparse
import json
from pathlib import Path

from .acceptance import evaluate_materials, freeze_materials, seal_candidate
from .corpus import freeze_corpus, load_acn, load_aci
from .reference_first import compare, score_original


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m clinical_intelligence.careflow.evaluation')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('freeze-corpus')
    p.add_argument('--dataset', choices=['acn', 'aci'], required=True)
    p.add_argument('--input', required=True); p.add_argument('--output', required=True)
    p.add_argument('--development-groups', type=int, required=True); p.add_argument('--holdout-groups', type=int, required=True)
    p.add_argument('--exposure-file')
    p = sub.add_parser('freeze-materials'); p.add_argument('--input', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('material-demo-freeze'); p.add_argument('--archive', required=True); p.add_argument('--split', required=True)
    p.add_argument('--output', required=True)
    p = sub.add_parser('run-materials'); p.add_argument('--frozen', required=True); p.add_argument('--output', required=True)
    p.add_argument('--partition', choices=['development', 'holdout'], required=True)
    p = sub.add_parser('seal-candidate'); p.add_argument('--frozen', required=True)
    p = sub.add_parser('compare'); p.add_argument('--references', required=True); p.add_argument('--predictions', required=True)
    p = sub.add_parser('freeze-reference-inventory'); p.add_argument('--source', required=True)
    p.add_argument('--frozen', required=True); p.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if args.command == 'freeze-corpus':
        exposed = json.loads(Path(args.exposure_file).read_text(encoding='utf-8')) if args.exposure_file else []
        docs = load_acn(args.input) if args.dataset == 'acn' else load_aci(args.input, cached_encounters=exposed)
        result = freeze_corpus(docs, args.output, development_groups=args.development_groups,
                               holdout_groups=args.holdout_groups, exposed_groups=exposed,
                               source_metadata={'input_sha256': __import__('hashlib').sha256(Path(args.input).read_bytes()).hexdigest(),
                                                'dataset': args.dataset})
    elif args.command == 'freeze-materials':
        rows = [json.loads(line) for line in Path(args.input).read_text(encoding='utf-8').splitlines()]
        result = freeze_materials(rows, args.output)
    elif args.command == 'material-demo-freeze':
        from .materials import freeze_original_material_demo
        result = freeze_original_material_demo(args.archive, args.split, args.output)
    elif args.command == 'run-materials':
        result = evaluate_materials(args.frozen, args.output, partition=args.partition)
    elif args.command == 'seal-candidate':
        result = seal_candidate(args.frozen)
    elif args.command == 'freeze-reference-inventory':
        from .references import freeze_acn_reference_inventory
        result = freeze_acn_reference_inventory(args.source, args.frozen, args.output)
    else:
        references = json.loads(Path(args.references).read_text(encoding='utf-8'))
        predictions = json.loads(Path(args.predictions).read_text(encoding='utf-8'))
        diff = compare(references, predictions)
        result = {'comparison': diff, 'original_metrics': score_original([diff])}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
