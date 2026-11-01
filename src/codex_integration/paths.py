"""Locations for checkout resources and private, machine-local state."""
import os
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]

def environment_value(name):
    """Prefer the current brand while accepting existing installation settings."""
    return os.environ.get('CODEX_HYBRID_' + name, os.environ.get('MODEL_ROUTER_' + name,
                          os.environ.get('CONNECTED_' + name)))


# Source resources are independent of private instance data.
ROOT = _CHECKOUT


def data_directory(value=None):
    """Resolve explicit overrides, otherwise use the same user directory on every OS."""
    value = value if value is not None else environment_value('DATA_DIR')
    return (Path(value).expanduser().resolve() if value else Path.home() / '.codex-hybrid')


def check_legacy_installation(directory, explicit=False):
    """Never silently create a second instance over an undiscovered legacy install."""
    if explicit or (directory / 'state.json').is_file():
        return
    legacy_root = Path(environment_value('HOME') or _CHECKOUT).expanduser().resolve()
    roots = [legacy_root, Path.home() / '.model-router', Path.home() / '.connected']
    for root in roots:
        pointer = root / 'cli-config.json'
        old_data = root / 'config'
        if pointer.is_file() or (old_data / 'state.json').is_file():
            raise ValueError(
                f'发现旧安装：{root}。请检查 cli-config.json 中的 data_dir（未设置时为 {old_data}），'
                '使用 --data-dir 显式指定原目录管理旧实例。迁移前请先在原目录执行 uninstall，'
                f'再在 {directory} 重新 install；不会自动搬迁或删除旧数据。')


RUNTIME = data_directory()


def default_models_path():
    return data_directory() / 'models.yaml'
