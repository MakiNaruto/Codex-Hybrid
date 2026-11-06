"""Prepare and durably publish a complete model-directory/settings snapshot."""
import copy
import json
from pathlib import Path

from codex_integration.configuration import uses_openai_auth
from infrastructure.files import write_private_text as private_write
from model_catalog.sources import (
    apply_preferences, import_current_cc_record, load_source, merged_catalog,
    source_key, update_cc_snapshot,
)


def external_codex_config(config):
    return bool(config) and config.get('model_provider', 'openai') not in {
        'openai', 'codex-hybrid'}


def prepare_publication(settings, codex_config, source=None, catalog=None, extra=None):
    """Prepare detached settings and the effective external catalog without writes."""
    settings = copy.deepcopy(settings)
    old_source_key = source_key(settings['source'])
    official_models_enabled = (
        uses_openai_auth(codex_config) if codex_config is not None
        else settings.get('official_models_enabled', True)
    )
    settings['official_models_enabled'] = official_models_enabled
    initial_external = (
        [] if settings['source']['type'] == 'cc-switch'
        and external_codex_config(codex_config)
        else [key for key in settings['models']
              if key not in settings['official_models']]
    )
    settings.setdefault('model_preferences', {}).setdefault(old_source_key, {
        'added': initial_external,
        'compatibility': {}})
    if source is not None:
        settings['source'] = source
    if extra:
        settings.update(extra)
    external = catalog if catalog is not None else load_source(settings)
    settings['model_preferences'].setdefault(source_key(settings['source']), {
        'added': [], 'compatibility': {}})
    if settings['source']['type'] == 'cc-switch':
        if codex_config is not None:
            import_current_cc_record(
                external,
                settings['model_preferences'][source_key(settings['source'])],
                codex_config,
            )
    external = apply_preferences(external, settings)
    settings.pop('routing_fallback_model', None)
    return settings, external


def complete_publication(settings, external, official_source):
    """Finish the owned settings snapshot with its merged directory and bindings."""
    external_keys = [key for key, value in external.models.items() if value['enabled']]
    official_models_enabled = settings['official_models_enabled']
    settings['official_catalog'] = official_source
    official = official_source if official_models_enabled else []
    merged = merged_catalog(
        official_source, external, include_official=official_models_enabled)
    settings['official_models'] = [model['slug'] for model in official]
    settings['models'] = [m['slug'] for m in merged['models']]
    update_cc_snapshot(settings, merged, external)
    if external_keys:
        settings['deepseek_model'] = external_keys[0]  # Historical smoke alias only.
    else:
        settings.pop('deepseek_model', None)
    return merged, official


def write_publication(settings_path, settings, merged, official):
    """Write under the caller's configuration lock, restoring the directory on failure."""
    catalog_path = Path(settings['catalog'])
    previous_catalog = (catalog_path.read_text(encoding='utf-8') if catalog_path.exists()
                        else json.dumps({'models': official}, ensure_ascii=False))
    private_write(catalog_path, json.dumps(merged, ensure_ascii=False))
    try:
        # The directory and its explicit bindings share one durable snapshot.
        private_write(settings_path, json.dumps(settings, ensure_ascii=False))
    except OSError:
        private_write(catalog_path, previous_catalog)
        raise
