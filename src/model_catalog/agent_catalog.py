"""Expose the published picker catalog without the backend's five-item preview.

This only changes model-visible descriptions. The native backend still validates
and creates each child using its own complete model registry.
"""
import copy
import json
from pathlib import Path
import re


PREVIEW = re.compile(
    r'(Available model overrides[^\n]*:\s*\n)(?:[ \t]*- `[^\n]*\n?)+')


def model_lines(models):
    lines = []
    for model in models:
        effort = ', '.join(item['effort'] for item in model.get('supported_reasoning_levels', []))
        detail = ' Reasoning efforts: ' + effort + '.' if effort else ''
        tiers = ', '.join(item['id'] for item in model.get('service_tiers', []))
        if tiers:
            detail += ' Service tiers: ' + tiers + '.'
        # Render metadata on one line so it cannot break the list structure.
        label = ' '.join(str(model.get('display_name', model['slug'])).split())
        lines.append(f"- `{model['slug']}`: {label}.{detail}\n")
    return ''.join(lines)


def expose_spawn_catalog(original, settings):
    targets = []

    def visit(tools, namespace=None):
        for tool in tools:
            if tool.get('type') == 'namespace':
                visit(tool.get('tools', []), tool.get('name'))
            elif (tool.get('name') == 'spawn_agent'
                  and namespace in {'collaboration', 'connected_agent_bridge'}):
                targets.append(tool)

    visit(original.get('tools', []))
    for item in original.get('input', []):
        if item.get('type') in {'additional_tools', 'tool_search_output'}:
            visit(item.get('tools', []))
    if not targets:
        return original

    catalog = json.loads(Path(settings['catalog']).read_text())['models']
    allowed = set(settings['models'])
    models = [model for model in catalog
              if model.get('visibility') == 'list' and model['slug'] in allowed]
    listing = model_lines(models)

    def replace(text):
        return PREVIEW.sub(lambda match: match[1] + listing, text)

    request = copy.deepcopy(original)
    # Find the corresponding copied tool objects, leaving the caller's body intact.
    targets.clear()
    visit(request.get('tools', []))
    for item in request.get('input', []):
        if item.get('type') in {'additional_tools', 'tool_search_output'}:
            visit(item.get('tools', []))
    for tool in targets:
        description = tool.get('description', '')
        updated = replace(description)
        if updated == description and not PREVIEW.search(description):
            updated += '\nAvailable model overrides (use the exact registered key):\n' + listing
        tool['description'] = updated
        properties = tool.get('parameters', {}).get('properties', {})
        if 'model' in properties:
            properties['model']['description'] = (
                'Model override: use an exact key from the complete list above. '
                'Display names and upstream API model IDs are not registry keys. '
                'Omit to inherit the parent model.')
    if isinstance(request.get('instructions'), str):
        request['instructions'] = replace(request['instructions'])
    for item in request.get('input', []):
        if item.get('role') in {'developer', 'system'}:
            if isinstance(item.get('content'), str):
                item['content'] = replace(item['content'])
            elif isinstance(item.get('content'), list):
                for part in item['content']:
                    if part.get('type') in {'input_text', 'text'}:
                        part['text'] = replace(part.get('text', ''))
    return request
