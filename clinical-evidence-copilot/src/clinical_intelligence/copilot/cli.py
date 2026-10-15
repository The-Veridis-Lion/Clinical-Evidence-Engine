"""Independent CLI for the Copilot application."""
import argparse
import json
from pathlib import Path

from .demo import seed_demo
from .models import OmissionCorrectionRequest, ReviewRequest, Source
from .augmentation import correct_omission, complete_eligible_omissions
from .reviewer import review_task, validate_product_review_request
from .runtime import ProductLedger, create_from_bundle, extract_live, import_engine_cache, replay_product_response
from .service import compare_packets, review_packet
from .store import CaseStore
from .views import render_markdown


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def export(packet, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    # Each version has a unique export filename; a source cannot be overwritten.
    name = 'v' + str(packet.version)
    for suffix, content in [('.json', packet.model_dump_json(indent=2)), ('.md', render_markdown(packet))]:
        path = folder/(name+suffix)
        if path.exists() and path.read_text(encoding='utf-8') != content:
            raise ValueError('Export already exists with different contents: '+str(path))
        path.write_text(content, encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Clinical Evidence Copilot — source-linked SOAP and review')
    ap.add_argument('--db', default='artifacts/copilot/cases.sqlite3')
    sub = ap.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo', help='Seed two synthetic encounters, no model calls')
    demo.add_argument('--output', default='artifacts/copilot/demo')
    serve = sub.add_parser('serve', help='Start local evidence workspace')
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--live', action='store_true', help='Explicitly enable inherited model extraction')
    create = sub.add_parser('create', help='Import a source + extraction bundle')
    create.add_argument('bundle')
    reviewed=sub.add_parser('reviewed-input',help='Offline evaluation only: import retained source judgments without model dispatch')
    reviewed.add_argument('input')
    reviewed.add_argument('--offline-evaluation', action='store_true', required=True,
                          help='Explicit evaluation import, separate from the Luna product workflow')
    live = sub.add_parser('extract', help='Explicit opt-in model extraction, with durable accounting')
    live.add_argument('input')
    live.add_argument('--case-id', required=True)
    live.add_argument('--patient-id', required=True)
    live.add_argument('--document-id', help='Retain an upstream source identity; defaults to CASE_ID:source')
    live.add_argument('--kind', choices=['dialogue', 'note'], default='note')
    live.add_argument('--encounter-time')
    live.add_argument('--model', choices=['gpt-6-luna'], default='gpt-6-luna')
    live.add_argument('--request-id', default='first')
    live.add_argument('--semantics-version', choices=['clinical-fact-semantics/2'],
                      help='Typed frequency/event_time/duration representation for new sources; legacy wire schema remains available')
    live.add_argument('--task-version', choices=['clinical-event-assertions/1'],
                      help='Opt-in independent events, documentation statements and proposed primary reference; requires semantics/2')
    cached = sub.add_parser('import-cache', help='Read original dialogue Engine cache without inference')
    cached.add_argument('root')
    cached.add_argument('encounter_id')
    cached.add_argument('--patient-id', required=True)
    cached.add_argument('--case-id')
    replay = sub.add_parser('replay-response', help='Revalidate an immutable actual product response without inference')
    replay.add_argument('--source-packet', required=True)
    replay.add_argument('--raw-response', required=True)
    replay.add_argument('--product-ledger', required=True)
    replay.add_argument('--case-id', required=True)
    show = sub.add_parser('show')
    show.add_argument('case_id')
    show.add_argument('--version', type=int)
    show.add_argument('--format', choices=['json', 'markdown'], default='markdown')
    show.add_argument('--output')
    review = sub.add_parser('review', help='Apply an active human review as a new immutable version')
    review.add_argument('case_id')
    review.add_argument('request')
    typed_review=sub.add_parser('review-semantics',help='Audit a typed attribute/event correction as an immutable version')
    typed_review.add_argument('case_id')
    typed_review.add_argument('request')
    omission = sub.add_parser('correct-omission', help='Add a verified source-first omission as a new version')
    omission.add_argument('case_id')
    omission.add_argument('request')
    completion = sub.add_parser('complete-eligible', help='Complete only calibrated low-risk source omissions')
    completion.add_argument('case_id')
    task = sub.add_parser('review-task', help='Export a targeted reviewer task without model dispatch')
    task.add_argument('case_id')
    task.add_argument('--fact-id', action='append')
    compare = sub.add_parser('compare')
    compare.add_argument('before_case')
    compare.add_argument('after_case')
    sub.add_parser('list')
    history = sub.add_parser('history')
    history.add_argument('case_id')
    sub.add_parser('calls')
    args = ap.parse_args(argv)
    store = CaseStore(args.db)
    ledger = ProductLedger(Path(args.db).parent/'product-calls.sqlite3')
    if args.command == 'serve':
        from .server import serve
        seed_demo(store)
        serve(store, port=args.port, live=args.live, ledger=ledger)
        return
    if args.command == 'demo':
        saved = seed_demo(store)
        for p in saved:
            export(p, Path(args.output)/p.case_id)
        Path(args.output, 'comparison.json').write_text(json.dumps(compare_packets(*saved), indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'cases': [p.case_id for p in saved], 'output': args.output, 'new_model_calls': 0}))
        return
    if args.command == 'create':
        p = create_from_bundle(read_json(args.bundle))
        store.save(p, expected_version=0)
    elif args.command == 'reviewed-input':
        from .runtime import create_from_claim_reviews
        value=read_json(args.input)
        if set(value) != {'case_id','patient_id','source','claims','reviews','audit'}:
            raise ValueError('Reviewed input requires exact source/claims/reviews/audit')
        p=create_from_claim_reviews(value['source'],value['claims'],value['reviews'],
            case_id=value['case_id'],patient_id=value['patient_id'],audit=value['audit'])
        store.save(p,expected_version=0)
    elif args.command == 'extract':
        # Refuse duplicate case before spending a request.
        if any(c['case_id'] == args.case_id for c in store.list_cases()):
            raise ValueError('Case already exists; create a distinct encounter ID')
        text = Path(args.input).read_text(encoding='utf-8')
        src = Source.create(args.document_id if args.document_id is not None else args.case_id+':source',
                            text, args.kind, encounter_time=args.encounter_time)
        p = extract_live(args.case_id, args.patient_id, src, ledger, model=args.model,
            request_id=args.request_id,semantics_version=args.semantics_version,
            **({'task_version':args.task_version} if args.task_version is not None else {}))
        store.save(p, expected_version=0)
    elif args.command == 'import-cache':
        p = import_engine_cache(args.root, args.encounter_id, patient_id=args.patient_id, case_id=args.case_id)
        store.save(p, expected_version=0)
    elif args.command == 'replay-response':
        p = replay_product_response(args.source_packet, args.raw_response, args.product_ledger, case_id=args.case_id)
        store.save(p, expected_version=0)
    elif args.command == 'review':
        old = store.get(args.case_id)
        p = review_packet(old, validate_product_review_request(old, ReviewRequest.model_validate(read_json(args.request))))
        store.save(p, expected_version=old.version)
    elif args.command == 'review-semantics':
        from .models import SemanticsReviewRequest
        from .semantics import review_semantics
        old=store.get(args.case_id)
        p=review_semantics(old,validate_product_review_request(old,SemanticsReviewRequest.model_validate(read_json(args.request))))
        store.save(p,expected_version=old.version)
    elif args.command in {'correct-omission', 'complete-eligible'}:
        old = store.get(args.case_id)
        p = (correct_omission(old, validate_product_review_request(old, OmissionCorrectionRequest.model_validate(read_json(args.request))))
             if args.command == 'correct-omission' else complete_eligible_omissions(old, store=store))
        if p.version == old.version:
            print(json.dumps({'case_id':old.case_id,'version':old.version,'eligible_corrections':0}))
            return
        if args.command == 'correct-omission':
            store.save(p, expected_version=old.version)
    elif args.command == 'show':
        p = store.get(args.case_id, args.version)
        if args.output:
            export(p, args.output)
        print(p.model_dump_json(indent=2) if args.format == 'json' else render_markdown(p))
        return
    elif args.command == 'review-task':
        print(json.dumps(review_task(store.get(args.case_id), args.fact_id), indent=2, ensure_ascii=False))
        return
    elif args.command == 'compare':
        print(json.dumps(compare_packets(store.get(args.before_case), store.get(args.after_case)), indent=2, ensure_ascii=False))
        return
    elif args.command in {'list', 'history', 'calls'}:
        result = store.list_cases() if args.command == 'list' else store.history(args.case_id) if args.command == 'history' else ledger.summary()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    print(json.dumps({'case_id': p.case_id, 'version': p.version, 'status': p.extraction_status, 'hash': p.content_hash}))
