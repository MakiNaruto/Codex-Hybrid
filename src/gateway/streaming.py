"""Streaming conversion, retry payloads and content-free request diagnostics."""
import http.client
import json
import socket
import ssl
import urllib.error

from infrastructure.sse import records as sse_events

MAX_UNKNOWN_TOOL_RETRIES = 2
# Match Codex's documented 300000 ms SSE idle default on the official hop.
# urllib applies this to blocking socket operations, not total turn duration.
OFFICIAL_UPSTREAM_TIMEOUT_SECONDS = 300


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
        if isinstance(getattr(cause, 'winerror', None), int):
            result['winerror'] = cause.winerror
    return result


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
