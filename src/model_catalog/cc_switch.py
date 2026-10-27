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
    protocol = {'responses': 'openai_responses', 'chat': 'openai_chat_completions'}.get(wire)
    if protocol is None:
        raise ConfigError('CC_PROTOCOL_NOT_SUPPORTED')
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
        protocol = {'openai_chat': 'openai_chat_completions',
                    'openai_responses': 'openai_responses'}.get(api_format)
        if protocol is None:
            raise ConfigError('CC_PROTOCOL_NOT_SUPPORTED')
    return {'protocol': protocol, 'base_url': provider.get('base_url'),
            'models': list(models.values()), 'key': key}


def inventory(path, *, strict=False):
    result = []
    try:
        with closing(connect(path)) as db:
            rows = db.execute("SELECT id,app_type,name,settings_config,meta FROM providers WHERE app_type='codex' ORDER BY sort_index,created_at,id").fetchall()
    except sqlite3.Error:
        raise ConfigError('CC_DATABASE_UNAVAILABLE') from None
    for identifier, app, name, raw, meta in rows:
        ref = app + '/' + identifier
        entry = {'ref': ref, 'provider_record_id': identifier, 'provider_key': identifier,
                 'name': name, 'app_type': app, 'supported': False, 'reason': None}
        try:
            parsed = decode(app, raw, meta)
            if not parsed['models']:
                continue
            entry.update(protocol=parsed['protocol'], base_url=parsed['base_url'], models=parsed['models'])
            # Reuse endpoint/model validation without exposing the credential.
            Catalog(Path(path).parent / 'cc-validation.yaml', data={'version': 1, 'providers': {
                'check': {'protocol': parsed['protocol'], 'base_url': parsed['base_url'],
                    'credentials': {'api_key_env': 'UNUSED'}, 'models': {
                        model['model_id']: {'model_id': model['model_id']}
                        for model in parsed['models']}}}}, source_identifiers=True)
            entry['supported'] = True
        except ConfigError as error:
            if strict and error.code not in {
                    'CC_OFFICIAL_LOGIN_NOT_SUPPORTED', 'CC_CUSTOM_HEADERS_NOT_SUPPORTED',
                    'CC_PROTOCOL_NOT_SUPPORTED'}:
                raise
            entry['reason'] = error.code
        except Exception:
            if strict:
                raise ConfigError('CC_CONFIG_INVALID') from None
            entry['reason'] = 'CC_CONFIG_INVALID'
        entry['_digest'] = configuration_digest(raw, meta)
        # Never show even an invalid URL to a client: it might contain a token query.
        if not entry['supported']:
            continue
        result.append(entry)
    return result


def selected_key(path, entry):
    app, identifier = entry['ref'].split('/', 1)
    try:
        with closing(connect(path)) as db:
            row = db.execute('SELECT settings_config,meta FROM providers WHERE id=? AND app_type=?', (identifier, app)).fetchone()
    except sqlite3.Error:
        raise ConfigError('CC_DATABASE_UNAVAILABLE') from None
    if not row or configuration_digest(*row) != entry['_digest']:
        raise ConfigError('CC_CONFIG_CHANGED_RELOAD')
    return decode(app, *row)['key']


def make_catalog(path):
    entries = inventory(path, strict=True)
    providers, refs = {}, {}
    for entry in entries:
        if not entry['supported']:
            continue
        key = entry['provider_key']
        models = {}
        for source_model in entry['models']:
            alias = source_model['model_id']
            models[alias] = {'model_id': source_model['model_id'],
                'display_name': entry['name']+' · '+source_model['display_name'],
                'max_output_tokens': source_model['max_output_tokens'], 'enabled': True}
            if source_model['context_window'] is not None:
                models[alias]['context_window'] = source_model['context_window']
        providers[key] = {'protocol': entry['protocol'], 'base_url': entry['base_url'],
                         'credentials': {'api_key_env': 'CC_READONLY_KEY'}, 'models': models}
        refs[key] = entry
    data = {'version': 1, 'providers': providers}
    catalog = Catalog(Path(path).parent / 'cc-readonly.yaml', data=data, source_identifiers=True)
    catalog.bindings = {
        slug: {'provider_record_id': model['provider'], 'app_type': refs[model['provider']]['app_type'],
               'model_id': model['model_id']}
        for slug, model in catalog.models.items()}
    catalog.inventory = entries
    catalog.source_revision = configuration_digest(
        str(Path(path).expanduser().resolve()), [(entry['ref'], entry['name'], entry['_digest']) for entry in entries])
    for key, provider in catalog.providers.items():
        entry = refs[key]
        provider['key_resolver'] = lambda entry=entry: selected_key(path, entry)
    return catalog
