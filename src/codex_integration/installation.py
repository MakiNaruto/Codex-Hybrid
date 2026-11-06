"""Prepare local routing artifacts under the selected runtime lock."""
import json
from pathlib import Path
import secrets
import tomllib

from infrastructure.files import write_snapshot_bytes as private_write
from codex_integration.configuration import digest, candidate_config, uses_openai_auth
from codex_integration.paths import RUNTIME, default_models_path
from model_catalog.sources import load_source, merged_catalog, update_cc_snapshot


def official_cache(codex_home, settings=None):
    models = json.loads((codex_home / 'models_cache.json').read_text(encoding='utf-8'))['models']
    if settings:
        external = set(settings['models']) - set(settings['official_models'])
        models = [model for model in models if model['slug'] not in external]
    if not models:
        raise ValueError('Official model cache is empty')
    return models


def prepare(port, codex_home, source=None, *, directory=None, management_auth_required=False):
    from codex_integration.locking import DirectoryLock
    runtime = Path(directory) if directory is not None else RUNTIME
    with DirectoryLock(runtime):
        return _prepare_locked(port, codex_home, source, directory=runtime,
                               management_auth_required=management_auth_required)


def _prepare_locked(port, codex_home, source=None, *, directory=None, management_auth_required=False):
    runtime = Path(directory) if directory is not None else RUNTIME
    if (runtime / 'state.json').exists():
        raise ValueError('Already prepared; use status/start/activate/rollback with the existing files')
    config_path = codex_home / 'config.toml'
    original = config_path.read_bytes()
    models = official_cache(codex_home)
    original_config = tomllib.loads(original.decode('utf-8'))
    official_models_enabled = uses_openai_auth(original_config)
    published_official = models if official_models_enabled else []
    source = source or {'type': 'yaml', 'path': str(default_models_path())}
    settings = {'port': port, 'source': source,
                'official_models': [m['slug'] for m in published_official],
                'official_catalog': models,
                'official_models_enabled': official_models_enabled,
                'local_token': secrets.token_urlsafe(32),
                'catalog': str(runtime / 'models.json'),
                'management_auth_required': management_auth_required,
                'disable_legacy_plugin': True, 'official_header_passthrough': True}
    external = load_source(settings)
    merged = merged_catalog(models, external, include_official=official_models_enabled)
    external_keys = [key for key, value in external.models.items() if value['enabled']]
    settings.update(models=[m['slug'] for m in merged['models']])
    update_cc_snapshot(settings, merged, external)
    if external_keys:
        settings['deepseek_model'] = external_keys[0]
    candidate = candidate_config(original.decode(), settings).encode()
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_write(runtime / 'models.json', json.dumps(merged, ensure_ascii=False))
    private_write(runtime / 'settings.json', json.dumps(settings))
    private_write(runtime / 'original-config.toml', original)
    private_write(runtime / 'desktop-config.toml', candidate)
    state = {'config_path': str(config_path), 'original_sha256': digest(original),
             'candidate_sha256': digest(candidate), 'activated': False}
    private_write(runtime / 'state.json', json.dumps(state))
    print('已准备本机模型路由，尚未修改 Codex 用户配置：' + str(runtime))
