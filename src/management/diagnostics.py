"""Bounded, allowlisted diagnostics; never export raw configuration or log lines."""
import builtins
import hashlib
import platform
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import json
import re
import time


STATUSES = {'rejected', 'incompatible_request_or_stream', 'upstream_connection_failed',
            'upstream_http_error', 'client_disconnected', 'failed', 'incomplete',
            'stream_ended_without_completion'}
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
    'error_kind': {'connection_error', 'incomplete_read', 'http_protocol_error', 'timeout',
                   'dns_error', 'tls_certificate_error', 'tls_error', 'connection_refused',
                   'connection_reset', 'broken_pipe'},
    'error_code': {'MODEL_NOT_ALLOWED', 'SUBSCRIPTION_AUTH_REQUIRED', 'STREAM_REQUIRED',
                   'INVALID_REQUEST_OBJECT', 'INVALID_BODY_SIZE', 'GATEWAY_UNREGISTERED_TOOL',
                   'GATEWAY_STREAM_ADAPTATION_FAILED', 'UPSTREAM_STREAM_ENDED_EARLY'},
    'protocol': {'openai_responses', 'openai_chat_completions'},
    'route_type': {'official', 'external'},
    'upstream_error_type': {'invalid_request_error', 'authentication_error', 'permission_error',
                           'not_found_error', 'rate_limit_error', 'server_error', 'api_error',
                           'insufficient_quota', 'overloaded_error'},
    'upstream_error_code': {'invalid_api_key', 'insufficient_quota', 'rate_limit_exceeded',
                           'model_not_found', 'context_length_exceeded', 'invalid_request_error'},
}


def safe_details(entry):
    """Only fixed vocabularies and project-owned source locations cross the export boundary."""
    result = {}
    for key, allowed in SAFE_VALUES.items():
        if isinstance(entry.get(key), str) and entry[key] in allowed:
            result[key] = entry[key]
    for key in ('error_type', 'cause_type'):
        if isinstance(entry.get(key), str) and entry[key] in EXCEPTION_TYPES:
            result[key] = entry[key]
    request_id = entry.get('request_id')
    if isinstance(request_id, str) and re.fullmatch(r'[0-9a-f]{32}', request_id):
        result['request_ref'] = hashlib.sha256(request_id.encode()).hexdigest()[:24]
    for key in ('stream', 'proxy_configured'):
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


def stderr_errors(lines, source, fallback_time=None):
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
            if entry_time is not None:
                clean['time'] = entry_time
            code = re.search(r'\[(WinError|Errno) ([0-9]{1,6})\]', line)
            if code:
                clean['winerror' if code[1] == 'WinError' else 'errno'] = int(code[2])
            errors.append(clean)
            pending = False
    if pending:
        clean = {'status': 'other', 'source': source}
        if entry_time is not None:
            clean['time'] = entry_time
        errors.append(clean)
    for error in errors:
        if 'time' not in error and fallback_time is not None:
            error.update(time=fallback_time, time_source='file_modified')
    return errors


def recent_errors(directory, days=None, now=None):
    if days not in (None, 1, 7, 30):
        raise ValueError("Unsupported diagnostic period")
    now = time.time() if now is None else now
    cutoff = now - days * 86400 if days is not None else None
    errors = []
    found = False
    unavailable = False
    for base in ('service.jsonl', 'service.stderr', 'service.startup.stderr'):
        # Runtime rotation retains three backups. Read old to new within each source.
        for suffix in ('.3', '.2', '.1', ''):
            source = base + suffix
            try:
                lines = read_records(directory / source)
                modified = (directory / source).stat().st_mtime
                found = True
            except FileNotFoundError:
                continue
            except OSError:
                unavailable = True
                continue
            if base != 'service.jsonl':
                errors.extend(stderr_errors(lines, source, modified))
                continue
            for line in lines:
                try:
                    entry = json.loads(line)
                except (ValueError, UnicodeError, RecursionError):
                    continue
                if (not isinstance(entry, dict) or not isinstance(entry.get('status'), str)
                        or entry['status'] not in STATUSES):
                    continue
                clean = {'status': entry['status']}
                clean.update(safe_details(entry))
                if isinstance(entry.get('phase'), str) and entry['phase'] in PHASES:
                    clean['phase'] = entry['phase']
                for field, maximum in [('time', 1e11), ('elapsed_ms', 1e12), ('http_status', 599)]:
                    value = number(entry.get(field), maximum)
                    if value is not None:
                        clean[field] = value
                if 'time' not in clean:
                    clean.update(time=modified, time_source='file_modified')
                errors.append(clean)
    if cutoff is not None:
        errors = [entry for entry in errors if cutoff <= entry.get('time', 0) <= now]
    errors.sort(key=lambda entry: entry.get('time', 0), reverse=True)
    # Legacy records share a file timestamp; merge identical safe summaries only.
    grouped = []
    legacy = {}
    for entry in errors:
        if entry.get('time_source') != 'file_modified':
            grouped.append(entry)
            continue
        key = tuple(sorted(entry.items()))
        if key in legacy:
            previous = legacy[key]
            previous['count'] = previous.get('count', 1) + 1
        else:
            legacy[key] = entry
            grouped.append(entry)
    errors = grouped
    state = 'partial' if unavailable and found else 'unavailable' if unavailable else 'available' if found else 'missing'
    result = {'state': state, 'errors': errors,
              'coverage': {'retained_files_only': True, 'rotation_may_remove_history': True,
                           'includes_successful_requests': False, 'read_failed': unavailable}}
    return result


def report(manager, days=1):
    activity = manager.activity_state()
    started = getattr(manager.gateway, 'started_at', None)
    now = time.time()
    return {'schema_version': 2, 'generated_at': now, 'period_days': days,
            'environment': environment(),
            'service': {'status': 'running', 'uptime_seconds':
                        max(0, int(time.monotonic() - started)) if started is not None else None},
            'routing_mode': manager.routing_state(), 'activity': activity,
            'log': recent_errors(manager.directory, days=days, now=now)}
