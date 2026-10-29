"""Small, previewable configuration switch shared by the browser management UI."""
import copy
import json
import re
import tomllib
from pathlib import Path

from desktop.service import PROVIDER, candidate_config, digest, remove_bridge_provider_table
from model_catalog.catalog import ConfigError


ROOT_KEYS = ('model_provider', 'model_catalog_json')


def managed(config):
    return {**{key: config.get(key) for key in ROOT_KEYS},
            'provider': config.get('model_providers', {}).get(PROVIDER)}


def restore(current, baseline):
    """Restore owned fields while retaining unrelated user edits and comments."""
    before = tomllib.loads(current)
    native = tomllib.loads(baseline)
    result, _ = remove_bridge_provider_table(current)
    boundary = re.search(r'^\s*\[', result, re.MULTILINE)
    root, tables = (result[:boundary.start()], result[boundary.start():]) if boundary else (result, '')
    for key in ROOT_KEYS:
        root = re.sub(r'^' + key + r'\s*=.*(?:\n|$)', '', root, flags=re.MULTILINE)
    values = ''.join(f'{key} = {json.dumps(native[key], ensure_ascii=False)}\n'
                     for key in ROOT_KEYS if key in native)
    # An inactive bridge table may have existed before this switch.
    provider = native.get('model_providers', {}).get(PROVIDER)
    if provider is not None:
        # Use the exact generated table syntax, including its original values.
        match = re.search(r'^\[model_providers\.(?:"codex-hybrid"|codex-hybrid)\][^\n]*\n', baseline, re.MULTILINE)
        if not match:
            raise ConfigError('CLIENT_CONFIG_REWRITE_UNSAFE')
        following = re.search(r'^\s*\[', baseline[match.end():], re.MULTILINE)
        end = match.end() + following.start() if following else len(baseline)
        tables += '\n' + baseline[match.start():end]
    # The root/table separators belong to this rewrite. Keep them stable
    # across repeated enable/disable cycles instead of retaining empty lines
    # left by the removed provider table.
    root = root.rstrip('\r\n')
    tables = tables.strip('\r\n')
    result = values + root + ('\n' if root else '') + (tables + '\n' if tables else '')
    expected = copy.deepcopy(before)
    for key in ROOT_KEYS:
        expected.pop(key, None)
        if key in native:
            expected[key] = native[key]
    expected.get('model_providers', {}).pop(PROVIDER, None)
    if provider is not None:
        expected.setdefault('model_providers', {})[PROVIDER] = provider
    if expected.get('model_providers') == {}:
        expected.pop('model_providers')
    if tomllib.loads(result) != expected:
        raise ConfigError('CLIENT_CONFIG_REWRITE_UNSAFE')
    return result


def snapshot(directory, name):
    try:
        return (directory / name).read_bytes().decode('utf-8')
    except (OSError, UnicodeError):
        raise ConfigError('CLIENT_BASELINE_UNAVAILABLE') from None


def prepare(directory, settings, mode):
    if mode not in ('project', 'openai'):
        raise ConfigError('INVALID_ROUTING_MODE')
    state = json.loads((directory / 'state.json').read_text())
    path = Path(state['config_path'])
    current = path.read_bytes().decode('utf-8')
    parsed = tomllib.loads(current)
    provider = parsed.get('model_provider', 'openai')
    if parsed.get('profile') or provider not in ('openai', PROVIDER):
        raise ConfigError('CLIENT_ROUTING_UNAVAILABLE')
    if (provider == PROVIDER) == (mode == 'project'):
        raise ConfigError('CLIENT_ROUTING_ALREADY_SET')
    if mode == 'project':
        baseline = current
        result = candidate_config(current, dict(settings, disable_legacy_plugin=False))
    else:
        baseline = snapshot(directory, 'original-config.toml')
        if digest(baseline.encode()) != state['original_sha256']:
            raise ConfigError('CLIENT_BASELINE_UNAVAILABLE')
        native = tomllib.loads(baseline)
        if native.get('profile') or native.get('model_provider', 'openai') != 'openai':
            raise ConfigError('CLIENT_BASELINE_UNAVAILABLE')
        candidate = snapshot(directory, 'desktop-config.toml')
        if digest(candidate.encode()) != state['candidate_sha256']:
            raise ConfigError('CLIENT_BASELINE_UNAVAILABLE')
        if managed(parsed) != managed(tomllib.loads(candidate)):
            raise ConfigError('CLIENT_CONFIG_CHANGED')
        result = restore(current, baseline)
    return state, path, current, baseline, result
