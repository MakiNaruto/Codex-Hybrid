"""Bounded, allowlisted diagnostics; never export raw configuration or log lines."""
import builtins
import hashlib
import platform
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import json
import math
import re
import time

from gateway.upstream_errors import ERROR_MESSAGES, redact_text


STATUSES = {'rejected', 'incompatible_request_or_stream', 'upstream_connection_failed',
            'upstream_http_error', 'client_disconnected', 'failed', 'incomplete',
            'stream_ended_without_completion', 'forwarding_exited', 'forwarding_start_failed'}
PHASES = {'read_request', 'route_request', 'connect_upstream', 'read_upstream', 'write_client', 'adapt_event'}


def number(value, maximum):
    return (value if type(value) in (int, float)
            and 0 <= value <= maximum else None)


EXCEPTION_TYPES = {name for name, value in vars(builtins).items()
                   if isinstance(value, type) and issubclass(value, BaseException)}
EXCEPTION_TYPES.update({'JSONDecodeError', 'TOMLDecodeError', 'HTTPError', 'URLError',
                        'SSLError', 'SSLCertVerificationError', 'TimeoutError',
                        'ConfigError', 'UnregisteredToolError', 'gaierror', 'IncompleteRead',
                        'RemoteDisconnected', 'HTTPException', 'BadStatusLine', 'SSLEOFError',
                        'SSLZeroReturnError', 'SSLWantReadError', 'SSLWantWriteError'})

SAFE_VALUES = {
    'error_reason': {'port_in_use', 'permission_denied', 'startup_timeout', 'worker_exited',
                     'invalid_configuration', 'process_start_failed', 'worker_error'},
    'error_kind': {'connection_error', 'incomplete_read', 'http_protocol_error', 'timeout',
                   'dns_error', 'tls_certificate_error', 'tls_error', 'connection_refused',
                   'connection_reset', 'broken_pipe'},
    'error_code': {'MODEL_NOT_IN_LIST', 'MODEL_NOT_ALLOWED', 'SUBSCRIPTION_AUTH_REQUIRED', 'STREAM_REQUIRED',
                   'INVALID_REQUEST_OBJECT', 'INVALID_BODY_SIZE', 'GATEWAY_UNREGISTERED_TOOL',
                   'GATEWAY_STREAM_ADAPTATION_FAILED', 'UPSTREAM_STREAM_ENDED_EARLY',
                   'UPSTREAM_PROTOCOL_MISMATCH', 'INVALID_STREAM_PAYLOAD', 'UNSUPPORTED_REASONING_HISTORY',
                   'UNSUPPORTED_SYSTEM_CONTENT', 'UNSUPPORTED_AGENT_MESSAGE_CONTENT'},
    'protocol': {'openai_responses'},
    'route_type': {'official', 'external'},
    'upstream_error_type': {'invalid_request_error', 'authentication_error', 'permission_error',
                           'not_found_error', 'rate_limit_error', 'server_error', 'api_error',
                           'insufficient_quota', 'overloaded_error'},
    'upstream_error_code': {'invalid_api_key', 'insufficient_quota', 'rate_limit_exceeded',
                           'model_not_found', 'context_length_exceeded', 'invalid_request_error'},
}
SAFE_VALUES['error_code'].update(ERROR_MESSAGES)
SAFE_VALUES['upstream_error_code'].add('invalid_request')


def detail_id(raw):
    return hashlib.sha256(raw).hexdigest()


