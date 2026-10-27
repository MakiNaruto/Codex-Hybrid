#!/usr/bin/env python3
"""Local desktop provider. Tool execution stays inside the official Codex backend."""
import argparse
import hmac
import http.client
import http.server
import json
import os
import socket
import ssl
from pathlib import Path
import socketserver
import threading
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import urllib.parse
import uuid

from model_catalog.legacy_config import load_config
from gateway.transport import FreshProxyOpener
from adapters.responses import (ResponsesAdapter, UnregisteredToolError,
                                 plaintext_collaboration_schema, NativeCoordinationAdapter)
from model_catalog.sources import load_source
from model_catalog.catalog import ConfigError, resolve_api_key
from adapters.chat import ChatAdapter
from adapters.request_compat import normalize_history, external_context, upstream_error
from model_catalog.agent_catalog import expose_spawn_catalog

OPENAI_URL = 'https://chatgpt.com/backend-api/codex/responses'
MAX_BODY = 32 * 1024 * 1024
MAX_UNKNOWN_TOOL_RETRIES = 2

# Hop-by-hop and local-only fields never reach an upstream provider.
OFFICIAL_HEADER_DENY = {
    'host', 'content-length', 'connection', 'transfer-encoding', 'te', 'upgrade',
    'accept-encoding', 'cookie', 'x-connected-token',
}


class _CoordinatedEvents:
    """Apply native spawn naming after protocol-specific event conversion."""
    def __init__(self, adapt, coordination):
        self.adapt = adapt
        self.coordination = coordination

    def event(self, original):
        converted = self.adapt(original)
        if isinstance(converted, list):
            return [renamed for item in converted
                    if (renamed := self.coordination.event(item)) is not None]
        if converted is None:
            return None
        return self.coordination.event(converted)


def coordinated(adapt, coordination):
    """Return a request-scoped bound adapter with native coordination."""
    return _CoordinatedEvents(adapt, coordination).event


def official_header_passthrough(settings):
    """Report whether official requests keep the client's protocol headers.

    The Codex endpoint only treats a request as the same cached conversation
    when the client's protocol headers survive the local hop. Namespace and
    catalog rewriting happen in the body, so forwarding headers never changes
    which model answers the turn.
    """
    if os.environ.get('CONNECTED_OFFICIAL_HEADER_PASSTHROUGH') == '1':
        return True
    return settings.get('official_header_passthrough') is True


def usage_fields(usage):
    """Keep token counts, including the cache split, never prompt content."""
    result = {key: usage[key] for key in ('input_tokens', 'output_tokens', 'total_tokens')
              if key in usage}
    details = usage.get('input_tokens_details')
    if isinstance(details, dict) and isinstance(details.get('cached_tokens'), int):
        result['cached_tokens'] = details['cached_tokens']
    return result


def connection_diagnostic(error):
    """Classify without serializing exception text, which can contain secrets."""
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    kind = 'connection_error'
    if isinstance(cause, http.client.IncompleteRead):
        kind = 'incomplete_read'
    elif isinstance(cause, http.client.HTTPException):
        kind = 'http_protocol_error'
    elif isinstance(cause, TimeoutError):
        kind = 'timeout'
    elif isinstance(cause, socket.gaierror):
        kind = 'dns_error'
    elif isinstance(cause, ssl.SSLCertVerificationError):
        kind = 'tls_certificate_error'
    elif isinstance(cause, ssl.SSLError):
        kind = 'tls_error'
    elif isinstance(cause, ConnectionRefusedError):
        kind = 'connection_refused'
    elif isinstance(cause, ConnectionResetError):
        kind = 'connection_reset'
    elif isinstance(cause, BrokenPipeError):
        kind = 'broken_pipe'
    result = {'error_kind': kind, 'error_type': type(error).__name__}
    if isinstance(cause, BaseException):
        result['cause_type'] = type(cause).__name__
        if isinstance(getattr(cause, 'errno', None), int):
            result['errno'] = cause.errno
    return result


