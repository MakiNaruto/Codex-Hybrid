"""Refresh the external and official model catalogs."""
import json
import os
from pathlib import Path
import sys

from infrastructure.files import write_snapshot_bytes as private_write
from model_catalog.sources import load_source, merged_catalog, update_cc_snapshot
from codex_integration.installation import official_cache


def run(args, runtime, state, settings):
    codex_home = args.codex_home if '--codex-home' in sys.argv or os.environ.get('CODEX_HOME') else Path(state['config_path']).parent
    original_models = official_cache(codex_home, settings)
    if args.source:
        settings['source'] = {'type': args.source, 'path': str((
            args.cc_db if args.source == 'cc-switch' else args.models_config).expanduser().resolve())}
    external = load_source(settings)
    official_models_enabled = settings.get('official_models_enabled', True)
    merged = merged_catalog(original_models, external,
                            include_official=official_models_enabled)
    settings['official_catalog'] = original_models
    settings['official_models'] = ([m['slug'] for m in original_models]
                                   if official_models_enabled else [])
    settings['models'] = [m['slug'] for m in merged['models']]
    update_cc_snapshot(settings, merged, external)
    keys = [key for key, model in external.models.items() if model['enabled']]
    if keys:
        settings['deepseek_model'] = keys[0]
    settings.pop('routing_fallback_model', None)
    private_write(Path(settings['catalog']), json.dumps(merged, ensure_ascii=False))
    private_write(runtime / 'settings.json', json.dumps(settings))
    print('Preserved official catalog and refreshed external entries; restart service and desktop to reload.')
    return
