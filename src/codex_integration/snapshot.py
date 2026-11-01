"""Read-only desktop catalog projection. No service/configuration initialization."""
import hashlib
import json
from pathlib import Path

from model_catalog.sources import load_source


def revision(directory, settings_bytes=None):
    if settings_bytes is None:
        settings_bytes = (Path(directory) / 'settings.json').read_bytes()
    settings = json.loads(settings_bytes)
    if settings['source']['type'] != 'yaml':
        return None
    return hashlib.sha256(settings_bytes + b'\0' + Path(settings['source']['path']).read_bytes()).hexdigest()


def editable(settings):
    if settings['source']['type'] != 'yaml':
        return []
    from model_catalog.catalog import read_yaml
    raw = read_yaml(settings['source']['path'])
    return [{'id': key, 'base_url': value['base_url'], 'protocol': value['protocol'],
             'enabled': value.get('enabled', True), 'timeout_seconds': value.get('timeout_seconds', 180),
             'models': [{'alias': alias, 'model_id': model['model_id'],
                         'display_name': model.get('display_name', model['model_id']),
                         'enabled': model.get('enabled', True)} for alias, model in value['models'].items()]}
            for key, value in raw['providers'].items()]


def snapshot(directory=None):
    # Desktop's fixed data location intentionally ignores CLI/environment overrides.
    directory = Path(directory) if directory is not None else Path.home() / '.codex-hybrid'
    result = {'version': 1, 'status': 'not_configured', 'source': None,
              'providers': [], 'models': []}
    try:
        settings_bytes = (directory / 'settings.json').read_bytes()
        settings = json.loads(settings_bytes)
    except FileNotFoundError:
        return result
    except (OSError, ValueError):
        return {**result, 'status': 'unavailable'}
    try:
        source = settings['source']['type']
        before = revision(directory, settings_bytes=settings_bytes)
        catalog = load_source(settings)
        editor = editable(settings)
        if before != revision(directory):
            raise ValueError("Configuration changed during read")
        return {**result, 'status': 'ready', 'source': source,
                'providers': [{'id': key, 'protocol': value['protocol']}
                              for key, value in catalog.providers.items()],
                'models': catalog.listing(include_disabled=True), 'revision': before, 'editable': editor}
    except Exception:
        # Parser/OS errors may contain source excerpts, tokens or private paths.
        return {**result, 'status': 'unavailable'}
