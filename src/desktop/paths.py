"""Locations for checkout resources and private, machine-local state."""
import os
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]

def environment_value(name):
    """Prefer the current brand while accepting existing installation settings."""
    return os.environ.get('CODEX_MODEL_BRIDGE_' + name, os.environ.get('MODEL_ROUTER_' + name,
                          os.environ.get('CONNECTED_' + name)))


_DEFAULT_HOME = _CHECKOUT
if not (_CHECKOUT / 'pyproject.toml').is_file():
    _DEFAULT_HOME = next((Path.home() / name for name in ('.model-router', '.connected')
                          if (Path.home() / name).is_dir()), Path.home() / '.codex-model-bridge')
ROOT = Path(environment_value('HOME') or _DEFAULT_HOME).expanduser().resolve()

def data_directory(value=None):
    """Resolve private state independently of checkout resources."""
    value = value if value is not None else environment_value('DATA_DIR')
    if value is None:
        from desktop.preferences import load_defaults
        value = load_defaults().get('data_dir')
    return (Path(value).expanduser().resolve() if value else ROOT / 'config')


RUNTIME = data_directory()


def default_models_path():
    return data_directory() / 'models.yaml'
