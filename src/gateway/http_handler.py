"""HTTP admission, request lifetime and upstream forwarding for the local gateway."""
import hmac
import http.client
import http.server
import json
from pathlib import Path
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

from adapters.stream_errors import upstream_error
from adapters.responses import ResponsesAdapter, UnregisteredToolError
from gateway.routing import MAX_BODY, resolve_requested_model, route
from gateway.official_catalog import cached_directory, refresh_official_directory
from gateway.streaming import (
    MAX_UNKNOWN_TOOL_RETRIES, OFFICIAL_UPSTREAM_TIMEOUT_SECONDS, usage_fields,
    connection_diagnostic, adapted_stream, retry_payload_after_unknown_tool,
)
from infrastructure.upstream_errors import diagnostic as upstream_diagnostic, ERROR_MESSAGES


class _ResponseTurn:
    """Own one admitted request through decoding, forwarding and final cleanup."""
    def __init__(self, handler, owner):
        self.handler = handler
        self.owner = owner
        self.started = False
        self.sequence = 0
        self.began = time.monotonic()
        self.observation = {'time': int(time.time()), 'status': 'rejected',
                            'request_id': uuid.uuid4().hex, 'phase': 'read_request'}
        self.event = None
        self.current_request = None
        self.settings = self.owner.settings

    def read_request(self):
        size = int(self.handler.headers.get('Content-Length', '0'))
        if size <= 0 or size > MAX_BODY or self.handler.headers.get('Transfer-Encoding'):
            self.observation['error_code'] = 'INVALID_BODY_SIZE'
            return self.handler.reply(413, {'error': {'message': 'INVALID_BODY_SIZE'}})
        body = json.loads(self.handler.rfile.read(size))
        if not isinstance(body, dict):
            raise ValueError('INVALID_REQUEST_OBJECT')
        return body

    def resolve_model(self, body):
        # Desktop can use its cached model directory without GET /models.
        # Reconcile an unknown ID against the authenticated account directory
        # before applying the allowlist; never accept an arbitrary ID.
        requested_model = body.get('model')
        resolved_model, _ = resolve_requested_model(requested_model, self.settings)
        if (resolved_model is None and isinstance(requested_model, str)
                and requested_model
                and self.settings.get('official_models_enabled') is not False
                and self.handler.headers.get('Authorization', '').startswith('Bearer ')):
            self.observation['phase'] = 'refresh_official_catalog'
            refresh_official_directory(self.owner, self.handler.headers)
            self.settings = self.owner.settings
            resolved_model, _ = resolve_requested_model(requested_model, self.settings)
        if resolved_model is not None and resolved_model != requested_model:
            body = {**body, 'model': resolved_model}
        return body, requested_model

    def observe_request(self, body, requested_model):
        self.observation['stream'] = body.get('stream') is True
        self.observation['route_type'] = ('official' if body.get('model') in
                                           self.settings.get('official_models', []) else 'external')
        if body.get('model') in self.settings['models']:
            self.observation['model'] = body['model']
        if (isinstance(requested_model, str)
                and requested_model != body.get('model')):
            self.observation['requested_model'] = requested_model[:256]
        def tool_types(items):
            result = []
            for item in items:
                result.append(str(item.get('type', 'missing'))[:64])
                result.extend(tool_types(item.get('tools', [])))
            return result
        self.observation['tool_types'] = sorted(set(tool_types(body.get('tools', [])) +
            tool_types([t for i in body.get('input', []) if i.get('type') == 'additional_tools'
                        for t in i.get('tools', [])])))
        def has_spawn(tools):
            return any(tool.get('name') == 'spawn_agent' or has_spawn(tool.get('tools', []))
                       for tool in tools)
        self.observation['spawn_agent_in_request_tools'] = has_spawn(body.get('tools', []))
        self.observation['spawn_agent_in_history_tools'] = any(
            has_spawn(item.get('tools', [])) for item in body.get('input', [])
            if item.get('type') in {'additional_tools', 'tool_search_output'})
        self.observation['spawn_agent_advertised'] = (self.observation['spawn_agent_in_request_tools']
                                                      or self.observation['spawn_agent_in_history_tools'])

    def route_request(self, body):
        self.observation['phase'] = 'route_request'
        self.url, self.payload, self.headers, self.adapt = route(
            body, self.handler.headers, self.settings, self.owner.deepseek)
        self.observation['model'] = body['model']
        target = urllib.parse.urlsplit(self.url)
        adapter_owner = getattr(self.adapt, '__self__', None)
        converter = getattr(adapter_owner, 'adapt', self.adapt)
        protocol_adapter = getattr(converter, '__self__', adapter_owner)
        self.native_adapter = getattr(protocol_adapter, 'native', protocol_adapter)
        self.timeout = getattr(protocol_adapter, 'timeout_seconds', OFFICIAL_UPSTREAM_TIMEOUT_SECONDS)
        self.observation['protocol'] = 'openai_responses'
        self.observation.update(upstream_host=target.hostname, upstream_port=target.port,
                                upstream_scheme=target.scheme, timeout_seconds=self.timeout,
                                phase='connect_upstream')
        # Portable Responses generations can be discarded and regenerated.
        self.retry_unknown_tools = isinstance(protocol_adapter, ResponsesAdapter)
        self.coordination = getattr(adapter_owner, 'coordination', None)
        self.initial_calls = dict(getattr(self.native_adapter, 'call_bindings', {}))

    def start_stream(self):
        self.handler.send_response(200)
        self.handler.send_header('Content-Type', 'text/event-stream')
        self.handler.send_header('Cache-Control', 'no-cache')
        self.handler.end_headers()
        self.started = True

    def write_event(self, adapted):
        self.observation['phase'] = 'write_client'
        if adapted.get('type') == 'response.output_text.delta':
            self.observation['text_delta_events'] = self.observation.get('text_delta_events', 0) + 1
        if adapted.get('type') in {'response.completed', 'response.failed', 'response.incomplete'}:
            final = adapted.get('response', {})
            self.observation.update(status=final.get('status'), returned_model=(
                final.get('metadata') or {}).get('connected_upstream_model', final.get('model')),
                usage=usage_fields(final.get('usage') or {}))
        adapted['sequence_number'] = self.sequence
        self.sequence += 1
        self.handler.wfile.write(('event: ' + adapted['type'] + '\ndata: ' +
                                  json.dumps(adapted) + '\n\n').encode())
        self.handler.wfile.flush()
        self.observation['phase'] = 'read_upstream'

    def observe_event(self, upstream_event):
        self.event = upstream_event
        self.observation['phase'] = 'adapt_event'
        self.observation['last_upstream_event'] = self.event.get('type')
        response_body = self.event.get('response')
        detail = response_body.get('error') if isinstance(response_body, dict) else None
        detail = detail or self.event.get('error')
        if not detail and (self.event.get('type') == 'error' or
                ('code' in self.event and 'message' in self.event)):
            detail = self.event
        if detail:
            self.observation.update(upstream_diagnostic(detail, secrets=(
                self.headers.get('Authorization', '').removeprefix('Bearer '),)))

    def forward(self):
        retries = 0
        while True:
            self.observation['phase'] = 'connect_upstream'
            self.current_request = urllib.request.Request(
                self.url, data=json.dumps(self.payload).encode(), headers=self.headers)
            try:
                # Spill large generations to disk; close the spool on
                # success, retry, transport failure and client failure.
                with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+t') as buffered:
                    with self.owner.opener.open(self.current_request, timeout=self.timeout) as response:
                        self.observation['headers_received_ms'] = round((time.monotonic() - self.began) * 1000)
                        self.observation['phase'] = 'read_upstream'
                        if not self.retry_unknown_tools:
                            self.start_stream()
                        terminal = False
                        for _, adapted in adapted_stream(response, self.adapt, self.observe_event):
                            terminal = adapted.get('type') in {
                                'response.completed', 'response.failed', 'response.incomplete'}
                            if self.retry_unknown_tools:
                                buffered.write(json.dumps(adapted) + '\n')
                            else:
                                self.write_event(adapted)
                            self.observation['phase'] = 'read_upstream'
                    if self.retry_unknown_tools:
                        if not terminal:
                            # Never publish potentially executable calls
                            # from a truncated, unvalidated generation.
                            self.handler.reply(502, {'error': {'code': 'UPSTREAM_STREAM_ENDED_EARLY',
                                'message': 'UPSTREAM_STREAM_ENDED_EARLY',
                                'request_id': self.observation['request_id']}})
                            self.observation['status'] = 'stream_ended_without_completion'
                            return
                        self.start_stream()
                        buffered.seek(0)
                        for line in buffered:
                            self.write_event(json.loads(line))
                break
            except UnregisteredToolError as error:
                if not self.retry_unknown_tools or retries >= MAX_UNKNOWN_TOOL_RETRIES:
                    raise
                retries += 1
                self.observation['unknown_tool_retries'] = retries
                self.observation['last_unknown_tool'] = error.tool_name
                self.payload = retry_payload_after_unknown_tool(self.payload, error)
                # Keep advertised tools and historical call bindings.
                self.native_adapter.call_bindings = dict(self.initial_calls)
                self.native_adapter.pending_added = {}
                if self.coordination is not None:
                    self.coordination.names = {}
                    self.coordination.spawn_items = set()
        self.observation['phase'] = 'read_upstream'
        if self.observation['status'] == 'rejected':
            self.observation['status'] = 'stream_ended_without_completion'
            self.handler.stream_failure('UPSTREAM_STREAM_ENDED_EARLY', sequence=self.sequence)

    def http_error(self, error):
        # Retain bounded, credential-redacted error fields for local details.
        self.observation.update(status='upstream_http_error', http_status=error.code)
        diagnostic = upstream_error({}, error.code)
        try:
            detail = json.loads(error.read()).get('error', {})
            authorization = self.current_request.get_header('Authorization', '') if self.current_request else ''
            self.observation.update(upstream_diagnostic(detail, error.code, secrets=(
                authorization.removeprefix('Bearer '),)))
            diagnostic = upstream_error(detail, error.code)
            code = self.observation['error_code']
            diagnostic['message'] = code + ': ' + ERROR_MESSAGES[code]
            message = str(detail.get('message', '')).lower()
            self.observation['validation_terms'] = [term for term in [
                'reasoning', 'function', 'tool', 'arguments', 'call_id', 'encrypted',
                'signature', 'mismatch', 'not found', 'schema', 'required', 'following',
                'missing', 'invalid', 'duplicate', 'reserved'] if term in message]
        except (ValueError, AttributeError):
            pass
        error.close()
        if not self.started:
            self.handler.reply(error.code, {'error': diagnostic})

    def incompatible_error(self, error):
        self.observation['status'] = 'incompatible_request_or_stream'
        self.observation['error_type'] = type(error).__name__
        if hasattr(error, 'agent_content_shapes'):
            self.observation['agent_content_shapes'] = error.agent_content_shapes
        source_root = Path(__file__).resolve().parents[1]
        self.observation['error_locations'] = [
            f'{Path(f.filename).resolve().relative_to(source_root).as_posix()}:{f.lineno}'
            for f in traceback.extract_tb(error.__traceback__)
            if Path(f.filename).resolve().is_relative_to(source_root)]
        if hasattr(error, 'tool_name'):
            self.observation['unregistered_tool'] = error.tool_name
            bindings = getattr(self.native_adapter, 'bindings', {})
            self.observation['registered_tool_names'] = sorted(bindings)
        if self.event:
            self.observation['event_type'] = self.event.get('type')
        code = getattr(error, 'code', None) or ('GATEWAY_UNREGISTERED_TOOL'
            if hasattr(error, 'tool_name') else 'GATEWAY_STREAM_ADAPTATION_FAILED')
        self.observation['error_code'] = code
        if (type(error) is ValueError and error.args and isinstance(error.args[0], str)
                and error.args[0] in {
                'SUBSCRIPTION_AUTH_REQUIRED', 'STREAM_REQUIRED', 'INVALID_REQUEST_OBJECT',
                'UPSTREAM_PROTOCOL_MISMATCH', 'INVALID_STREAM_PAYLOAD',
                'UNSUPPORTED_REASONING_HISTORY', 'UNSUPPORTED_SYSTEM_CONTENT',
                'UNSUPPORTED_AGENT_MESSAGE_CONTENT'}):
            self.observation['error_code'] = error.args[0]
            code = error.args[0]
        detail = None
        if hasattr(error, 'tool_name'):
            detail = {'request_id': self.observation['request_id'],
                      'message': 'GATEWAY_UNREGISTERED_TOOL: the model called '
                      f'unknown tool {error.tool_name!r}; no tool was executed; '
                      f'request_id={self.observation["request_id"]}'}
        if not self.started:
            message = ('The requested model is not in the current model list. '
                       'Select an available model and try again.'
                       if code == 'MODEL_NOT_IN_LIST' else code)
            self.handler.reply(400, {'error': {'code': code, 'message': message, **(detail or {})}})
        else:
            self.handler.stream_failure(code, detail, sequence=self.sequence)

    def connection_error(self, error):
        self.observation.update(connection_diagnostic(error))
        self.observation['elapsed_ms'] = round((time.monotonic() - self.began) * 1000)
        if self.observation['phase'] in {'write_client', 'read_request'}:
            self.observation['status'] = 'client_disconnected'
            return
        self.observation['status'] = 'upstream_connection_failed'
        detail = {key: self.observation[key] for key in [
            'request_id', 'phase', 'error_kind', 'error_type', 'cause_type', 'errno',
            'elapsed_ms', 'timeout_seconds', 'upstream_host'] if key in self.observation}
        detail['message'] = ('UPSTREAM_CONNECTION_FAILED: ' + detail['error_kind'] +
            '; phase=' + detail['phase'] + '; request_id=' + detail['request_id'] +
            '; consult service.jsonl')
        if not self.started:
            self.handler.reply(502, {'error': {'code': 'UPSTREAM_CONNECTION_FAILED', **detail}})
        else:
            self.handler.stream_failure('UPSTREAM_CONNECTION_FAILED', detail, sequence=self.sequence)

    def run(self):
        self.owner.activity.begin()
        try:
            body = self.read_request()
            if body is None:
                return
            body, requested_model = self.resolve_model(body)
            self.observe_request(body, requested_model)
            self.route_request(body)
            self.forward()
        except urllib.error.HTTPError as error:
            self.http_error(error)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            self.incompatible_error(error)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            self.connection_error(error)
        finally:
            self.owner.activity.end()
            if self.current_request is not None and hasattr(self.current_request, 'connected_proxy_configured'):
                self.observation['proxy_configured'] = self.current_request.connected_proxy_configured
            self.observation['elapsed_ms'] = round((time.monotonic() - self.began) * 1000)
            # Request metadata and bounded upstream errors, without request bodies or headers.
            self.owner.record(self.observation)


