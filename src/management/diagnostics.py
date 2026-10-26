"""Bounded, allowlisted diagnostics; never export raw configuration or log lines."""
import json
import time


STATUSES = {'rejected', 'incompatible_request_or_stream', 'upstream_connection_failed',
            'upstream_http_error', 'client_disconnected', 'failed', 'incomplete',
            'stream_ended_without_completion'}
PHASES = {'read_request', 'route_request', 'connect_upstream', 'read_upstream', 'write_client', 'adapt_event'}


def number(value, maximum):
    return (value if type(value) in (int, float)
            and 0 <= value <= maximum else None)


def recent_errors(directory):
    path = directory / 'service.jsonl'
    try:
        with path.open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 131072))
            if size > 131072:
                stream.readline(131072)  # Discard a potentially partial first record.
            lines = stream.read(131072).splitlines()
    except FileNotFoundError:
        return {'state': 'missing', 'errors': []}
    except OSError:
        return {'state': 'unavailable', 'errors': []}
    errors = []
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
        errors.append(clean)
    return {'state': 'available', 'errors': errors[-20:]}


def report(manager):
    activity = manager.activity_state()
    started = getattr(manager.gateway, 'started_at', None)
    return {'schema_version': 1, 'generated_at': time.time(),
            'service': {'status': 'running', 'uptime_seconds':
                        max(0, int(time.monotonic() - started)) if started is not None else None},
            'routing_mode': manager.routing_state(), 'activity': activity,
            'log': recent_errors(manager.directory)}
