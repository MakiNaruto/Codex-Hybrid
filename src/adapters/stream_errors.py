"""Bounded protocol error envelopes for native and portable Responses streams."""
import copy
import time
import uuid

from infrastructure.upstream_errors import diagnostic, ERROR_MESSAGES


def upstream_error(detail, status):
    """Expose bounded diagnostic identifiers, never the provider's echoed message."""
    result = {'message': 'UPSTREAM_HTTP_' + str(status)}
    if not isinstance(detail, dict):
        return result
    for key in ('type', 'code', 'param'):
        value = detail.get(key)
        if (isinstance(value, str) and 0 < len(value) <= 180
                and all(c.isascii() and (c.isalnum() or c in '_.[] -') for c in value)):
            result[key] = value
    identifiers = ', '.join(key + '=' + result[key] for key in ('code', 'param') if key in result)
    if identifiers:
        result['message'] += ': ' + identifiers
    return result


def stream_error_event(event):
    """Translate explicit protocol error envelopes without echoing upstream text."""
    kind = event.get('type', '')
    if kind in {'response.failed', 'response.incomplete'}:
        response = copy.deepcopy(event.get('response', {}))
        if isinstance(response.get('error'), dict):
            code = diagnostic(response['error'])['error_code']
            response['error'] = upstream_error(response['error'], 502)
            response['error']['message'] = code + ': ' + ERROR_MESSAGES[code]
        return dict(event, response=response)
    if kind != 'error' and not event.get('error') and not (
            not kind and 'code' in event and 'message' in event):
        return None
    safe = upstream_error(event.get('error', event), 502)
    code = diagnostic(event.get('error', event))['error_code']
    safe['message'] = code + ': ' + ERROR_MESSAGES[code]
    return {'type': 'response.failed', 'response': {
        'id': 'resp_gateway_' + uuid.uuid4().hex, 'object': 'response',
        'created_at': int(time.time()), 'status': 'failed', 'output': [], 'usage': None, 'error': safe}}
