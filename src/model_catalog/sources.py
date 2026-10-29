"""External configuration sources, separate from native execution and OpenAI auth."""
import copy
import hashlib
from pathlib import Path

from model_catalog.catalog import Catalog, ConfigError


def load_source(settings):
    source = settings['source']
    if source['type'] == 'yaml':
        catalog = Catalog(source['path'])
    elif source['type'] == 'cc-switch':
        from model_catalog.cc_switch import make_catalog
        catalog = make_catalog(source['path'])
    else:
        raise ConfigError('SOURCE_NOT_SUPPORTED')
    return apply_preferences(catalog, settings)


def source_key(source):
    # Managed YAML is rewritten to a private file; keep its preferences stable.
    identity = 'yaml' if source['type'] == 'yaml' else 'cc-switch:' + str(Path(source['path']).expanduser().resolve())
    return hashlib.sha256(identity.encode()).hexdigest()


def apply_preferences(catalog, settings):
    preferences = settings.get('model_preferences', {}).get(source_key(settings['source']))
    if preferences is None:
        return catalog
    if not isinstance(preferences, dict) or set(preferences) - {'added', 'compatibility'}:
        raise ConfigError('INVALID_MODEL_PREFERENCES')
    added = preferences.get('added', [])
    compatibility = preferences.get('compatibility', {})
    if (not isinstance(added, list) or any(not isinstance(key, str) for key in added)
            or not isinstance(compatibility, dict)
            or any(not isinstance(key, str) or value not in ('native', 'portable')
                   for key, value in compatibility.items())):
        raise ConfigError('INVALID_MODEL_PREFERENCES')
    for key, model in catalog.models.items():
        model['enabled'] = model['source_enabled'] and key in added
        if key in compatibility and model['protocol'] == 'openai_responses':
            model['responses_compatibility'] = compatibility[key]
    if catalog.default_model and not catalog.models[catalog.default_model]['enabled']:
        catalog.default_model = None
    return catalog


def update_cc_snapshot(settings, merged, external):
    """Persist identity bindings with the exact directory that advertised them."""
    if settings['source']['type'] == 'cc-switch':
        settings['cc_snapshot'] = {'models': merged['models'], 'bindings': external.bindings,
                                   'revision': external.source_revision}
    else:
        settings.pop('cc_snapshot', None)


def merged_catalog(official, external):
    """Official entries remain byte-for-byte equivalent; external entries sort last."""
    merged = copy.deepcopy(official)
    reserved = {m['slug'] for m in official}
    template = next((m for m in official if m['slug'] == 'gpt-6-astra'), official[0])
    priority = max((m.get('priority', 0) for m in official), default=0)
    for key, model in external.models.items():
        if not model['enabled']:
            continue
        if key in reserved:
            raise ConfigError('MODEL_NAME_COLLIDES_WITH_OFFICIAL')
        priority += 1
        entry = copy.deepcopy(template)
        entry.update(slug=key, display_name=model['display_name'], visibility='list', priority=priority,
            description='External API · ' + model['provider'], upgrade=None,
            tool_mode=None, shell_type='shell_command', default_reasoning_summary='none',
            context_window=model['context_window'], max_context_window=model['context_window'],
            default_reasoning_level='low', supported_reasoning_levels=[{'effort': 'low', 'description': 'Provider-configured reasoning'}],
            include_skills_usage_instructions=False, include_plugin_usage_instructions=False,
            include_apps_usage_instructions=False,
            model_messages={'instructions_template':
                'You are a coding agent. Follow the assigned task and the current sandbox and approvals. '
                'Use the explicitly assigned worktree for every command and file edit. '
                'For a delegated task with no assigned worktree, ask the parent before editing. '
                'Do not assume the inherited directory is the worker directory.',
                'instructions_variables': {}, 'approvals': None})
        for field in ['service_tiers', 'additional_speed_tiers']:
            if field in entry:
                entry[field] = []
        if 'default_service_tier' in entry:
            entry['default_service_tier'] = None
        merged.append(entry)
    return {'models': merged}
