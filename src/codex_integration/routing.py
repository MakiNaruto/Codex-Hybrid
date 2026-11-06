"""Small, previewable configuration switch shared by the browser management UI."""
import hashlib
import hmac
import json
import tomllib
from pathlib import Path

from codex_integration.configuration import PROVIDER, candidate_config, digest, managed, restore
from model_catalog.catalog import ConfigError
from model_catalog.cc_switch import match_current_record
from model_catalog.sources import load_source


def snapshot(directory, name):
    try:
        return (directory / name).read_bytes().decode('utf-8')
    except (OSError, UnicodeError):
        raise ConfigError('CLIENT_BASELINE_UNAVAILABLE') from None


def _external_record(settings, config):
    provider = config.get('model_provider', 'openai')
    if provider in {'openai', PROVIDER}:
        return None
    source = settings.get('source', {})
    if source.get('type') != 'cc-switch':
        raise ConfigError('CLIENT_ROUTING_UNAVAILABLE')
    catalog = load_source(settings)
    return match_current_record(catalog.inventory, config)


def validate_baseline(directory, settings):
    """Reject unsupported direct configurations before publishing membership."""
    state = json.loads((directory / 'state.json').read_text())
    current = Path(state['config_path']).read_bytes().decode('utf-8')
    parsed = tomllib.loads(current)
    if parsed.get('profile'):
        raise ConfigError('CLIENT_ROUTING_UNAVAILABLE')
    _external_record(settings, parsed)


def prepare(directory, settings, mode):
    if mode not in ('project', 'openai'):
        raise ConfigError('INVALID_ROUTING_MODE')
    state = json.loads((directory / 'state.json').read_text())
    path = Path(state['config_path'])
    current = path.read_bytes().decode('utf-8')
    parsed = tomllib.loads(current)
    provider = parsed.get('model_provider', 'openai')
    if parsed.get('profile'):
        raise ConfigError('CLIENT_ROUTING_UNAVAILABLE')
    if mode == 'project':
        _external_record(settings, parsed)
    elif provider not in ('openai', PROVIDER):
        # Never overwrite a direct configuration that replaced an active bridge.
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
        if native.get('profile') or native.get('model_provider', 'openai') == PROVIDER:
            raise ConfigError('CLIENT_BASELINE_UNAVAILABLE')
        candidate = snapshot(directory, 'desktop-config.toml')
        if digest(candidate.encode()) != state['candidate_sha256']:
            raise ConfigError('CLIENT_BASELINE_UNAVAILABLE')
        if managed(parsed) != managed(tomllib.loads(candidate)):
            raise ConfigError('CLIENT_CONFIG_CHANGED')
        result = restore(current, baseline)
    return state, path, current, baseline, result


def plan(directory, settings, mode, revision_secret):
    """Bind the config rewrite and session migration to one preview revision."""
    state, path, current, baseline, result = prepare(directory, settings, mode)
    from codex_integration.session_migration import plan as plan_migration
    provider = ('codex-hybrid' if mode == 'project'
                else tomllib.loads(baseline).get('model_provider', 'openai'))
    migration = plan_migration(path.parent, settings, provider, best_effort=True)
    revision = hmac.new(revision_secret,
        json.dumps([mode, str(path), state, current, baseline, result, migration['revision']]).encode(),
        hashlib.sha256).hexdigest()
    return state, path, current, baseline, result, migration, revision


def commit(directory, settings, mode, revision_secret, revision, confirm_activity=False):
    """Commit config, recovery metadata and indexes as one recoverable operation.

    The caller must hold its ConfigurationLock through planning and commit.
    Desktop shutdown/startup and forwarding waits stay outside this transaction.
    """
    if type(confirm_activity) is not bool:
        raise ConfigError('INVALID_ACTIVITY_CONFIRMATION')
    controls = {directory/name: ((directory/name).read_bytes()
                if (directory/name).exists() else None)
                for name in ('state.json', 'original-config.toml', 'desktop-config.toml')}
    state, path, current, baseline, result, migration, expected = plan(directory, settings, mode, revision_secret)
    if not isinstance(revision, str) or not hmac.compare_digest(revision, expected):
        raise ConfigError('CLIENT_CONFIG_CHANGED')
    if path.read_bytes().decode('utf-8') != current:
        raise ConfigError('CLIENT_CONFIG_CHANGED')
    from codex_integration.session_migration import apply, log_warnings
    updates = {}

    def update(file, value):
        file = Path(file)
        updates[file] = (controls[file], value.encode())

    # Routing config, recovery metadata and thread indexes form one recoverable operation.
    if mode == 'project':
        update(directory/'original-config.toml', baseline)
        state['original_sha256'] = digest(baseline.encode())
        update(directory/'desktop-config.toml', result)
        state['candidate_sha256'] = digest(result.encode())
    else:
        update(directory/'original-config.toml', result)
        state['original_sha256'] = digest(result.encode())
    state['activated'] = mode == 'project'
    update(directory/'state.json', json.dumps(state))
    updates[path] = (current.encode(), result.encode())
    warning_log = log_warnings(migration, directory)
    backup = apply(migration, directory, updates,
                   allow_running=confirm_activity)
    return {'saved': True, 'routing_mode': mode, 'restart_client': True,
            'session_count': migration['count'], 'model_change_count': migration['model_change_count'],
            'index_repair_count': len(migration['unindexed']) or migration['index_repair_count'],
            'session_backup': backup, 'warnings': migration['warnings'],
            'warning_log': warning_log}
