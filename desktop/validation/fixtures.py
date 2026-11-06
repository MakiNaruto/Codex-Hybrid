"""Temporary validation fixtures, with no production directory defaults."""
import hashlib
import json


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def fixture(directory, port):
    (directory / 'stage0-fixture.marker').touch()
    original = 'model = "fixture-official"\n'
    config = directory / 'codex-config.toml'
    config.write_text(original, encoding='utf-8')
    (directory / 'models.yaml').write_text('version: 1\nproviders: {}\n', encoding='utf-8')
    write_json(directory / 'models.json', {'models': [{'slug': 'fixture-official', 'priority': 1}]})
    write_json(directory / 'models_cache.json', {'models': [{'slug': 'fixture-official', 'priority': 1}]})
    write_json(directory / 'state.json', {
        'config_path': str(config), 'activated': False,
        'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
    })
    settings_path = directory / 'settings.json'
    write_json(settings_path, {
        'port': port, 'catalog': str(directory / 'models.json'),
        'source': {'type': 'yaml', 'path': str(directory / 'models.yaml')},
        'official_models': ['fixture-official'], 'models': ['fixture-official'],
        'local_token': 'stage0-local-fake-token', 'management_token': 'stage0-management-fake-token',
        'management_auth_required': True,
    })
    return settings_path
