"""Source-scoped model membership and explicit Responses preferences."""
import hashlib
from pathlib import Path

from infrastructure.errors import ConfigError


def source_key(source):
    # Managed YAML is rewritten to a private file; keep its preferences stable.
    identity = 'yaml' if source['type'] == 'yaml' else 'cc-switch:' + str(Path(source['path']).expanduser().resolve())
    return hashlib.sha256(identity.encode()).hexdigest()


def import_current_cc_record(catalog, preferences, codex_config):
    """Import one matched CC record exactly once into this source's membership."""
    provider_name = codex_config.get('model_provider', 'openai')
    if provider_name in {'openai', 'codex-hybrid'}:
        return False
    imported = preferences.setdefault('imported_records', [])
    if (not isinstance(imported, list)
            or any(not isinstance(value, str) for value in imported)):
        raise ConfigError('INVALID_MODEL_PREFERENCES')
    from model_catalog.cc_switch import match_current_record
    entry = match_current_record(catalog.inventory, codex_config)
    record_ref = entry['ref']
    if record_ref in imported:
        return False
    added = preferences.setdefault('added', [])
    if not isinstance(added, list) or any(not isinstance(value, str) for value in added):
        raise ConfigError('INVALID_MODEL_PREFERENCES')
    added.extend(entry['provider_key'] + '/' + model['model_id'] for model in entry['models'])
    preferences['added'] = sorted(set(added))
    imported.append(record_ref)
    return True


def apply_preferences(catalog, settings):
    preferences = settings.get('model_preferences', {}).get(source_key(settings['source']))
    if preferences is None:
        return catalog
    if not isinstance(preferences, dict) or set(preferences) - {
            'added', 'compatibility', 'adaptations', 'imported_records'}:
        raise ConfigError('INVALID_MODEL_PREFERENCES')
    added = preferences.get('added', [])
    compatibility = preferences.get('compatibility', {})
    adaptations = preferences.get('adaptations', {})
    imported = preferences.get('imported_records', [])
    from adapters.response_schemas import validate_adaptations
    if not isinstance(adaptations, dict):
        raise ConfigError('INVALID_MODEL_PREFERENCES')
    try:
        for key, value in adaptations.items():
            if not isinstance(key, str):
                raise ValueError('INVALID_MODEL_PREFERENCES')
            validate_adaptations(value)
    except ValueError:
        raise ConfigError('INVALID_MODEL_PREFERENCES') from None
    if (not isinstance(added, list) or any(not isinstance(key, str) for key in added)
            or not isinstance(imported, list)
            or any(not isinstance(value, str) for value in imported)
            or not isinstance(compatibility, dict)
            or any(not isinstance(key, str) or value not in ('native', 'portable')
                   for key, value in compatibility.items())):
        raise ConfigError('INVALID_MODEL_PREFERENCES')
    for key, model in catalog.models.items():
        model['enabled'] = model['source_enabled'] and key in added
        if key in compatibility and model['protocol'] == 'openai_responses':
            model['responses_compatibility'] = compatibility[key]
        if key in adaptations and model['protocol'] == 'openai_responses':
            model['responses_adaptations'] = list(adaptations[key])
    if catalog.default_model and not catalog.models[catalog.default_model]['enabled']:
        catalog.default_model = None
    return catalog
