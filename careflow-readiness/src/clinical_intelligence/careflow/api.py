"""Local synthetic-data HTTP API; no implicit provider calls or rule overrides."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import ValidationError

from .contracts import Case, EvidenceUpdate, Review, SourceIntake, SourceMaterialUpdate
from .report import SUPPORT_VIEW_VERSION, markdown, packet_support_view
from .rules import manifests
from .service import CareFlow, RevisionConflict

MAX_BODY_BYTES = 2_000_000


class BodyTooLarge(ValueError):
    pass


def make_server(db, host='127.0.0.1', port=8765):
    app = CareFlow(db)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # No patient IDs/documents in access logs.

        def respond(self, status, value, *, text=False, support_packet=None):
            if status >= 400:
                self.discard_rejected_body()
            semantic_contract = None
            if support_packet is None and not text and isinstance(value, dict):
                if value.get('schema_version') == 'careflow-review-packet/1':
                    support_packet = value
                elif isinstance(value.get('packet'), dict):
                    support_packet = value['packet']
                elif value.get('schema_version') == SUPPORT_VIEW_VERSION:
                    semantic_contract = value['status']
            if support_packet is not None:
                semantic_contract = packet_support_view(support_packet)['status']
            body = (value if text else json.dumps(value, ensure_ascii=False, allow_nan=False)).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/markdown; charset=utf-8' if text else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            if semantic_contract:
                self.send_header('X-CareFlow-Semantic-Contract', semantic_contract)
            self.end_headers()
            self.wfile.write(body)

        def discard_rejected_body(self):
            # Unread bodies can cause a TCP reset that discards the rejection,
            # especially on Windows. Drain only a bounded amount, without JSON
            # parsing/allocation, and never wait indefinitely for a slow sender.
            try:
                remaining = getattr(self, 'unread_body_bytes', int(self.headers.get('Content-Length', '0')))
                remaining = min(max(0, remaining), MAX_BODY_BYTES * 2)
                self.connection.settimeout(1)
                while remaining:
                    block = self.rfile.read(min(remaining, 65536))
                    if not block:
                        break
                    remaining -= len(block)
            except (ValueError, OSError):
                pass

        def body(self, cls):
            self.connection.settimeout(10)
            length = int(self.headers.get('Content-Length', '0'))
            self.unread_body_bytes = max(0, length)
            if length > MAX_BODY_BYTES:
                raise BodyTooLarge('Request body exceeds 2 MB')
            if length <= 0:
                raise ValueError('A positive Content-Length JSON body is required')
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('Content-Type must be application/json')
            raw = self.rfile.read(length)
            self.unread_body_bytes = length - len(raw)
            if len(raw) != length:
                raise ValueError('Incomplete JSON body')
            return cls.model_validate_json(raw)

        def dispatch(self):
            parsed = urlsplit(self.path)
            path = [unquote(p) for p in parsed.path.strip('/').split('/')]
            query = parse_qs(parsed.query)
            if self.command == 'GET' and path == ['health']:
                return self.respond(200, {'status': 'ok', 'product': 'careflow/1.0.0'})
            if self.command == 'GET' and path == ['v1', 'rules']:
                return self.respond(200, manifests())
            if self.command == 'GET' and path == ['v1', 'schemas']:
                from .requirement_support import RequirementEvidence
                return self.respond(200, {'case': Case.model_json_schema(), 'review': Review.model_json_schema(),
                                          'evidence_update': EvidenceUpdate.model_json_schema(),
                                          'source_intake': SourceIntake.model_json_schema(),
                                          'source_material_update': SourceMaterialUpdate.model_json_schema(),
                                          'requirement_evidence': RequirementEvidence.model_json_schema()})
            if self.command == 'POST' and path == ['v1', 'intake']:
                from .raw_input import build_case
                intake = self.body(SourceIntake)
                case, receipt = build_case(**intake.model_dump(mode='json', exclude={'schema_version'}))
                return self.respond(201, {'packet': app.create(case), 'intake_receipt': receipt})
            if self.command == 'POST' and path == ['v1', 'cases']:
                return self.respond(201, app.create(self.body(Case)))
            if len(path) not in {3, 4} or path[:2] != ['v1', 'cases']:
                return self.respond(404, {'error': 'NOT_FOUND'})
            case_id, action = path[2], path[3] if len(path) == 4 else 'packet'
            if self.command == 'GET':
                revision = None
                if 'revision' in query:
                    if len(query['revision']) != 1:
                        raise ValueError('One revision query value is required')
                    revision = int(query['revision'][0])
                    if revision < 1:
                        raise ValueError('Revision must be positive')
                if action == 'packet':
                    return self.respond(200, app.packet(case_id, revision))
                if action == 'support-status':
                    return self.respond(200, packet_support_view(app.packet(case_id, revision)))
                if action == 'report':
                    packet = app.packet(case_id, revision)
                    return self.respond(200, markdown(packet, app.reviews(case_id)), text=True, support_packet=packet)
                if action == 'audit':
                    return self.respond(200, app.audit(case_id))
                if action == 'reviews':
                    return self.respond(200, app.reviews(case_id))
                if action == 'model-calls':
                    return self.respond(200, app.model_calls(case_id))
                if action == 'review-input':
                    packet = app.packet(case_id, revision)
                    return self.respond(200, {'invocation': 'optional_external_reviewer',
                                              'model_calls': 0, 'packet': packet, 'review_schema': Review.model_json_schema()})
            if self.command == 'POST':
                if action == 'materials':
                    return self.respond(201, app.add_material_sources(case_id, self.body(SourceMaterialUpdate)))
                if action == 'reviews':
                    return self.respond(201, app.review(case_id, self.body(Review)))
                if action in {'evidence', 'corrections'}:
                    update = self.body(EvidenceUpdate)
                    if action == 'corrections' and not any(f.amends_fact_id for f in update.facts):
                        raise ValueError('Corrections endpoint requires an explicit amendment')
                    return self.respond(201, app.add_evidence(case_id, update))
            return self.respond(404, {'error': 'NOT_FOUND'})

        def handle_request(self):
            try:
                self.dispatch()
            except BodyTooLarge as exc:
                self.respond(413, {'error': 'BODY_TOO_LARGE', 'message': str(exc)})
                self.close_connection = True
            except ValidationError as exc:
                self.respond(422, {'error': 'CONTRACT_INVALID', 'details': [
                    {'location': error['loc'], 'message': error['msg']} for error in exc.errors()]})
            except RevisionConflict as exc:
                self.respond(409, {'error': 'REVISION_CONFLICT', 'message': str(exc)})
            except KeyError:
                self.respond(404, {'error': 'NOT_FOUND'})
            except (ValueError, UnicodeError) as exc:
                self.respond(400, {'error': 'INVALID_REQUEST', 'message': str(exc)})
            except TimeoutError:
                self.respond(408, {'error': 'REQUEST_TIMEOUT'})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.respond(500, {'error': 'INTERNAL_ERROR'})

        do_GET = handle_request
        do_POST = handle_request

    return ThreadingHTTPServer((host, port), Handler)
