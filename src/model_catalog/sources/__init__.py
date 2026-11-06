"""Configuration source selection and compatible public catalogue helpers."""
from model_catalog.catalog import Catalog, ConfigError
from model_catalog.preferences import apply_preferences, import_current_cc_record, source_key
from model_catalog.publication import merged_catalog, update_cc_snapshot

__all__ = [
    "Catalog", "ConfigError", "load_source", "apply_preferences",
    "import_current_cc_record", "source_key", "merged_catalog", "update_cc_snapshot",
]


def load_source(settings):
    source = settings['source']
    if source['type'] == 'yaml':
        catalog = Catalog(source['path'])
    elif source['type'] == 'cc-switch':
        from model_catalog.cc_switch import make_catalog
        catalog = make_catalog(source['path'])
    else:
        raise ConfigError('SOURCE_NOT_SUPPORTED')
    return apply_preferences(catalog, settings)
