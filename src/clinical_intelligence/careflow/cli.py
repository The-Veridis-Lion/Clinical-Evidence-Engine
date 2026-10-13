"""Independent module entry point avoids shared CLI/packaging changes."""
import argparse
import json
from pathlib import Path
import sys

from .contracts import Case, EvidenceUpdate, Review
from .report import markdown
from .rules import manifests
from .service import CareFlow


def load(path, cls):
    return cls.model_validate_json(Path(path).read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m clinical_intelligence.careflow')
    parser.add_argument('--db', default='artifacts/careflow.sqlite')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('create'); p.add_argument('--case', required=True)
    p = sub.add_parser('add-evidence'); p.add_argument('--case-id', required=True); p.add_argument('--input', required=True)
    p = sub.add_parser('review'); p.add_argument('--case-id', required=True); p.add_argument('--input', required=True)
    for command in ['packet', 'report', 'audit', 'reviews', 'model-calls', 'review-input']:
        p = sub.add_parser(command); p.add_argument('--case-id', required=True)
        if command in {'packet', 'report', 'review-input'}:
            p.add_argument('--revision', type=int)
    sub.add_parser('rules')
    p = sub.add_parser('demo'); p.add_argument('--output', default='artifacts/careflow-demo')
    p = sub.add_parser('serve'); p.add_argument('--host', default='127.0.0.1'); p.add_argument('--port', type=int, default=8765)
    p = sub.add_parser('retrieve'); p.add_argument('--archive', required=True); p.add_argument('--case', required=True)
    p.add_argument('--received-at', required=True); p.add_argument('--output', required=True)
    p = sub.add_parser('synthea-demo'); p.add_argument('--archive', required=True); p.add_argument('--split', required=True)
    p.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'serve':
            from .api import make_server
            server = make_server(args.db, args.host, args.port)
            print(f'CareFlow local API: http://{args.host}:{server.server_port}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        if args.command == 'demo':
            from .demo import run_demo
            result = run_demo(args.db, args.output)
        elif args.command == 'synthea-demo':
            from .demo import run_synthea_demo
            result = run_synthea_demo(args.db, args.output, args.archive, args.split)
        elif args.command == 'rules':
            result = manifests()
        elif args.command == 'retrieve':
            from datetime import date
            from .archive import retrieve_context, safe_index
            case = load(args.case, Case)
            result = retrieve_context(safe_index(args.archive), case.request, received_at=date.fromisoformat(args.received_at))
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        else:
            app = CareFlow(args.db)
            if args.command == 'create':
                result = app.create(load(args.case, Case))
            elif args.command == 'add-evidence':
                result = app.add_evidence(args.case_id, load(args.input, EvidenceUpdate))
            elif args.command == 'review':
                result = app.review(args.case_id, load(args.input, Review))
            elif args.command == 'packet':
                result = app.packet(args.case_id, args.revision)
            elif args.command == 'report':
                print(markdown(app.packet(args.case_id, args.revision), app.reviews(args.case_id)))
                return 0
            elif args.command == 'audit':
                result = app.audit(args.case_id)
            elif args.command == 'reviews':
                result = app.reviews(args.case_id)
            elif args.command == 'model-calls':
                result = app.model_calls(args.case_id)
            else:
                result = {'packet': app.packet(args.case_id, args.revision), 'review_schema': Review.model_json_schema(),
                          'invocation': 'optional_external_reviewer', 'model_calls': 0}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
