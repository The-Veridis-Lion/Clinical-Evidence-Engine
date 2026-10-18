"""Local-only demonstration server. Browser and CLI share the same application."""
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, unquote, urlparse

from .demo import bundles
from .models import OmissionCorrectionRequest, ReviewRequest, SemanticsReviewRequest, Source
from .augmentation import correct_omission, complete_eligible_omissions
from .reviewer import review_task, validate_product_review_request, ProductModelReviewForbidden
from .runtime import create_from_bundle, extract_live
from .service import compare_packets, review_packet
from .store import VersionConflict
from .views import render_markdown, render_readable_markdown
from .presentation import draft_presentation


MAX_BODY_BYTES = 2_000_000


def make_server(store, *, port=8765, live=False, ledger=None, offline_evaluation=False,
                careflow_url=None, workbench_extractor=None):
    token = secrets.token_urlsafe(32)
    from .workbench import Workbench
    from .workbench_routes import route
    options = {'extractor': workbench_extractor} if workbench_extractor else {}
    workbench = Workbench(store, ledger=ledger, live=live, careflow_url=careflow_url, **options)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log raw clinical sources or reviewer bodies.

        def reply(self, value, status=200, content_type='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else (json.dumps(value, ensure_ascii=False) if content_type.startswith('application/json') else value).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def host_valid(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

        def do_GET(self):
            try:
                if not self.host_valid():
                    return self.reply({'error': 'Invalid local host'}, 403)
                parsed = urlparse(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                if path.startswith('/ui/'):
                    value, status = route(workbench, 'GET', path, query)
                    return self.reply(value, status)
                if path in {'/', '/workbench', '/workbench/'} or path.startswith('/workbench/'):
                    name = 'index.html' if path in {'/', '/workbench', '/workbench/'} else path.removeprefix('/workbench/')
                    # The Gemini-designed workbench is the only browser UI. Vite
                    # assets have one bounded directory; no arbitrary filesystem path.
                    if name not in {'index.html', 'THIRD_PARTY_LICENSES.txt'} and not re.fullmatch(r'assets/[A-Za-z0-9_-]+\.(?:js|css)', name):
                        return self.reply({'error': 'Unknown static asset'}, 404)
                    asset = files('clinical_intelligence.copilot').joinpath('static', 'gemini', *name.split('/'))
                    if not asset.is_file():
                        return self.reply({'error': 'Unknown static asset'}, 404)
                    content_type = 'text/html' if name.endswith('.html') else 'text/javascript' if name.endswith('.js') else 'text/plain' if name.endswith('.txt') else 'text/css'
                    return self.reply(asset.read_bytes(), content_type=content_type+'; charset=utf-8')
                if path == '/api/config':
                    from .defaults import request_options,PROFILE_VERSION
                    return self.reply({'csrf_token': token, 'live_enabled': live, 'offline_evaluation': offline_evaluation,
                                       'extraction_defaults':request_options(),'extraction_profile_version':PROFILE_VERSION,
                                       'runtime_model': 'gpt-6-luna', 'provider': os.environ.get('CLINICAL_PRODUCT_PROVIDER', 'codex_cli'),
                                       'schema_version': 'clinical-evidence-copilot/v1',
                                       'workbench_url': '/workbench/', 'workbench_contract': 'workbench/1',
                                       'careflow_url': careflow_url})
                if path == '/api/cases':
                    return self.reply(store.list_cases())
                if path == '/api/demo-bundles':
                    return self.reply(bundles())
                if path == '/api/calls':
                    return self.reply(ledger.summary() if ledger else {'dispatch_attempts': 0})
                if path == '/api/compare':
                    before = store.get(query['before'][0], int(query['before_version'][0]) if 'before_version' in query else None)
                    after = store.get(query['after'][0], int(query['after_version'][0]) if 'after_version' in query else None)
                    return self.reply(compare_packets(before, after))
                if path.startswith('/api/cases/'):
                    suffix = path[len('/api/cases/'):]
                    pieces = suffix.split('/')
                    case_id = unquote(pieces[0])
                    version = int(query['version'][0]) if 'version' in query else None
                    if len(pieces) == 2 and pieces[1] == 'history':
                        return self.reply(store.history(case_id))
                    p = store.get(case_id, version)
                    if len(pieces) == 2 and pieces[1] == 'presentation':
                        return self.reply(draft_presentation(p))
                    if len(pieces) == 2 and pieces[1] == 'markdown':
                        render = render_readable_markdown if query.get('view') == ['draft'] else render_markdown
                        return self.reply(render(p), content_type='text/markdown; charset=utf-8')
                    if len(pieces) == 2 and pieces[1] == 'review-task':
                        return self.reply(review_task(p, query.get('fact_id')))
                    if len(pieces) != 1:
                        return self.reply({'error': 'Unknown endpoint'}, 404)
                    return self.reply(p.model_dump(mode='json'))
                return self.reply({'error': 'Not found'}, 404)
            except KeyError as exc:
                self.reply({'error': str(exc)}, 404)
            except (ValueError, TypeError) as exc:
                self.reply({'error': str(exc)}, 400)

        def do_POST(self):
            try:
                if not self.host_valid() or not secrets.compare_digest(self.headers.get('X-Copilot-Token', ''), token):
                    return self.reply({'error': 'Local request token required'}, 403)
                origin = self.headers.get('Origin')
                if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}:
                    return self.reply({'error': 'Cross-origin request rejected'}, 403)
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > MAX_BODY_BYTES:
                    return self.reply({'error': 'Request body size outside allowed range'}, 413)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Request body must be an object')
                parsed = urlparse(self.path)
                if parsed.path.startswith('/ui/'):
                    value, status = route(workbench, 'POST', parsed.path, parse_qs(parsed.query), body)
                    return self.reply(value, status)
                if self.path == '/api/cases':
                    p = create_from_bundle(body)
                    store.save(p, expected_version=0)
                    return self.reply(p.model_dump(mode='json'), 201)
                if self.path == '/api/source-reviews':
                    if not offline_evaluation:
                        return self.reply({'error': 'Source-review import is an offline evaluation endpoint; disabled in the product server.'}, 403)
                    from .runtime import create_from_claim_reviews
                    if set(body) != {'case_id','patient_id','source','claims','reviews','audit'}:
                        raise ValueError('Reviewed input requires exact original source/claims/reviews/audit')
                    p=create_from_claim_reviews(body['source'],body['claims'],body['reviews'],
                        case_id=body['case_id'],patient_id=body['patient_id'],audit=body['audit'])
                    store.save(p,expected_version=0)
                    return self.reply(p.model_dump(mode='json'),201)
                if self.path == '/api/extract':
                    if not live:
                        return self.reply({'error': 'Live extraction is disabled. Start serve --live to enable it.'}, 403)
                    if any(c['case_id'] == body['case_id'] for c in store.list_cases()):
                        raise VersionConflict('Case already exists')
                    src = Source.create(body.get('document_id',body['case_id']+':source'), body['text'],
                                        body['input_kind'], encounter_time=body.get('encounter_time'))
                    options = {key: body[key] for key in ('semantics_version','task_version') if key in body}
                    if body.get('legacy_extraction'):
                        if options:raise ValueError('legacy_extraction cannot be combined with semantics/task options')
                        options={'semantics_version':None,'task_version':None}
                    p = extract_live(body['case_id'], body['patient_id'], src, ledger, **options)
                    store.save(p, expected_version=0)
                    return self.reply(p.model_dump(mode='json'), 201)
                if self.path.startswith('/api/cases/') and self.path.endswith('/reprocess'):
                    from .reprocessing import ReprocessRequest, reprocess_packet
                    case_id = unquote(self.path[len('/api/cases/'):-len('/reprocess')])
                    old = store.get(case_id)
                    request = ReprocessRequest.model_validate(body)
                    if request.base_version != old.version:
                        raise VersionConflict('Program reprocessing base version is stale')
                    p = reprocess_packet(old, request)
                    store.save(p, expected_version=old.version)
                    return self.reply(p.model_dump(mode='json'))
                if self.path.startswith('/api/cases/') and self.path.endswith('/semantics'):
                    case_id = unquote(self.path[len('/api/cases/'):-len('/semantics')])
                    old=store.get(case_id)
                    request=SemanticsReviewRequest.model_validate(body)
                    validate_product_review_request(old, request)
                    if request.base_version != old.version:
                        raise VersionConflict('Semantic correction base version is stale')
                    from .semantics import review_semantics
                    p=review_semantics(old,request)
                    store.save(p,expected_version=old.version)
                    return self.reply(p.model_dump(mode='json'))
                if self.path.startswith('/api/cases/') and self.path.endswith('/review'):
                    case_id = unquote(self.path[len('/api/cases/'):-len('/review')])
                    old = store.get(case_id)
                    request = ReviewRequest.model_validate(body)
                    validate_product_review_request(old, request)
                    if request.base_version != old.version:
                        raise VersionConflict('Review base version is stale; reload latest version')
                    p = review_packet(old, request)
                    store.save(p, expected_version=old.version)
                    return self.reply(p.model_dump(mode='json'))
                if self.path.startswith('/api/cases/') and self.path.endswith('/omission'):
                    case_id = unquote(self.path[len('/api/cases/'):-len('/omission')])
                    old = store.get(case_id)
                    if body.get('base_version') != old.version:
                        raise VersionConflict('Omission correction base version is stale')
                    request = validate_product_review_request(old, OmissionCorrectionRequest.model_validate(body))
                    p = correct_omission(old, request)
                    store.save(p, expected_version=old.version)
                    return self.reply(p.model_dump(mode='json'))
                if self.path.startswith('/api/cases/') and self.path.endswith('/complete-eligible'):
                    case_id = unquote(self.path[len('/api/cases/'):-len('/complete-eligible')])
                    old = store.get(case_id)
                    if body.get('base_version') != old.version:
                        raise VersionConflict('Completion base version is stale')
                    p = complete_eligible_omissions(old, store=store)
                    return self.reply(p.model_dump(mode='json'))
                return self.reply({'error': 'Unknown endpoint'}, 404)
            except ProductModelReviewForbidden as exc:
                self.reply({'error': str(exc)}, 403)
            except VersionConflict as exc:
                self.reply({'error': str(exc)}, 409)
            except KeyError as exc:
                self.reply({'error': str(exc)}, 404)
            except (ValueError, TypeError) as exc:
                self.reply({'error': str(exc)}, 400)

    class LocalServer(ThreadingHTTPServer):
        def server_close(self):
            workbench.close()
            super().server_close()
    server = LocalServer(('127.0.0.1', port), Handler)
    server.workbench = workbench
    return server


def serve(store, *, port=8765, live=False, ledger=None, offline_evaluation=False, careflow_url=None):
    server = make_server(store, port=port, live=live, ledger=ledger, offline_evaluation=offline_evaluation, careflow_url=careflow_url)
    print(f'Clinical Evidence Copilot: http://127.0.0.1:{server.server_port} · live extraction {"enabled" if live else "disabled"}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
