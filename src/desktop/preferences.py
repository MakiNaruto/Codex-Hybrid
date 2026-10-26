"""Read-only inspection of the selected instance configuration."""
import argparse
import json
from pathlib import Path


def configure(argv):
    from desktop.paths import data_directory, environment_value, check_legacy_installation

    parser = argparse.ArgumentParser(description='查看所选实例配置')
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args(argv)
    runtime = data_directory(args.data_dir)
    check_legacy_installation(runtime, explicit=args.data_dir is not None or bool(environment_value('DATA_DIR')))
    result = {}
    state = {}
    settings_path = runtime / 'settings.json'
    state_path = runtime / 'state.json'
    if settings_path.is_file() and state_path.is_file():
        settings = json.loads(settings_path.read_text())
        state = json.loads(state_path.read_text())
        result['active'] = {'port': settings.get('port'), 'source': settings.get('source'),
                            'management_auth_required': settings.get('management_auth_required', False)}
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

    active = result.get('active', {})
    saved_port = 18891
    saved_auth = 'off'
    saved_codex = str(Path(state['config_path']).parent) if active else os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))
    effective_data = runtime
    active_source = active.get('source') or {}
    source_type = active_source.get('type')
    source_label = {'cc-switch': 'CC Switch', 'yaml': 'YAML'}.get(source_type, source_type)
    source_path = active_source.get('path')
    if not active:
        source_label = 'YAML（默认）'
        source_path = str(effective_data / 'models.yaml')
    print('Codex Hybrid 配置')
    table(['项目', '当前生效值'], [
        ('数据目录', str(effective_data)),
        ('端口', active.get('port') if active.get('port') is not None else saved_port),
        ('配置来源', source_label or '未知'),
        ('来源位置', source_path or '未知'),
        ('Codex 目录', saved_codex),
        ('管理页鉴权', '开启' if (active.get('management_auth_required') if active else saved_auth == 'on') else '关闭'),
    ])
