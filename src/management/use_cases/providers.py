"""Prepare isolated provider documents and local model preferences before publication."""
import copy
import hashlib
from pathlib import Path

from infrastructure.errors import ConfigError
from model_catalog.catalog import string
from model_catalog.sources import source_key


def prepare_provider_document(raw, source_path, provider_id, spec=None, api_key=None, delete=False):
    raw = copy.deepcopy(raw)
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
    return raw, {} if delete else old.get('models', {})


def prepare_provider_preferences(settings, catalog, current_catalog, provider_id, models, previous_models):
    preferences = copy.deepcopy(settings.get('model_preferences', {}))
    preference_key = source_key(settings['source'])
    preference = preferences.setdefault(preference_key, {
        'added': [key for key, model in current_catalog.models.items() if model['enabled']],
        'compatibility': {}})
    for alias, model in models.items():
        if alias not in previous_models and model.get('enabled', True):
            preference['added'].append(provider_id + '/' + alias)
    preference['added'] = sorted(set(preference['added']) & set(catalog.models))
    return preferences
