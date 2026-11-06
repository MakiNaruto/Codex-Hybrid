"""Validate a full local model-preference batch without mutating live settings."""
import copy

from infrastructure.errors import ConfigError
from model_catalog.sources import source_key


def prepare_model_preferences(settings, catalog, updates):
    preferences_by_source = copy.deepcopy(settings.get('model_preferences', {}))
    key = source_key(settings['source'])
    preferences = preferences_by_source.setdefault(key, {
        'added': [key for key, model in catalog.models.items() if model['enabled']], 'compatibility': {}})
    added = set(preferences['added'])
    seen = set()
    for update in updates:
        if (not isinstance(update, dict) or set(update) - {'key', 'added', 'responses_compatibility', 'responses_adaptations'}
                or not isinstance(update.get('key'), str) or update['key'] in seen):
            raise ConfigError('INVALID_MODEL_PREFERENCES')
        model_key = update['key']
        seen.add(model_key)
        if model_key not in catalog.models:
            raise ConfigError('MODEL_NOT_CONFIGURED')
        model = catalog.models[model_key]
        if 'added' in update:
            if type(update['added']) is not bool:
                raise ConfigError('CONFIG_INVALID_ENABLED')
            if update['added']:
                if not model['source_enabled']:
                    raise ConfigError('MODEL_DISABLED_AT_SOURCE')
                added.add(model_key)
            else:
                added.discard(model_key)
        if 'responses_compatibility' in update:
            value = update['responses_compatibility']
            if value not in ('native', 'portable'):
                raise ConfigError('CONFIG_INVALID_RESPONSES_COMPATIBILITY')
            if model['protocol'] != 'openai_responses':
                raise ConfigError('CONFIG_UNSUPPORTED_PROTOCOL_OPTIONS')
            preferences['compatibility'][model_key] = value
        if 'responses_adaptations' in update:
            from adapters.response_schemas import validate_adaptations
            if model['protocol'] != 'openai_responses':
                raise ConfigError('CONFIG_UNSUPPORTED_PROTOCOL_OPTIONS')
            try:
                value = validate_adaptations(update['responses_adaptations'])
            except ValueError:
                raise ConfigError('INVALID_RESPONSES_ADAPTATIONS') from None
            preferences.setdefault('adaptations', {})[model_key] = value
    preferences['added'] = sorted(added)
    return preferences_by_source
