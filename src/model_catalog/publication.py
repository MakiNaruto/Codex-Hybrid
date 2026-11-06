"""Model directory merging and identity snapshots independent of management transport."""
import copy

from infrastructure.errors import ConfigError


def update_cc_snapshot(settings, merged, external):
    """Persist identity bindings with the exact directory that advertised them."""
    if settings['source']['type'] == 'cc-switch':
        settings['cc_snapshot'] = {'models': merged['models'], 'bindings': external.bindings,
                                   'revision': external.source_revision}
    else:
        settings.pop('cc_snapshot', None)


def merged_catalog(official, external, *, include_official=True):
    """Official entries remain byte-for-byte equivalent; external entries sort last."""
    merged = copy.deepcopy(official) if include_official else []
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
            default_reasoning_level='low',
            supported_reasoning_levels=[
                {'effort': 'low', 'description': 'Fast responses with lighter reasoning'},
                {'effort': 'medium', 'description': 'Balances speed and reasoning depth'},
                {'effort': 'high', 'description': 'Greater reasoning depth for complex problems'},
            ],
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