def redact_record(value, depth=0):
    if depth > 12:
        return '[嵌套内容已省略]'
    if isinstance(value, dict):
        sensitive = {'headers', 'authorization', 'api_key', 'apikey', 'token', 'password',
                     'secret', 'credentials', 'settings', 'config', 'input', 'messages',
                     'instructions', 'prompt', 'output', 'arguments', 'encrypted_content'}
        return {key: '[已隐藏]' if key.lower() in sensitive or key.lower().endswith(('_token', '_key', '_secret'))
                else redact_record(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_record(item, depth + 1) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return redact_text(value) if isinstance(value, str) else value


def error_detail(directory, identifier):
    """Locate one retained record by content, with no caller-selected filesystem paths."""
    if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{64}', identifier):
        return None
    for base in ('service.jsonl', 'service.stderr', 'service.startup.stderr'):
        for suffix in ('', '.1', '.2', '.3'):
            source = base + suffix
            try:
                lines = read_records(directory / source)
            except OSError:
                continue
            for index, raw in enumerate(lines):
                if detail_id(raw) != identifier:
                    continue
                if base == 'service.jsonl':
                    try:
                        record = json.loads(raw)
                    except (ValueError, UnicodeError, RecursionError):
                        return None
                    if not isinstance(record, dict) or record.get('status') not in STATUSES:
                        return None
                    return {'source': source, 'line': index + 1, 'record': redact_record(record)}
                # Include the traceback leading up to this exception, stopping at
                # the previous terminal exception. Timestamped stderr is unwrapped.
                block = []
                size = 0
                truncated = False
                for line in reversed(lines[:index + 1]):
                    text = line.decode('utf-8', errors='replace')
                    try:
                        wrapped = json.loads(text)
                        if isinstance(wrapped, dict) and isinstance(wrapped.get('message'), str):
                            text = wrapped['message']
                    except (ValueError, RecursionError):
                        pass
                    match = re.match(r'^([A-Za-z][A-Za-z0-9_]*):(?: |$)', text)
                    if block and match and match[1] in EXCEPTION_TYPES:
                        break
                    size += len(line)
                    if size > 65536:
                        truncated = True
                        break
                    block.append(redact_text(text))
                return {'source': source, 'line': index + 1,
                        'record': '\n'.join(reversed(block)), 'truncated': truncated}
    return None


def safe_details(entry):
    """Only fixed vocabularies and project-owned source locations cross the export boundary."""
    result = {}
    for key, allowed in SAFE_VALUES.items():
        if isinstance(entry.get(key), str) and entry[key] in allowed:
            result[key] = entry[key]
    for key in ('error_type', 'cause_type'):
        if isinstance(entry.get(key), str) and entry[key] in EXCEPTION_TYPES:
            result[key] = entry[key]
    shapes = entry.get('agent_content_shapes')
    allowed_shapes = {'non_object','input_text','text','output_text','other',
                      'encrypted_content:ciphertext','encrypted_content:readable',
                      'encrypted_content:opaque_string','encrypted_content:non_string'}
    if isinstance(shapes, list):
        result['agent_content_shapes'] = sorted({v for v in shapes if isinstance(v, str) and v in allowed_shapes})
    request_id = entry.get('request_id')
    if isinstance(request_id, str) and re.fullmatch(r'[0-9a-f]{32}', request_id):
        result['request_ref'] = hashlib.sha256(request_id.encode()).hexdigest()[:24]
    for key in ('stream', 'proxy_configured', 'spawn_agent_advertised'):
        if type(entry.get(key)) is bool:
            result[key] = entry[key]
    for key in ('errno', 'winerror'):
        value = entry.get(key)
        if type(value) is int and -1000000 <= value <= 1000000:
            result[key] = value
    for key in ('timeout_seconds', 'headers_received_ms', 'unknown_tool_retries'):
        value = number(entry.get(key), 1e12)
        if value is not None:
            result[key] = value
    # Validate against this checkout's source; never trust arbitrary log filenames/functions.
    locations = entry.get('error_locations')
    if isinstance(locations, list):
        safe = []
        root = Path(__file__).resolve().parents[1]
        for location in locations[:32]:
            if not isinstance(location, str):
                continue
            match = re.fullmatch(r'((?:gateway|adapters|model_catalog|management)/[a-z_]+\.py):([1-9][0-9]{0,5})', location)
            if match and (root / match[1]).is_file():
                safe.append(location)
        if safe:
            result['error_locations'] = safe
    return result


def environment():
    try:
        app_version = version('codex-hybrid')
    except PackageNotFoundError:
        app_version = 'unknown'
        try:
            import tomllib
            app_version = tomllib.loads((Path(__file__).resolve().parents[2] / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
        except (OSError, ValueError, KeyError):
            pass
    return {'app_version': app_version, 'os': platform.system(),
            'architecture': platform.machine(), 'python_version': platform.python_version()}


def read_records(path):
    # Scan each retained file from the beginning; memory per source line is bounded.
    lines = []
    with path.open('rb') as stream:
        while True:
            line = stream.readline(65536)
            if not line:
                break
            if len(line) == 65536 and not line.endswith(b'\n'):
                while line and not line.endswith(b'\n'):
                    line = stream.readline(65536)
                continue
            lines.append(line.rstrip(b'\r\n'))
    return lines


def stderr_errors(lines, source, fallback_time=None, include_details=False):
    # Export only known exception names and numeric system codes, never messages,
    # source lines, paths, credentials or traceback contents.
    errors = []
    pending = False
    entry_time = None
    for raw in lines:
        line = raw.decode('utf-8', errors='replace')
        entry_time = None
        try:
            record = json.loads(line)
            if isinstance(record, dict) and isinstance(record.get('message'), str):
                line = record['message']
                entry_time = number(record.get('time'), 1e11)
        except (ValueError, RecursionError):
            pass
        if not line.strip() or set(line.strip()) == {'-'}:
            continue
        pending = True
        match = re.match(r'^([A-Za-z][A-Za-z0-9_]*):(?: |$)', line)
        if match and match[1] in EXCEPTION_TYPES:
            clean = {'status': 'other', 'source': source, 'exception_type': match[1]}
            if include_details:
                clean['detail_id'] = detail_id(raw)
            if entry_time is not None:
                clean['time'] = entry_time
            code = re.search(r'\[(WinError|Errno) ([0-9]{1,6})\]', line)
            if code:
                clean['winerror' if code[1] == 'WinError' else 'errno'] = int(code[2])
            errors.append(clean)
            pending = False
    if pending:
        clean = {'status': 'other', 'source': source}
        if include_details:
            clean['detail_id'] = detail_id(raw)
        if entry_time is not None:
            clean['time'] = entry_time
        errors.append(clean)
    for error in errors:
        if 'time'