"""Persistent CLI defaults, independent of the selected runtime directory."""
import json
from pathlib import Path



def config_path():
    from desktop.paths import ROOT
    return ROOT / 'cli-config.json'


def load_defaults():
    path = config_path()
    values = json.loads(path.read_text()) if path.exists() else {}
    allowed = {'data_dir', 'port', 'management_auth', 'codex_home'}
    if not isinstance(values, dict) or values.keys() - allowed:
        raise ValueError('Invalid CLI configuration')
    for key, value in values.items():
        if key == 'port':
            if type(value) is not int or not 1024 <= value <= 65535:
                raise ValueError('Invalid unprivileged port')
        elif key == 'management_auth':
            if value not in ('on', 'off'):
                raise ValueError('Invalid management authentication mode')
        elif not isinstance(value, str) or not value.strip():
            raise ValueError('Invalid configuration path')
    return values


def save_data_directory(directory):
    """Remember a successful installation without changing other CLI preferences."""
    from desktop.service import private_write

    values = load_defaults()
    values['data_dir'] = str(Path(directory).expanduser().resolve())
    config_path().parent.mkdir(parents=True, exist_ok=True)
    private_write(config_path(), json.dumps(values, ensure_ascii=False, indent=2) + '\n')


def configure(argv):
    import argparse
    from desktop.service import private_write

    parser = argparse.ArgumentParser(description='查看配置；使用 --set 保存 CLI 默认值（不修改已初始化服务）')
    parser.add_argument('--set', action='store_true', help='保存后续命令使用的 CLI 默认值')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--port', type=int, choices=range(1024, 65536), metavar='1024-65535')
    parser.add_argument('--management-auth', choices=['on', 'off'])
    parser.add_argument('--codex-home', type=Path)
    parser.add_argument('--reset', action='store_true', help='清除保存的默认值')
    args = parser.parse_args(argv)
    values = {} if args.reset else load_defaults()
    updates = {key: str(value.expanduser().resolve()) if isinstance(value, Path) else value
               for key, value in vars(args).items() if key not in ('reset', 'set') and value is not None}
    if updates and not args.set:
        parser.error('修改默认值请使用 config --set --port ... --data-dir ...')
    values.update(updates)
    if args.set and not updates:
        parser.error('--set 至少需要一个设置项')
    if args.set or args.reset:
        config_path().parent.mkdir(parents=True, exist_ok=True)
        private_write(config_path(), json.dumps(values, ensure_ascii=False, indent=2) + '\n')
    result = {'config_file': str(config_path()), 'defaults': values}
    # Include live installation values when present, without exposing credentials.
    from desktop.paths import RUNTIME, data_directory
    runtime = data_directory()
    settings_path = runtime / 'settings.json'
    state_path = runtime / 'state.json'
    if settings_path.is_file() and state_path.is_file():
        settings = json.loads(settings_path.read_text())
        result['active'] = {'data_dir': str(runtime), 'port': settings.get('port'),
            'source': settings.get('source'),
            'management_auth_required': bool(settings.get('management_auth_required', False))}
    import os
    import unicodedata

    def width(value):
        return sum(2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1 for char in str(value))

    def pad(value, size):
        value = str(value)
        return value + ' ' * max(0, size - width(value))

    def table(headers, rows):
        widths = [max(width(headers[i]), *(width(row[i]) for row in rows)) for i in range(len(headers))]
        border = lambda left, middle, right: left + middle.join('─' * (size + 2) for size in widths) + right
        print(border('┌', '┬', '┐'))
        print('│ ' + ' │ '.join(pad(value, size) for value, size in zip(headers, widths)) + ' │')
        print(border('├', '┼', '┤'))
        for row in rows:
            print('│ ' + ' │ '.join(pad(value, size) for value, size in zip(row, widths)) + ' │')
        print(border('└', '┴', '┘'))

    saved_port = values.get('port', 18891)
    saved_auth = values.get('management_auth', 'off')
    saved_codex = os.environ.get('CODEX_HOME', values.get('codex_home', str(Path.home() / '.codex')))
    effective_data = data_directory()
    active = result.get('active', {})
    active_source = active.get('source') or {}
    source_type = active_source.get('type')
    source_label = {'cc-switch': 'CC Switch', 'yaml': 'YAML'}.get(source_type, source_type)
    source_path = active_source.get('path')
    if not active:
        source_label = 'YAML（默认）'
        source_path = str(effective_data / 'models.yaml')
    print('Codex Model Bridge 配置')
    table(['项目', '当前生效值'], [
        ('数据目录', str(effective_data)),
        ('端口', active.get('port') if active.get('port') is not None else saved_port),
        ('配置来源', source_label or '未知'),
        ('来源位置', source_path or '未知'),
        ('Codex 目录', saved_codex),
        ('管理页鉴权', '开启' if (active.get('management_auth_required') if active else saved_auth == 'on') else '关闭'),
    ])
