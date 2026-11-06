"""Explicit connection testing through the same routing and transport as generation."""
import copy
import json
import time
import urllib.request

from infrastructure.errors import ConfigError
from model_catalog.sources import load_source, source_key


def test_connection(context, route, sse_events, key):
    began = time.monotonic()
    settings = context.settings
    if key in settings['official_models']:
        raise ConfigError('EXTERNAL_MODEL_REQUIRED')
    if settings['source']['type'] == 'cc-switch':
        settings = copy.deepcopy(settings)
        # Membership controls the client directory, not source connection tests.
        preference = settings.get('model_preferences', {}).get(source_key(settings['source']))
        if preference is not None:
            preference['added'] = [*preference.get('added', []), key]
    catalog = load_source(settings)
    if settings['source']['type'] == 'cc-switch':
        # Test the selected live configuration without publishing a partial directory.
        settings['cc_snapshot'] = {'bindings': catalog.bindings}
    model, _ = catalog.select(key)
    if key not in settings['models']:
        # A one-off connection test may precede publishing a newly discovered CC model.
        settings = dict(settings, models=[*settings['models'], key])
    body = {'model': key, 'stream': True, 'max_output_tokens': min(model['max_output_tokens'] or 8192, 8192),
            'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Reply with exactly hello and nothing else.'}]}]}
    url, payload, headers, adapt = route(body, {'Authorization': 'Bearer local-management-only'}, settings)
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with context.opener.open(request, timeout=60) as response:
        for event in sse_events(response):
            events = adapt(event)
            if not isinstance(events, list):
                events = [] if events is None else [events]
            for item in events:
                if item.get('type') == 'response.failed':
                    raise ConfigError('UPSTREAM_STREAM_ERROR')
                if item.get('type') == 'response.incomplete':
                    reason = item.get('response', {}).get('incomplete_details', {}).get('reason')
                    raise ConfigError('UPSTREAM_OUTPUT_BUDGET_EXHAUSTED' if reason == 'max_output_tokens'
                                      else 'UPSTREAM_INCOMPLETE')
                if item.get('type') == 'response.completed':
                    # Do not return arbitrary upstream content or errors to the browser.
                    return {'status': 'completed', 'model_key': key, 'model_id': model['model_id'],
                            'elapsed_ms': round((time.monotonic() - began) * 1000)}
    raise ConfigError('UPSTREAM_STREAM_ENDED_EARLY')
