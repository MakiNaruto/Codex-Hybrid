"""Read-only adapter for CC Switch 3.20.x provider records. Never writes its DB."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from model_catalog.catalog import Catalog, ConfigError


def configuration_digest(raw, meta):
    return hashlib.sha256(json.dumps([raw, meta]).encode()).hexdigest()


def _normalized_provider(provider):
    if not isinstance(provider, dict):
        return None
    base_url = provider.get('base_url')
    if not isinstance(base_url, str) or not base_url:
        return None
    wire_api = provider.get('wire_api', 'responses')
    if wire_api != 'responses':
        return None
    # Codex and CC Switch intentionally differ on credential delivery fields:
    # CC Switch may leave requires_openai_auth in the record while writing an
    # experimental bearer token and disabling that flag in the live config.
    return {
        'base_url': base_url.rstrip('/'),
        'wire_api': wire_api,
        'responses_compatibility': provider.get(
            'responses_compatibility', 'native'),
        'history_migration': provider.get('history_migration', False),
    }


def match_current_record(entries, config):
    """Resolve one supported CC record from the authoritative Codex config."""
    if not isinstance(config, dict) or config.get('profile'):
        raise ConfigError('CLIENT_ROUTING_UNAVAILABLE')
    provider_name = config.get('model_provider', 'openai')
    providers = config.get('model_providers', {})
    provider = providers.get(provider_name) if isinstance(providers, dict) else None
    target = _normalized_provider(provider)
    if target is None:
        raise ConfigError('CC_ROUTING_PROVIDER_UNMATCHED')
    matches = [
        entry for entry in entries
        if entry.get('supported') and _normalized_provider(entry.get('_provider_config')) == target
    ]
    if not matches:
        raise ConfigError('CC_ROUTING_PROVIDER_UNMATCHED')
    if len(matches) > 1:
        raise ConfigError('CC_ROUTING_PROVIDER_AMBIGUOUS')
    return matches[0]


def connect(path):
    connection = sqlite3.connect(Path(path).expanduser().resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    connection.execute('PRAGMA query_only=ON')
    return connection


def decode(app, raw, meta=None):
    settings = json.loads(raw)
    if app != 'codex':
        raise ConfigError('CC_PROTOCOL_NOT_SUPPORTED')
    cfg = settings.get('config', '')
    cfg = tomllib.loads(cfg) if isinstance(cfg, str) else cfg
    provider = cfg.get('model_providers', {}).get(cfg.get('model_provider'), {})
    if not provider:
        raise ConfigError('CC_OFFICIAL_LOGIN_NOT_SUPPORTED')
    if provider.get('http_headers'):
        raise ConfigError('CC_CUSTOM_HEADERS_NOT_SUPPORTED')
    wire = provider.get('wire_api', 'responses')
    if wire != 'responses':
        raise ConfigError('CC_PROTOCOL_NOT_SUPPORTED')
    protocol = 'openai_responses'
    auth = settings.get('auth', {})
    if isinstance(auth, str):
        auth = json.loads(auth)
    key = auth.get('OPENAI_API_KEY')
    if not isinstance(key, str) or not key.strip():
        raise ConfigError('CC_STATIC_API_KEY_REQUIRED')
    configured = cfg.get('model')
    source_models = settings.get('modelCatalog', {}).get('models', [])
    models = {}
    if isinstance(configured, str) and configured:
        models[configured] = {'model_id': configured}
    for item in source_models:
        if not isinstance(item, dict) or not isinstance(item.get('model'), str) or not item['model']:
            continue
        model = item['model']
        models[model] = {'model_id': model, 'display_name': item.get('displayName') or model,
            'context_window': item.get('contextWindow'), 'max_output_tokens': item.get('maxOutputTokens')}
    for model in models.values():
        for key_name, fallback in [('context_window', cfg.get('model_context_window')),
                                    ('max_output_tokens', cfg.get('model_max_output_tokens'))]:
            value = model.get(key_name)
            if value is None:
                value = fallback
            model[key_name] = value if type(value) is int and value > 0 else None
        model.setdefault('display_name', model['model_id'])
    metadata = json.loads(meta) if isinstance(meta, str) else (meta or {})
    api_format = metadata.get('apiFormat')
    if api_format is not None:
        if api_format != 'openai_responses':
            raise ConfigError('CC_PROTOCOL_NOT_SUPPORTED')
    return {'protocol': protocol, 'base_url': provider.get('base_url'), 'provider_config': provider,
            'responses_compatibility': provider.get('responses_compatibility', 'native'),
            'history_migration': provider.get('history_migration', False),
            'models': list(models.values()), 'key': key}


def inventory(path, *, strict=False):
    result = []
    try:
        with closing(connect(path)) as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(providers)').fetchall()}
            current = 'is_current' if 'is_current' in columns else '0'
            rows = db.execute(
                "SELECT id,app_type,name,settings_config,meta,"
                f"{current} FROM providers WHERE app_type='codex' ORDER BY sort_index,created_at,id"
            ).fetchall()
    except sqlite3.Error:
        raise ConfigError('CC_DATABASE_UNAVAILABLE') from None
    for identifier, app, name, raw, meta, is_current in rows:
        ref = app + '/' + identifier
        entry = {'ref': ref, 'provider_record_id': identifier, 'provider_key': identifier,
                 'name': name, 'app_type': app, 'is_current': bool(is_current),
                 'supported': False, 'reason': None}
        try:
            parsed = decode(app, raw, meta)
            if not parsed['models']:
           