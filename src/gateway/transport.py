"""Shared streaming transport for OpenAI-compatible Chat Completions."""
import errno
import base64
import json
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def discover_proxies():
    if sys.platform != 'win32':
        return urllib.request.getproxies()
    # Windows follows the user's current system proxy switch. Environment
    # variables inherited at service startup must not keep an old proxy alive.
    return urllib.request.getproxies_registry()


class WindowsSystemProxyHandler(urllib.request.ProxyHandler):
    """Use Windows bypass rules too, without consulting inherited NO_PROXY."""

    def proxy_open(self, request, proxy, protocol):
        if request.host and urllib.request.proxy_bypass_registry(request.host):
            return None
        parsed = urllib.parse.urlsplit(proxy if '://' in proxy else 'http://' + proxy)
        if parsed.username and parsed.password:
            credentials = '{}:{}'.format(urllib.parse.unquote(parsed.username),
                                         urllib.parse.unquote(parsed.password))
            encoded = base64.b64encode(credentials.encode()).decode('ascii')
            request.add_header('Proxy-Authorization', 'Basic ' + encoded)
        hostport = urllib.parse.unquote(parsed.netloc.rsplit('@', 1)[-1])
        original_protocol = request.type
        request.set_proxy(hostport, parsed.scheme)
        if original_protocol != parsed.scheme and original_protocol != 'https':
            return self.parent.open(request, timeout=request.timeout)
        return None


class FreshProxyOpener:
    """Discover proxies for every request, without sharing mutable handlers.

    urllib's default ProxyHandler snapshots macOS system proxies at creation.
    A desktop service can outlive VPN/proxy changes and sleep/wake cycles.
    Rebuilding locally also keeps concurrent requests independent. Do not
    replay failed POSTs: the upstream may already have accepted a generation.
    """

    def __init__(self, upstream_proxy=None):
        self.upstream_proxy = upstream_proxy

    def open(self, request, timeout=120):
        windows = sys.platform == 'win32'
        proxies = ({'http': self.upstream_proxy, 'https': self.upstream_proxy}
                   if self.upstream_proxy and not windows else discover_proxies())
        # Record only presence, never proxy URLs, credentials or bypass lists.
        request.connected_proxy_configured = bool(proxies.get(request.type))
        handler = WindowsSystemProxyHandler if windows else urllib.request.ProxyHandler
        opener = urllib.request.build_opener(handler(proxies), NoRedirect())
        return opener.open(request, timeout=timeout)


VALIDATION_CODES = frozenset({
    'INVALID_ENV_FILE', 'MISSING_CONFIGURATION', 'OFFICIAL_ENDPOINT_REQUIRED',
    'UNSUPPORTED_REQUEST_FIELDS', 'MESSAGES_REQUIRED', 'INVALID_TOKEN_LIMIT',
    'UPSTREAM_STREAM_ERROR', 'UPSTREAM_INCOMPLETE', 'INVALID_TOOL_COMPLETION',
    'INVALID_TOOL_CALL', 'MISSING_TOOL_CALLS',
})


def error_event(error, stage, requested_model=None):
    """Report fixed diagnostic codes, never raw exception text or paths."""
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    number = getattr(cause, 'errno', None)
    if isinstance(error, urllib.error.HTTPError):
        code = 'UPSTREAM_HTTP_' + str(error.code)
    elif isinstance(cause, ssl.SSLCertVerificationError):
        code = 'TLS_CERTIFICATE_FAILED'
    elif isinstance(cause, ssl.SSLError):
        code = 'TLS_FAILED'
    elif isinstance(cause, socket.gaierror):
        code = 'DNS_LOOKUP_FAILED'
    elif isinstance(cause, TimeoutError):
        code = 'NETWORK_TIMEOUT'
    elif isinstance(cause, PermissionError) or number in {errno.EACCES, errno.EPERM}:
        code = 'NETWORK_ACCESS_DENIED' if stage in {'connect', 'stream'} else 'FILE_ACCESS_DENIED'
    elif isinstance(cause, FileNotFoundError):
        code = 'FILE_NOT_FOUND'
    elif isinstance(error, json.JSONDecodeError):
        code = 'INVALID_JSON'
    elif isinstance(error, ValueError) and str(error) in VALIDATION_CODES:
        code = str(error)
    elif isinstance(error, urllib.error.URLError):
        code = 'NETWORK_CONNECTION_FAILED'
    elif isinstance(error, (KeyError, TypeError, AttributeError, UnicodeError)):
        code = 'INVALID_STREAM_PAYLOAD' if stage == 'stream' else 'INVALID_LOCAL_INPUT'
    else:
        code = 'BRIDGE_REQUEST_FAILED'
    event = {'type': 'error', 'code': code, 'stage': stage}
    if isinstance(number, int):
        event['errno'] = number
    if requested_model is not None:
        event['requested_model'] = requested_model
    return event

def records(source):
    """Shared JSON SSE framing; event fields may supply missing payload types."""
    data, event_type = [], ''
    first = True

    def decode():
        value = json.loads('\n'.join(data))
        if not isinstance(value, dict):
            raise ValueError('INVALID_STREAM_PAYLOAD')
        if event_type and not value.get('type'):
            value['type'] = event_type
        return value

    for raw in source:
        line = raw.decode('utf-8').rstrip('\r\n')
        if first:
            line = line.removeprefix('\ufeff')
            first = False
        if not line:
            if data:
                value = '\n'.join(data)
                if value == '[DONE]':
                    return
                yield decode()
            data, event_type = [], ''
        elif line.startswith('data:'):
            value = line[5:].removeprefix(' ')
            if value == '[DONE]':
                if data:
                    yield decode()
                return
            data.append(value)
        elif line.startswith('event:'):
            event_type = line[6:].removeprefix(' ')
    if data and '\n'.join(data) != '[DONE]':
        yield decode()


def relay(source, emit, requested_model):
    text, calls, reason, returned_model = [], {}, None, None
    for chunk in records(source):
        if chunk.get('error'):
            raise ValueError('UPSTREAM_STREAM_ERROR')
        returned_model = chunk.get('model', returned_model)
        for choice in chunk.get('choices', []):
            if choice.get('index', 0) != 0:
                continue
            delta = choice.get('delta', {})
            if delta.get('content'):
                text.append(delta['content'])
                emit({'type': 'text_delta', 'text': delta['content']})
            for call in delta.get('tool_calls', []):
                entry = calls.setdefault(call['index'], {'id': '', 'type': 'function',
                    'function': {'name': '', 'arguments': ''}})
                if call.get('id'):
                    entry['id'] = call['id']
                for key in ('name', 'arguments'):
                    entry['function'][key] += call.get('function', {}).get(key, '')
            if choice.get('finish_reason'):
                reason = choice['finish_reason']
    if reason not in {'stop', 'tool_calls'}:
        raise ValueError('UPSTREAM_INCOMPLETE')
    message = {'role': 'assistant', 'content': ''.join(text) or None}
    if calls:
        if reason != 'tool_calls':
            raise ValueError('INVALID_TOOL_COMPLETION')
        message['tool_calls'] = [calls[i] for i in sorted(calls)]
        for call in message['tool_calls']:
            if not call['id'] or not call['function']['name']:
                raise ValueError('INVALID_TOOL_CALL')
            json.loads(call['function']['arguments'])
            emit({'type': 'tool_proposal', 'call': call})
    elif reason == 'tool_calls':
        raise ValueError('MISSING_TOOL_CALLS')
    emit({'type': 'turn_completed', 'requested_model': requested_model,
          'returned_model': returned_model, 'finish_reason': reason, 'message': message})
