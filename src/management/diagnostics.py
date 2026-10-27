"""Bounded, allowlisted diagnostics; never export raw configuration or log lines."""
import builtins
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
                        'SSLError', 'SSLCertVerificationError', 'TimeoutError'})


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
    result = {'state': state, 'errors': errors}
    return result


def report(manager, days=1):
    activity = manager.activity_state()
    started = getattr(manager.gateway, 'started_at', None)
    now = time.time()
    return {'schema_version': 1, 'generated_at': now, 'period_days': days,
            'service': {'status': 'running', 'uptime_seconds':
                        max(0, int(time.monotonic() - started)) if started is not None else None},
            'routing_mode': manager.routing_state(), 'activity': activity,
            'log': recent_errors(manager.directory, days=days, now=now)}
