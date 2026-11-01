"""Fixed desktop management operations, without listeners or Codex lifecycle actions."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path

from desktop.locking import DirectoryLock
from desktop.snapshot import revision
from model_catalog.catalog import Catalog, ConfigError, identifier, read_yaml

# Only these stable codes cross the private process boundary.
ERRORS = {'CONFIG_CHANGED', 'ALREADY_CONFIGURED', 'CODEX_NOT_READY', 'NOT_CONFIGURED',
          'SERVICE_ALREADY_RUNNING', 'INSTANCE_BUSY', 'CC_MODE_IS_READ_ONLY',
          'INVALID_REQUEST', 'MODEL_DISABLED', 'MODEL_NOT_CONFIGURED', 'CONCURRENCY_LIMIT'}


def validate(request):
    if not isinstance(request, dict) or request.get('action') not in (
            'initialize', 'save_provider', 'test_connection'):
        raise ConfigError('INVALID_REQUEST')
    action = request['action']
    allowed = {'action'}
    if action == 'test_connection':
        allowed.add('key')
        if not isinstance(request.get('key'), str) or not request['key']:
            raise ConfigError('INVALID_REQUEST')
    if action == 'save_provider':
        allowed.update(('revision', 'id', 'base_url', 'protocol', 'enabled',
                        'timeout_seconds', 'api_key', 'models'))
        for key in ('revision', 'id', 'base_url', 'protocol'):
            if not isinstance(request.get(key), str):
                raise ConfigError('INVALID_REQUEST')
        identifier(request['id'])
        if type(request.get('enabled')) is not bool or type(request.get('timeout_seconds')) is not int:
            raise ConfigError('INVALID_REQUEST')
        if not isinstance(request.get('api_key', ''), str):
            raise ConfigError('INVALID_REQUEST')
        if not isinstance(request.get('models'), list) or not request['models']:
            raise ConfigError('INVALID_REQUEST')
        aliases = set()
        for model in request['models']:
            if not isinstance(model, dict) or set(model) != {'alias', 'model_id', 'display_name', 'enabled'}:
                raise ConfigError('INVALID_REQUEST')
            for key in ('alias', 'model_id', 'display_name'):
                if not isinstance(model[key], str):
                    raise ConfigError('INVALID_REQUEST')
            identifier(model['alias'])
            if type(model['enabled']) is not bool or model['alias'] in aliases:
                raise ConfigError('INVALID_REQUEST')
            aliases.add(model['alias'])
    if set(request) - allowed:
        raise ConfigError('INVALID_REQUEST')


def initialize(directory, codex_home):
    from desktop.service import official_cache, prepare
    from management.service import private_write
    if (directory / 'settings.json').exists() or (directory / 'state.json').exists():
        raise ConfigError('ALREADY_CONFIGURED')
    try:
        # Preflight before creating configuration files; prepare repeats these reads.
        (codex_home / 'config.toml').read_text(encoding='utf-8')
        official_cache(codex_home)
    except (OSError, ValueError, KeyError, TypeError):
        raise ConfigError('CODEX_NOT_READY') from None
    models = directory / 'models.yaml'
    if not models.exists():
        private_write(models, 'version: 1\nproviders: {}\n')
    Catalog(models)
    with redirect_stdout(io.StringIO()):
        prepare(18891, codex_home, {'type': 'yaml', 'path': str(models)},
                directory=directory, management_auth_required=True)
    return {'saved': True}


def save(manager, request):
    if manager.gateway.settings['source']['type'] != 'yaml':
        raise ConfigError('CC_MODE_IS_READ_ONLY')
    if revision(manager.directory) != request['revision']:
        raise ConfigError('CONFIG_CHANGED')
    raw = read_yaml(manager.gateway.settings['source']['path'])
    old = raw['providers'].get(request['id'], {})
    spec = copy.deepcopy(old)
    spec.update({key: request[key] for key in ('base_url', 'protocol', 'enabled', 'timeout_seconds')})
    if old.get('protocol') != request['protocol']:
        spec['responses_compatibility'] = 'portable' if request['protocol'] == 'openai_responses' else 'native'
        spec['history_migration'] = False
    spec['models'] = {}
    for model in request['models']:
        value = copy.deepcopy(old.get('models', {}).get(model['alias'], {}))
        value.update({key: model[key] for key in ('model_id', 'display_name', 'enabled')})
        spec['models'][model['alias']] = value
    return manager.save_provider(request['id'], spec, api_key=request.get('api_key') or None)


def execute(request, *, directory=None, codex_home=None):
    directory = Path(directory) if directory is not None else Path.home() / '.codex-hybrid'
    codex_home = Path(codex_home) if codex_home is not None else Path.home() / '.codex'
    try:
        validate(request)
        with DirectoryLock(directory, 'service.lock', 'SERVICE_ALREADY_RUNNING'), DirectoryLock(directory):
            if request['action'] == 'initialize':
                return {'ok': True, 'result': initialize(directory, codex_home)}
            settings_path = directory / 'settings.json'
            if not settings_path.is_file():
                raise ConfigError('NOT_CONFIGURED')
            from management.runtime import ManagementContext
            from management.service import Management
            from gateway.server import route, sse_events
            context = ManagementContext(json.loads(settings_path.read_text(encoding='utf-8')))
            manager = Management(context, settings_path, route, sse_events)
            try:
                result = (save(manager, request) if request['action'] == 'save_provider'
                          else manager.test_connection(request['key']))
                return {'ok': True, 'result': result}
            finally:
                manager.close()
    except Exception as error:
        code = error.code if isinstance(error, ConfigError) else None
        return {'ok': False, 'error': code if code in ERRORS else 'OPERATION_FAILED'}


def main():
    import sys
    try:
        line = sys.stdin.buffer.readline(65537)
        if len(line) > 65536:
            raise ValueError('request too large')
        result = execute(json.loads(line))
    except Exception:
        result = {'ok': False, 'error': 'INVALID_REQUEST'}
    print(json.dumps(result, ensure_ascii=False), flush=True)