def route(body, headers, settings, deepseek=None):
    """Build each request with fresh, vendor-specific headers and adapter state."""
    model = body.get('model')
    if model not in settings['models']:
        raise ConfigError('MODEL_NOT_ALLOWED')
    auth = headers.get('Authorization', '')
    if not auth.startswith('Bearer ') or len(auth) < 16:
        raise ValueError('SUBSCRIPTION_AUTH_REQUIRED')
    if body.get('stream') is not True:
        raise ValueError('STREAM_REQUIRED')
    body = expose_spawn_catalog(body, settings)
    if 'source' in settings and model not in settings['official_models']:
        catalog = load_source(settings)  # Fresh address, model and credentials every request.
        if settings['source']['type'] == 'cc-switch':
            binding = settings.get('cc_snapshot', {}).get('bindings', {}).get(model)
            if binding is None or catalog.bindings.get(model) != binding:
                raise ConfigError('MODEL_NOT_CONFIGURED')
        selected, provider = catalog.select(model)
        coordination = NativeCoordinationAdapter(
            set(settings['models']) - set(settings['official_models']))
        adapter = ChatAdapter(model) if provider['protocol'] == 'openai_chat_completions' else ResponsesAdapter()
        adapter.timeout_seconds = provider['timeout_seconds']
        converted = adapter.request(external_context(body, selected))
        if provider['protocol'] == 'openai_chat_completions':
            payload = converted
            limit_field = provider['token_limit_field']
            adapt = coordinated(adapter.event, coordination)
        else:
            payload = {key: value for key, value in converted.items()
                       if key in {'model', 'input', 'instructions', 'tools', 'stream'}}
            limit_field = 'max_output_tokens'
            adapt = coordinated(adapter.stream_events, coordination)
        # Provider settings may extend a request but never replace routing
        # instructions or the bridge's no-storage policy.
        payload.update({key: value for key, value in selected['parameters'].items()
                        if key not in {'store', 'instructions'}})
        if provider['protocol'] == 'openai_responses':
            payload['store'] = False
        payload['model'] = selected['model_id']
        configured_limit = selected.get(
            'output_limit_configured', selected.get('max_output_tokens') is not None)
        budget = body.get('max_output_tokens', selected['max_output_tokens'] if configured_limit else None)
        # An absent output setting is not an implicit token cap. Keep the
        # context window separate and let the upstream default apply.
        if 'max_output_tokens' in body or configured_limit:
            if type(budget) is not int or budget <= 0:
                raise ValueError('INVALID_OUTPUT_BUDGET')
            payload[limit_field] = min(budget, selected['max_output_tokens']) if configured_limit else budget
        return provider['endpoint'], payload, {
            'Authorization': 'Bearer ' + resolve_api_key(provider),
            'Content-Type': 'application/json', 'Accept': 'text/event-stream'}, adapt
    if 'source' not in settings and model == deepseek['DEEPSEEK_MODEL']:
        adapter = ResponsesAdapter()
        coordination = NativeCoordinationAdapter(deepseek['DEEPSEEK_MODEL'])
        # Bindings belong to this request, never to a shared server instance.
        payload = adapter.request(external_context(body, {
            'display_name': deepseek['DEEPSEEK_MODEL'], 'model_id': deepseek['DEEPSEEK_MODEL']}))
        budget = body.get('max_output_tokens', settings['deepseek_max_output_tokens'])
        if type(budget) is not int or budget <= 0:
            raise ValueError('INVALID_OUTPUT_BUDGET')
        payload['max_output_tokens'] = min(budget, settings['deepseek_max_output_tokens'])
        payload['reasoning'] = {'effort': 'none'}
        return (deepseek['DEEPSEEK_BASE_URL'] + '/responses', payload,
                {'Authorization': 'Bearer ' + deepseek['DEEPSEEK_API_KEY'],
                 'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
                coordinated(adapter.stream_events, coordination))
    outgoing = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
    # Never forward the local access token, cookies, arbitrary destination or host.
    if official_header_passthrough(settings):
        for name, value in headers.items():
            if name.lower() not in OFFICIAL_HEADER_DENY:
                outgoing[name] = value
    else:
        for name in ['Authorization', 'ChatGPT-Account-ID', 'OpenAI-Beta', 'OpenAI-Organization',
                     'OpenAI-Project', 'User-Agent', 'Originator', 'Version', 'Session_ID',
                     'X-Codex-Turn-Metadata', 'X-Codex-Beta-Features']:
            if headers.get(name):
                outgoing[name] = headers[name]
    external_models = (set(settings['models']) - set(settings['official_models'])
                       if 'source' in settings else deepseek['DEEPSEEK_MODEL'])
    return OPENAI_URL, normalize_history(plaintext_collaboration_schema(body)), outgoing, NativeCoordinationAdapter(external_models).event


def sse_events(response):
    """Parse SSE records, including multi-line data and EOF without a blank line."""
    data = []
    for raw in response:
        line = raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if data:
                yield json.loads('\n'.join(data))
                data = []
        elif line.startswith('data:'):
            value = line[5:].lstrip(' ')
            if value == '[DONE]':
                if data:
                    yield json.loads('\n'.join(data))
                return
            data.append(value)
    if data:
        yield json.loads('\n'.join(data))


def adapted_stream(response, adapt, on_event=None):
    """A terminal Responses event ends the turn, without waiting for socket EOF."""
    for event in sse_events(response):
        if on_event is not None:
            on_event(event)
        events = adapt(event)
        if not isinstance(events, list):
            events = [] if events is None else [events]
        for adapted in events:
            yield event, adapted
            if adapted.get('type') in {'response.completed', 'response.failed', 'response.incomplete'}:
                return


def retry_payload_after_unknown_tool(payload, error):
    """Ask the third-party model to correct an unregistered tool proposal."""
    retry = json.loads(json.dumps(payload))
    items = retry.get('input')
    if not isinstance(items, list):
        raise error
    items.append({'type': 'message', 'role': 'developer', 'content': [{
        'type': 'input_text', 'text': (
            f'Your previous response called the unregistered tool {error.tool_name!r}. '
            'That call was discarded and no tool was executed. Continue the task using only '
            'the tools listed in the current request, with their exact names, or answer without '
            'a tool. Do not repeat the unavailable call.'
        )
    }]})
    return retry


class Gateway:
    def __init__(self, settings, settings_path=None, context=None):
        self.context = context
        self.started_at = time.monotonic()
        self.record = lambda observation: print(json.dumps(observation), flush=True)
        self.settings = settings
        self.deepseek = None if 'source' in settings else load_config(settings['env_file'])
        if self.deepseek and self.deepseek['DEEPSEEK_MODEL'] != settings['deepseek_model']:
            raise ValueError('DeepSeek model changed; prepare a matching catalog first')
        self.slots = threading.BoundedSemaphore(settings['max_concurrent_requests'])
        from gateway.activity import Activity
        self.activity = Activity()
        # No redirects: credentials can only go to the fixed official endpoints.
        self.opener = FreshProxyOpener()
        if context is not None:
            self.slots, self.activity, self.opener = context.slots, context.activity, context.opener
            self.record = context.record
        self.manager = None
        if settings_path is not None and 'source' in settings:
            from management.service import Management, private_write
            import secrets
            if 'management_token' not in settings:
                settings['management_token'] = secrets.token_urlsafe(32)
                private_write(settings_path, json.dumps(settings))
            self.manager = Management(self, settings_path, route, sse_events)

    @property
    def settings(self):
        return self.context.settings if self.context is not None else self._settings

    @settings.setter
    def settings(self, value):
        if self.context is not None:
            self.context.settings = value
        else:
            self._settings = value

    def handler(self):
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

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
                    settings = owner.settings
                    models = settings.get('cc_snapshot', {}).get('models')
                    directory = ({'models': models} if models is not None else
                                 json.loads(Path(settings['catalog']).read_text(encoding='utf-8')))
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
                if not owner.slots.acquire(blocking=False):
                    return self.reply(429, {'error': {'message': 'CONCURRENCY_LIMIT'}})
                started = False
                sequence = 0
                began = time.monotonic()
                observation = {'time': int(time.time()), 'status': 'rejected',
                               'request_id': uuid.uuid4().hex, 'phase': 'read_request'}
                event = None
                current_request = None
                settings = owner.settings
                owner.activity.begin()
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if size <= 0 or size > MAX_BODY or self.headers.get('Transfer-Encoding'):
                        return self.reply(413, {'error': {'message': 'INVALID_BODY_SIZE'}})
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError('INVALID_REQUEST_OBJECT')
                    if body.get('model') in settings['models']:
                        observation['model'] = body['model']
                    def tool_types(items):
                        result = []
                        for item in items:
                            result.append(str(item.get('type', 'missing'))[:64])
                            result.extend(tool_types(item.get('tools', [])))
                        return result
                    observation['tool_types'] = sorted(set(tool_types(body.get('tools', [])) +
                        tool_types([t for i in body.get('input', []) if i.get('type') == 'additional_tools'
                                    for t in i.get('tools', [])])))
                    observation['phase'] = 'route_request'
                    url, payload, headers, adapt = route(body, self.headers, settings, owner.deepseek)
                    observation['model'] = body['model']
                    target = urllib.parse.urlsplit(url)
                    adapter_owner = getattr(adapt, '__self__', None)
                    converter = getattr(adapter_owner, 'adapt', adapt)
                    protocol_adapter = getattr(converter, '__self__', adapter_owner)
                    native_adapter = getattr(protocol_adapter, 'native', protocol_adapter)
                    timeout = getattr(protocol_adapter, 'timeout_seconds', 120)
                    observation.update(upstream_host=target.hostname, upstream_port=target.port,
                                       upstream_scheme=target.scheme, timeout_seconds=timeout,
                                       phase='connect_upstream')
                    # Chat and official traffic retain immediate streaming. Only
                    # Responses generations can be discarded and regenerated.
                    retry_unknown_tools = isinstance(protocol_adapter, ResponsesAdapter)
                    coordination = getattr(adapter_owner, 'coordination', None)
                    initial_calls = dict(getattr(native_adapter, 'call_bindings', {}))

                    def start_stream():
                        nonlocal started
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Cache-Control', 'no-cache')
                        self.end_headers()
                        started = True

                    def write_event(adapted):
                        nonlocal sequence
                        observation['phase'] = 'write_client'
                        if adapted.get('type') == 'response.output_text.delta':
                            observation['text_delta_events'] = observation.get('text_delta_events', 0) + 1
                        if adapted.get('type') in {'response.completed', 'response.failed', 'response.incomplete'}:
                            final = adapted.get('response', {})
                            observation.update(status=final.get('status'), returned_model=(
                                final.get('metadata') or {}).get('connected_upstream_model', final.get('model')),
                                usage=usage_fields(final.get('usage') or {}))
                        adapted['sequence_number'] = sequence
                        sequence += 1
                        self.wfile.write(('event: ' + adapted['type'] + '\ndata: ' +
                                          json.dumps(adapted) + '\n\n').encode())
                        self.wfile.flush()
                        observation['phase'] = 'read_upstream'

                    retries = 0
                    while True:
                        observation['phase'] = 'connect_upstream'
                        current_request = urllib.request.Request(
                            url, data=json.dumps(payload).encode(), headers=headers)
                        try:
                            # Spill large generations to disk; close the spool on
                            # success, retry, transport failure and client failure.
                            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+t') as buffered:
                                with owner.opener.open(current_request, timeout=timeout) as response:
                                    observation['headers_received_ms'] = round((time.monotonic() - began) * 1000)
                                    observation['phase'] = 'read_upstream'
                                    if not retry_unknown_tools:
                                        start_stream()
                                    def observe_event(upstream_event):
                                        nonlocal event
                                        event = upstream_event
                                        observation['phase'] = 'adapt_event'
                                        observation['last_upstream_event'] = event.get('type')
                                    terminal = False
                                    for _, adapted in adapted_stream(response, adapt, observe_event):
                                        terminal = adapted.get('type') in {
                                            'response.completed', 'response.failed', 'response.incomplete'}
                                        if retry_unknown_tools:
                                            buffered.write(json.dumps(adapted) + '\n')
                                        else:
                                            write_event(adapted)
                                        observation['phase'] = 'read_upstream'
                                if retry_unknown_tools:
                                    if not terminal:
                                        # Never publish potentially executable calls
                                        # from a truncated, unvalidated generation.
                                        self.reply(502, {'error': {'code': 'UPSTREAM_STREAM_ENDED_EARLY',
                                            'message': 'UPSTREAM_STREAM_ENDED_EARLY',
                                            'request_id': observation['request_id']}})
                                        observation['status'] = 'stream_ended_without_completion'
                                        return
                                    start_stream()
                                    buffered.seek(0)
                                    for line in buffered:
                                        write_event(json.loads(line))
                            break
                        except UnregisteredToolError as error:
                            if not retry_unknown_tools or retries >= MAX_UNKNOWN_TOOL_RETRIES:
                                raise
                            retries += 1
                            observation['unknown_tool_retries'] = retries
                            observation['last_unknown_tool'] = error.tool_name
                            payload = retry_payload_after_unknown_tool(payload, error)
                            # Keep advertised tools and historical call bindings.
                            native_adapter.call_bindings = dict(initial_calls)
                            native_adapter.pending_added = {}
                            if coordination is not None:
                                coordination.names = {}
                                coordination.spawn_items = set()
                    observation['phase'] = 'read_upstream'
                    if observation['status'] == 'rejected':
                        observation['status'] = 'stream_ended_without_completion'
                        self.stream_failure('UPSTREAM_STREAM_ENDED_EARLY', sequence=sequence)
                except urllib.error.HTTPError as error:
                    # Do not log upstream bodies: they may echo input or credentials.
                    observation.update(status='upstream_http_error', http_status=error.code)
                    diagnostic = upstream_error({}, error.code)
                    try:
                        detail = json.loads(error.read()).get('error', {})
                        diagnostic = upstream_error(detail, error.code)
                        for key in ['type', 'code', 'param']:
                            value = detail.get(key)
                            if isinstance(value, str) and len(value) <= 180 and all(
                                    c.isalnum() or c in '_.[] -' for c in value):
                                observation['upstream_error_' + key] = value
                        message = str(detail.get('message', '')).lower()
                        observation['validation_terms'] = [term for term in [
                            'reasoning', 'function', 'tool', 'arguments', 'call_id', 'encrypted',
                            'signature', 'mismatch', 'not found', 'schema', 'required', 'following',
                            'missing', 'invalid', 'duplicate', 'reserved'] if term in message]
                    except (ValueError, AttributeError):
                        pass
                    error.close()
                    if not started:
                        self.reply(error.code, {'error': diagnostic})
                except (ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
                    observation['status'] = 'incompatible_request_or_stream'
                    observation['error_type'] = type(error).__name__
                    observation['error_locations'] = [f'{Path(f.filename).name}:{f.lineno}:{f.name}'
                        for f in traceback.extract_tb(error.__traceback__)]
                    if hasattr(error, 'tool_name'):
                        observation['unregistered_tool'] = error.tool_name
                        bindings = getattr(native_adapter, 'bindings', {})
                        observation['registered_tool_names'] = sorted(bindings)
                    if event:
                        observation['event_type'] = event.get('type')
                    code = getattr(error, 'code', None) or ('GATEWAY_UNREGISTERED_TOOL'
                        if hasattr(error, 'tool_name') else 'GATEWAY_STREAM_ADAPTATION_FAILED')
                    if getattr(error, 'code', None):
                        observation['error_code'] = code
                    detail = None
                    if hasattr(error, 'tool_name'):
                        detail = {'request_id': observation['request_id'],
                                  'message': 'GATEWAY_UNREGISTERED_TOOL: the model called '
                                  f'unknown tool {error.tool_name!r}; no tool was executed; '
                                  f'request_id={observation["request_id"]}'}
                    if not started:
                        self.reply(400, {'error': {'code': code, 'message': code, **(detail or {})}})
                    else:
                        self.stream_failure(code, detail, sequence=sequence)
                except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
                    observation.update(connection_diagnostic(error))
                    observation['elapsed_ms'] = round((time.monotonic() - began) * 1000)
                    if observation['phase'] in {'write_client', 'read_request'}:
                        observation['status'] = 'client_disconnected'
                        return
                    observation['status'] = 'upstream_connection_failed'
                    detail = {key: observation[key] for key in [
                        'request_id', 'phase', 'error_kind', 'error_type', 'cause_type', 'errno',
                        'elapsed_ms', 'timeout_seconds', 'upstream_host'] if key in observation}
                    detail['message'] = ('UPSTREAM_CONNECTION_FAILED: ' + detail['error_kind'] +
                        '; phase=' + detail['phase'] + '; request_id=' + detail['request_id'] +
                        '; consult service.jsonl')
                    if not started:
                        self.reply(502, {'error': {'code': 'UPSTREAM_CONNECTION_FAILED', **detail}})
                    else:
                        self.stream_failure('UPSTREAM_CONNECTION_FAILED', detail, sequence=sequence)
                finally:
                    owner.activity.end()
                    if current_request is not None and hasattr(current_request, 'connected_proxy_configured'):
                        observation['proxy_configured'] = current_request.connected_proxy_configured
                    observation['elapsed_ms'] = round((time.monotonic() - began) * 1000)
                    owner.slots.release()
                    # Only metadata; no prompts, messages, tool inputs, headers or tokens.
                    owner.record(observation)

        return Handler


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # Avoid reverse DNS lookup during startup.
        socketserver.TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.server_address[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    args = parser.parse_args()
    from desktop.locking import DirectoryLock
    from gateway.runtime_log import RuntimeLog
    from management.runtime import serve
    import sys
    with DirectoryLock(args.settings.resolve().parent, 'service.lock', 'SERVICE_ALREADY_RUNNING'):
        runtime_log = RuntimeLog(args.settings.resolve().parent)
        previous_stderr = sys.stderr
        sys.stderr = runtime_log.stderr
        try:
            serve(args.settings, runtime_log.emit)
        finally:
            sys.stderr = previous_stderr
            runtime_log.close()


if __name__ == '__main__':
    main()
