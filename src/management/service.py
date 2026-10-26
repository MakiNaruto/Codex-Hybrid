"""Configuration-only management for the native gateway; no task runner or MCP."""
import copy
import hashlib
import hmac
import json
import os
import re
import tomllib
from pathlib import Path
import secrets
import threading
import urllib.request

import yaml

from model_catalog.sources import Catalog, ConfigError, load_source, merged_catalog
from model_catalog.catalog import identifier, read_yaml, string


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
            out.write(value)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Management:
    def __init__(self, gateway, settings_path, route, sse_events):
        self.gateway = gateway
        self.settings_path = Path(settings_path).resolve()
        self.directory = self.settings_path.parent
        self.route = route
        self.sse_events = sse_events
        self.lock = threading.RLock()
        self.revision_secret = secrets.token_bytes(32)

    def routing_state(self):
        try:
            state = json.loads((self.directory/'state.json').read_text())
            config = tomllib.loads(Path(state['config_path']).read_text())
            if config.get('profile'):
                return 'unsupported'
            provider = config.get('model_provider', 'openai')
            from desktop.service import PROVIDER
            return 'project' if provider == PROVIDER else 'openai' if provider == 'openai' else 'unsupported'
        except (OSError, ValueError, KeyError):
            return 'unavailable'

    def set_routing(self, mode):
        if mode not in ('project', 'openai'):
            raise ConfigError('INVALID_ROUTING_MODE')
        with self.lock:
            from desktop.service import PROVIDER, candidate_config, is_bridge_provider
            if self.routing_state() not in ('project', 'openai'):
                raise ConfigError('CLIENT_ROUTING_UNAVAILABLE')
            state_path = self.directory/'state.json'
            state = json.loads(state_path.read_text())
            path = Path(state['config_path'])
            original = path.read_text()
            parsed = tomllib.loads(original)
            boundary = re.search(r'^\s*\[', original, re.MULTILINE)
            root, tables = (original[:boundary.start()], original[boundary.start():]) if boundary else (original, '')
            for key in ('model_provider', 'model_catalog_json'):
                root = re.sub(r'^' + key + r'\s*=.*(?:\n|$)', '', root, flags=re.MULTILINE)
            if mode == 'project':
                providers = parsed.get('model_providers', {})
                if PROVIDER not in providers:
                    result = candidate_config(original, self.gateway.settings)
                else:
                    if not is_bridge_provider(providers[PROVIDER]):
                        raise ConfigError('CLIENT_CONFIG_REWRITE_UNSAFE')
                    result = (f'model_provider = "{PROVIDER}"\nmodel_catalog_json = '
                              + json.dumps(self.gateway.settings['catalog']) + '\n' + root + tables)
            else:
                result = 'model_provider = "openai"\n' + root + tables
            after = tomllib.loads(result)
            # Verify the root rewrite preserved every unrelated setting.
            providers = parsed.get('model_providers', {})
            if mode == 'openai' or PROVIDER in providers:
                expected = copy.deepcopy(parsed)
                expected['model_provider'] = PROVIDER if mode == 'project' else 'openai'
                expected.pop('model_catalog_json', None)
                if mode == 'project':
                    expected['model_catalog_json'] = self.gateway.settings['catalog']
                if after != expected:
                    raise ConfigError('CLIENT_CONFIG_REWRITE_UNSAFE')
            # Keep CLI activate/rollback snapshots consistent with the UI switch.
            from desktop.service import digest
            private_write(self.directory/('desktop-config.toml' if mode == 'project' else 'original-config.toml'), result)
            state['candidate_sha256' if mode == 'project' else 'original_sha256'] = digest(result.encode())
            state['activated'] = mode == 'project'
            if path.read_text() != original:
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            private_write(path, result)
            private_write(state_path, json.dumps(state))
            return {'saved': True, 'routing_mode': mode, 'restart_client': True}

    def official(self):
        settings = self.gateway.settings
        return [model for model in json.loads(Path(settings['catalog']).read_text())['models']
                if model['slug'] in settings['official_models']]

    def publish(self, source=None, catalog=None, extra=None):
        with self.lock:
            settings = copy.deepcopy(self.gateway.settings)
            if source is not None:
                settings['source'] = source
            if extra:
                settings.update(extra)
            external = catalog if catalog is not None else load_source(settings)
            merged = merged_catalog(self.official(), external)
            settings['models'] = [m['slug'] for m in merged['models']]
            keys = [key for key, value in external.models.items() if value['enabled']]
            if keys:
                settings['deepseek_model'] = keys[0]  # Historical smoke alias only.
            private_write(settings['catalog'], json.dumps(merged, ensure_ascii=False))
            private_write(self.settings_path, json.dumps(settings, ensure_ascii=False))
            self.gateway.settings = settings  # Replace one snapshot; never mutate an in-flight request.
            return {'saved': True, 'restart_client_for_model_list': True}

    def view(self):
        with self.lock:
            settings = self.gateway.settings
            source = settings['source']
            cc_path = settings.get('cc_db_path', str(Path.home()/'.cc-switch/cc-switch.db'))
            mode = 'cc_switch' if source['type'] == 'cc-switch' else 'independent'
            result = {'routing_mode': self.routing_state(), 'mode': mode, 'cc_db_path': source['path'] if mode == 'cc_switch' else cc_path,
                      'config': {'version': 1, 'providers': {}}, 'inventory': [], 'models': [],
                      'source_error': None, 'sync_revision': None, 'catalog_pending': False,
                      'native_routing': True, 'official_model_count': len(settings['official_models'])}
            try:
                catalog = load_source(settings)
                result['models'] = catalog.listing(True)
                if mode == 'independent':
                    result['config'] = read_yaml(source['path'])
                    for provider in result['config']['providers'].values():
                        provider['credentials'].pop('api_key', None)
                else:
                    from model_catalog.cc_switch import inventory
                    entries = inventory(source['path'])
                    result['inventory'] = [{k: v for k, v in entry.items() if not k.startswith('_')}
                                           for entry in entries]
                    versions = [(e['ref'], e['_digest']) for e in entries]
                    result['sync_revision'] = hmac.new(self.revision_secret,
                        json.dumps(versions).encode(), hashlib.sha256).hexdigest()
                result['catalog_pending'] = merged_catalog(self.official(), catalog) != json.loads(
                    Path(settings['catalog']).read_text())
            except Exception as error:
                result['source_error'] = error.code if isinstance(error, ConfigError) else 'SOURCE_UNAVAILABLE'
            return result

    def set_source(self, mode, cc_db_path=None):
        with self.lock:
            settings = self.gateway.settings
            standalone = settings.get('standalone_source')
            if settings['source']['type'] == 'yaml':
                standalone = settings['source']
            if standalone is None:
                standalone = {'type': 'yaml', 'path': str(self.directory / 'models.yaml')}
            if mode == 'independent':
                return self.publish(standalone)
            if mode != 'cc_switch':
                raise ConfigError('INVALID_SOURCE_MODE')
            db = cc_db_path or settings.get('cc_db_path') or str(Path.home()/'.cc-switch/cc-switch.db')
            db = str(Path(string(db)).expanduser().resolve())
            return self.publish({'type': 'cc-switch', 'path': db}, extra={
                'cc_db_path': db, 'standalone_source': standalone})

    def save_provider(self, provider_id, spec=None, api_key=None, delete=False):
        identifier(provider_id)
        if type(delete) is not bool:
            raise ConfigError('INVALID_DELETE_FLAG')
        if api_key is not None and not isinstance(api_key, str):
            raise ConfigError('INVALID_API_KEY')
        with self.lock:
            settings = self.gateway.settings
            if settings['source']['type'] != 'yaml':
                raise ConfigError('CC_MODE_IS_READ_ONLY')
            source_path = Path(settings['source']['path'])
            raw = copy.deepcopy(read_yaml(source_path))
            if delete:
                if provider_id not in raw['providers']:
                    raise ConfigError('PROVIDER_NOT_FOUND')
                del raw['providers'][provider_id]
            else:
                if not isinstance(spec, dict):
                    raise ConfigError('INVALID_PROVIDER_SPEC')
                spec = copy.deepcopy(spec)
                old = raw['providers'].get(provider_id, {})
                env_name = ('CONNECTED_' + provider_id.upper().replace('-', '_').replace('.', '_') + '_'
                            + hashlib.sha256(provider_id.encode()).hexdigest()[:8].upper() + '_KEY')
                spec['credentials'] = old.get('credentials', {'api_key_env': env_name})
                if api_key:
                    string(api_key)
                    spec['credentials'] = {'api_key': api_key}
                raw['providers'][provider_id] = spec
            if raw.get('default_model'):
                provider, alias = raw['default_model'].split('/', 1)
                entry = raw['providers'].get(provider, {})
                if (not entry.get('enabled', True) or alias not in entry.get('models', {})
                        or not entry['models'][alias].get('enabled', True)):
                    raw.pop('default_model', None)
            for provider in raw['providers'].values():
                credentials = provider['credentials']
                if 'env_file' in credentials:
                    credentials['env_file'] = str((source_path.parent/Path(credentials['env_file']).expanduser()).resolve())
            target = self.directory/'managed-models.yaml'
            catalog = Catalog(target, data=raw)
            merged_catalog(self.official(), catalog)  # Validate publication before writing Key/config.
            private_write(target, yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
            return self.publish({'type': 'yaml', 'path': str(target)}, catalog=catalog,
                                extra={'standalone_source': {'type': 'yaml', 'path': str(target)}})

    def test_connection(self, key):
        settings = self.gateway.settings
        if key in settings['official_models']:
            raise ConfigError('EXTERNAL_MODEL_REQUIRED')
        catalog = load_source(settings)
        model, _ = catalog.select(key)
        if key not in settings['models']:
            # A one-off connection test may precede publishing a newly discovered CC model.
            settings = dict(settings, models=[*settings['models'], key])
        body = {'model': key, 'stream': True, 'max_output_tokens': min(model['max_output_tokens'] or 8192, 8192),
                'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': 'Reply with exactly hello and nothing else.'}]}]}
        if not self.gateway.slots.acquire(blocking=False):
            raise ConfigError('CONCURRENCY_LIMIT')
        try:
            url, payload, headers, adapt = self.route(body, {'Authorization': 'Bearer local-management-only'}, settings)
            request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
            with self.gateway.opener.open(request, timeout=60) as response:
                for event in self.sse_events(response):
                    events = adapt(event)
                    if not isinstance(events, list):
                        events = [] if events is None else [events]
                    for item in events:
                        if item.get('type') == 'response.incomplete':
                            reason = item.get('response', {}).get('incomplete_details', {}).get('reason')
                            raise ConfigError('UPSTREAM_OUTPUT_BUDGET_EXHAUSTED' if reason == 'max_output_tokens'
                                              else 'UPSTREAM_INCOMPLETE')
                        if item.get('type') == 'response.completed':
                            # Do not return arbitrary upstream content or errors to the browser.
                            return {'status': 'completed', 'model_key': key, 'model_id': model['model_id']}
            raise ConfigError('UPSTREAM_STREAM_ENDED_EARLY')
        finally:
            self.gateway.slots.release()