def make_handler(owner):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # Client cancellation is normal, including during headers or
                # an error response outside the inference streaming loop.
                self.close_connection = True

        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(180)

        def reply(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            return hmac.compare_digest(self.headers.get('X-Connected-Token', ''),
                                       owner.settings['local_token'])

        def stream_failure(self, code, detail=None, sequence=None):
            """Terminate the turn with a protocol event instead of a bare EOF.

            Codex ignores the legacy `error` event and reports any stream that
            closes without a terminal response event as a generic disconnect.
            Sending `response.failed` makes the real cause visible.
            """
            failure = {'type': 'error', 'code': code, 'message': code +
                       ': consult the local gateway metadata log.', 'param': None}
            if detail:
                failure.update(detail)
            terminal = {'type': 'response.failed', 'response': {
                'id': 'resp_gateway_' + uuid.uuid4().hex, 'object': 'response',
                'created_at': int(time.time()), 'status': 'failed',
                'error': {'code': code, 'message': failure['message']}, 'output': [],
                'usage': None}}
            if sequence is not None:
                terminal['sequence_number'] = sequence
            try:
                self.wfile.write(('event: error\ndata: ' + json.dumps(failure) + '\n\n').encode())
                self.wfile.write(('event: response.failed\ndata: ' +
                                  json.dumps(terminal) + '\n\n').encode())
                self.wfile.flush()
            except OSError:
                pass

        def do_GET(self):
            if getattr(owner, 'manager', None) is not None:
                from management.http import handle
                if handle(self, owner, 'GET'):
                    return
            if self.path == '/healthz':
                return self.reply(200, {'service': 'connected-native-gateway', 'version': 1})
            if not self.authorized():
                return self.reply(401, {'error': {'message': 'LOCAL_AUTH_REQUIRED'}})
            if self.path.split('?', 1)[0] == '/models':
                if owner.settings.get('official_models_enabled') is False:
                    directory = cached_directory(owner.settings)
                    if directory is None:
                        return self.reply(502, {'error': {
                            'message': 'LOCAL_MODEL_LIST_UNAVAILABLE'}})
                    return self.reply(200, directory)
                if not self.headers.get('Authorization', '').startswith('Bearer '):
                    return self.reply(401, {'error': {'message': 'SUBSCRIPTION_AUTH_REQUIRED'}})
                directory = refresh_official_directory(
                    owner, self.headers, urllib.parse.urlsplit(self.path).query)
                if directory is None:
                    directory = cached_directory(owner.settings)
                    owner.record({'time': int(time.time()),
                                  'status': 'official_catalog_refresh_failed',
                                  'cached_directory': directory is not None})
                    if directory is None:
                        return self.reply(502, {'error': {'message': 'OFFICIAL_MODEL_LIST_UNAVAILABLE'}})
                return self.reply(200, directory)
            self.reply(404, {'error': {'message': 'UNSUPPORTED_ENDPOINT'}})

        def do_POST(self):
            if getattr(owner, 'manager', None) is not None:
                from management.http import handle
                if handle(self, owner, 'POST'):
                    return
            if not self.authorized() or self.headers.get('Origin'):
                return self.reply(401, {'error': {'message': 'LOCAL_AUTH_REQUIRED'}})
            if self.path != '/responses':
                return self.reply(404, {'error': {'message': 'UNSUPPORTED_ENDPOINT'}})
            _ResponseTurn(self, owner).run()

    return Handler
