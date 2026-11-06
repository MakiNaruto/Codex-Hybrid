"""Service commands and human-readable status rendering."""
import json
from pathlib import Path

from codex_integration.configuration import digest
from codex_integration import service_lifecycle as lifecycle


def run(args, runtime, state, settings):
    if args.action in ('start', 'restart'):
        if args.action == 'restart':
            lifecycle.stop_service(missing_ok=True, runtime=runtime)
        lifecycle.start_service(settings, runtime=runtime)
    elif args.action == 'stop':
        lifecycle.stop_service(runtime=runtime)
        print('Stopped. If activated, roll back configuration before starting another Codex turn.')
    elif args.action == 'status':
        try:
            lifecycle.health(settings)
            running = True
        except (OSError, ValueError):
            running = False
        current = digest(Path(state['config_path']).read_bytes())
        config_state = ('activated' if current == state['candidate_sha256'] else
                        'original' if current == state['original_sha256'] else 'modified_since_prepare')
        catalog_path = Path(settings.get('catalog', runtime / 'models.json'))
        catalog_models = []
        if catalog_path.is_file():
            try:
                catalog_models = json.loads(catalog_path.read_text(encoding='utf-8')).get('models', [])
            except (OSError, ValueError, TypeError):
                catalog_models = []
        # Show human-facing model names while retaining stable keys for selection.
        models = [{'name': item.get('display_name') or item.get('model_id') or item.get('slug') or '未知模型',
                   'enabled': item.get('enabled', True)}
                  for item in catalog_models if isinstance(item, dict)]
        import unicodedata

        def visual_width(value):
            return sum(2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1 for char in str(value))

        def pad(value, width):
            value = str(value)
            return value + ' ' * max(0, width - visual_width(value))

        def row(label, value):
            print(f'│ {pad(label, 16)} │ {value}')

        source = settings.get('source') or {}
        source_label = {'cc-switch': 'CC Switch', 'yaml': 'YAML'}.get(source.get('type'), source.get('type', '未知'))
        print('Codex Hybrid 状态')
        print('┌──────────────────┬──────────────────────────────────────────────')
        row('服务状态', '运行中' if running else '未运行')
        row('监听端口', settings['port'])
        from management.runtime import management_port
        row('管理端口', management_port(settings))
        row('客户端路由', '已启用' if config_state == 'activated' else '未启用')
        row('配置状态', {'activated': '已接入', 'original': '未接入',
                         'modified_since_prepare': '初始化后有修改'}.get(config_state, config_state))
        row('配置来源', source_label)
        if source.get('path'):
            row('来源位置', source['path'])
        row('数据目录', str(runtime))
        row('Codex 配置', state.get('config_path', '未知'))
        row('管理页鉴权', '已开启' if settings.get('management_auth_required', False) else '关闭')
        print('└──────────────────┴──────────────────────────────────────────────')
        print('\n可用模型')
        name_width = max([12, *(visual_width(model['name']) for model in models)])
        print(f'┌─{"─" * name_width}─┬──────┐')
        print(f'│ {pad("模型名称", name_width)} │ 状态 │')
        print(f'├─{"─" * name_width}─┼──────┤')
        if models:
            for model in models:
                state_label = '启用' if model['enabled'] else '禁用'
                print(f"│ {pad(model['name'], name_width)} │ {state_label} │")
        else:
            print(f'│ {pad("未找到模型信息", name_width)} │      │')
        print(f'└─{"─" * name_width}─┴──────┘')
