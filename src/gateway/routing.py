"""Request routing and request-scoped protocol adapter selection."""
import os

from adapters.coordination import plaintext_collaboration_schema, NativeCoordinationAdapter
from adapters.minimal_responses import MinimalResponsesAdapter
from adapters.native_responses import NativeResponsesAdapter
from adapters.history import normalize_history
from adapters.context import external_context
from adapters.responses import ResponsesAdapter
from model_catalog.agent_catalog import expose_spawn_catalog
from model_catalog.catalog import ConfigError, resolve_api_key
from model_catalog.sources import load_source

OPENAI_URL = 'https://chatgpt.com/backend-api/codex/responses'
MAX_BODY = 32 * 1024 * 1024

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


def official_headers(headers, settings, accept='text/event-stream'):
    outgoing = {'Accept': accept}
    if official_header_passthrough(settings):
        for name, value in headers.items():
            if name.lower() not in OFFICIAL_HEADER_DENY:
                outgoing[name] = value
    else:
        for name in ['Authorization', 'ChatGPT-Account-ID', 'OpenAI-Beta',
                     'OpenAI-Organization', 'OpenAI-Project', 'User-Agent',
                     'Originator', 'Version', 'Session_ID',
                     'X-Codex-Turn-Metadata', 'X-Codex-Beta-Features']:
            if headers.get(name):
                outgoing[name] = headers[name]
    return outgoing


def resolve_requested_model(model, settings):
    """Map a legacy direct-provider ID to an unambiguous published key.

    Codex stores the model from the session instead of re-reading the current
    catalog. Sessions created under a direct CC Switch provider therefore carry
    the vendor's raw model ID, while the Hybrid catalog uses record-qualified
    keys. Resolve only an unambiguous enabled match; never pick between records.
    """
    if not isinstance(model, str) or not model:
        return None, None
    allowed = settings.get('models') or ()
    if model in allowed:
        return model, None
    source = settings.get('source')
    if not source:
        return None, None
    bindings = settings.get('cc_snapshot', {}).get('bindings')
    if source.get('type') == 'cc-switch' and isinstance(bindings, dict):
        candidates = [(key, entry.get('model_id')) for key, entry in bindings.items()
                      if isinstance(entry, dict) and key in allowed]
    else:
        catalog = load_source(settings)
        candidates = [(key, entry.get('model_id'))
                      for key, entry in catalog.models.items()
                      if entry.get('enabled') and key in allowed]
    matches = [key for key, model_id in candidates if model_id == model]
    if len(matches) == 1:
        return matches[0], 'legacy_alias'
    return None, None


def external_route(body, settings):
    """Resolve a live external model and build its protocol-specific request."""
    model = body.get('model')
    catalog = load_source(settings)  # Fresh address, model and credentials every request.
    if settings['source']['type'] == 'cc-switch':
        binding = settings.get('cc_snapshot', {}).get('bindings', {}).get(model)
        if binding is None or catalog.bindings.get(model) != binding:
            raise ConfigError('MODEL_NOT_CONFIGURED')
    selected, provider = catalog.select(model)
    coordination = NativeCoordinationAdapter(
        set(settings['models']) - set(settings['official_models']))
    native = provider.get('responses_compatibility', 'native') == 'native'
    if native:
        adaptations = provider.get('responses_adaptations', [])
        adapter = (MinimalResponsesAdapter(adaptations, history_migration=provider.get('history_migration', False))
                   if adaptations else NativeResponsesAdapter(history_migration=provider.get('history_migration', False)))
    else:
        adapter = ResponsesAdapter()
    adapter.timeout_seconds = provider['timeout_seconds']
    advertised = expose_spawn_catalog(body, settings)
    converted = adapter.request(advertised if native else external_context(advertised, selected))
    payload = converted if native else {key: value for key, value in converted.items()
               if key in {'model', 'input', 'instructions', 'tools', 'stream'}}
    adapt = adapter.stream_events if native else coordinated(adapter.stream_events, coordination)
    # Provider settings may extend a request but never replace routing
    # instructions or the bridge's no-storage policy.
    payload.update({key: value for key, value in selected['parameters'].items()
                    if key not in {'store', 'instructions'}})
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
        payload['max_output_tokens'] = min(budget, selected['max_output_tokens']) if configured_limit else budget
    return provider['endpoint'], payload, {
        'Authorization': 'Bearer ' + resolve_api_key(provider),
        'Content-Type': 'application/json', 'Accept': 'text/event-stream'}, adapt


def route(body, headers, settings, deepseek=None):
    """Build each request with fresh, vendor-specific headers and adapter state."""
    model = body.get('model')
    if model not in settings['models']:
        resolved, _ = resolve_requested_model(model, settings)
        if resolved is None:
            raise ConfigError('MODEL_NOT_IN_LIST')
        # Keep the caller's body immutable while routing the canonical key.
        body = {**body, 'model': resolved}
        model = resolved
    if body.get('stream') is not True:
        raise ValueError('STREAM_REQUIRED')
    if 'source' in settings and model not in settings['official_models']:
        # External providers use their own credentials. Codex may access the
        # local bridge without an OpenAI subscription login in this mode.
        return external_route(body, settings)
    auth = headers.get('Authorization', '')
    if not auth.startswith('Bearer ') or len(auth) < 16:
        raise ValueError('SUBSCRIPTION_AUTH_REQUIRED')
    if 'source' not in settings and model == deepseek['DEEPSEEK_MODEL']:
        adapter = NativeResponsesAdapter()
        payload = adapter.request(body)
        payload['store'] = False
        budget = body.get('max_output_tokens', settings['deepseek_max_output_tokens'])
        if type(budget) is not int or budget <= 0:
            raise ValueError('INVALID_OUTPUT_BUDGET')
        payload['max_output_tokens'] = min(budget, settings['deepseek_max_output_tokens'])
        return (deepseek['DEEPSEEK_BASE_URL'] + '/responses', payload,
                {'Authorization': 'Bearer ' + deepseek['DEEPSEEK_API_KEY'],
                 'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
                adapter.stream_events)
    body = expose_spawn_catalog(body, settings)
    # Never forward the local access token, cookies, arbitrary destination or host.
    outgoing = official_headers(headers, settings)
    outgoing['Content-Type'] = 'application/json'
    external_models = (set(settings['models']) - set(settings['official_models'])
                       if 'source' in settings else deepseek['DEEPSEEK_MODEL'])
    return OPENAI_URL, normalize_history(plaintext_collaboration_schema(body)), outgoing, NativeCoordinationAdapter(external_models).event
