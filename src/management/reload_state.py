"""User acknowledgement of a manual Codex reload; never claim process verification."""
import hashlib
import hmac
import json
from pathlib import Path


def status(manager):
    try:
        state = json.loads((manager.directory / 'state.json').read_text())
        config = Path(state['config_path']).read_bytes()
        catalog = Path(manager.gateway.settings['catalog']).read_bytes()
        secret = manager.gateway.settings['local_token'].encode()
        revision = hmac.new(secret, config + b'\0' + catalog, hashlib.sha256).hexdigest()
    except (OSError, ValueError, KeyError, TypeError):
        return {'available': False, 'required': None, 'revision': None}
    try:
        saved = json.loads((manager.directory / 'web-reload.json').read_text())
        acknowledged = saved.get('acknowledged_revision')
    except (OSError, ValueError, AttributeError):
        acknowledged = None
    # Initial native installations have nothing to acknowledge. Once active, any
    # config/catalog change remains visible across reloads and gateway restarts.
    required = acknowledged != revision and (
        acknowledged is not None or manager.routing_state() == 'project')
    return {'available': True, 'required': required, 'revision': revision}


def remember_before_change(manager):
    """Capture the old revision on first edit so disabling also prompts a reload."""
    from management.service import private_write
    path = manager.directory / 'web-reload.json'
    current = status(manager)
    if not path.exists() and current['available']:
        private_write(path, json.dumps({'acknowledged_revision': current['revision']}))


def acknowledge(manager, revision):
    from management.service import private_write
    from model_catalog.catalog import ConfigError
    current = status(manager)
    if not isinstance(revision, str) or not current['available'] or not hmac.compare_digest(revision, current['revision']):
        raise ConfigError('CLIENT_RELOAD_STATE_CHANGED')
    private_write(manager.directory / 'web-reload.json', json.dumps({'acknowledged_revision': revision}))
    return {'saved': True, 'reload': status(manager)}
