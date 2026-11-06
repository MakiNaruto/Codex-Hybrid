"""CLI routing transactions and uninstall confirmation."""
import json
from pathlib import Path
import secrets
import tomllib

from infrastructure.files import write_snapshot_bytes as private_write
from codex_integration.configuration import PROVIDER, digest, remove_bridge_provider_table, retain_config_model
from codex_integration import service_lifecycle as lifecycle


def migrate_routing(config_path, settings, state, data, activating, expected_current=None, *, runtime):
    from codex_integration.locking import DirectoryLock
    with DirectoryLock(runtime):
        return _migrate_routing_locked(config_path, settings, state, data, activating, expected_current, runtime=runtime)


def _migrate_routing_locked(config_path, settings, state, data, activating, expected_current=None, *, runtime):
    """Commit CLI routing changes together with offline session metadata."""
    from codex_integration.session_migration import plan, apply
    provider = tomllib.loads(data.decode()).get('model_provider', 'openai')
    if provider not in ('openai', PROVIDER):
        raise ValueError('会话迁移只支持原生 OpenAI 与 Codex Hybrid 路由。')
    name = 'desktop-config.toml' if activating else 'original-config.toml'
    paths = (config_path, runtime / name, runtime / 'state.json')
    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    if expected_current is not None and before[config_path] != expected_current:
        raise ValueError('Codex 配置在迁移前发生变化，未应用切换。')
    if json.loads(before[runtime / 'state.json']) != state:
        raise ValueError('实例配置在迁移前发生变化，未应用切换。')
    data = retain_config_model(data, before[config_path])
    migration = plan(config_path.parent, settings, provider)
    state = dict(state, activated=activating)
    name = 'desktop-config.toml' if activating else 'original-config.toml'
    state['candidate_sha256' if activating else 'original_sha256'] = digest(data)
    updates = {}
    for path, after in [(config_path, data), (runtime / name, data),
                        (runtime / 'state.json', json.dumps(state).encode())]:
        updates[path] = (before[path], after)
    backup = apply(migration, runtime, updates)
    if migration['count']:
        print(f"已迁移 {migration['count']} 个本机会话；首次基线：{backup}")
    return state


def uninstall(args, runtime, state, settings):
    from codex_integration.session_migration import assert_stopped
    assert_stopped(Path(state['config_path']).parent)
    lifecycle.stop_service(missing_ok=True, runtime=runtime)
    print('Codex Hybrid 本机服务已停止。')
    config_path = Path(state['config_path'])
    current = digest(config_path.read_bytes())
    if current == state['original_sha256']:
        try:
            cleaned, removed = remove_bridge_provider_table(config_path.read_bytes().decode('utf-8'))
        except ValueError as error:
            print('无法安全移除 Codex 配置中的 provider 表：' + str(error))
            return
        if removed:
            try:
                confirmed = input('发现 Codex 配置中仍保留 Codex Hybrid 本机服务使用的 provider 表。卸载将从 Codex 配置中移除此服务配置，输入 y 确认：[y/N] ')
            except EOFError:
                confirmed = ''
            if confirmed.strip().lower() not in ('y', 'yes'):
                print('已取消卸载。服务已停止，Codex 配置和本地数据均保留。')
                return
            original = config_path.read_bytes()
            if digest(original) != state['original_sha256']:
                print('确认期间 Codex 配置再次变化，已取消卸载。请检查后重试。')
                return
            migrate_routing(config_path, settings, state, cleaned.encode(), False, original, runtime=runtime)
            print('已从 Codex 配置中移除本地 provider 表。')
        else:
            migrate_routing(config_path, settings, state, config_path.read_bytes(), False, runtime=runtime)
        print('Codex 配置已是安装前状态，无需回滚。')
        print('卸载完成。配置文件和凭据仍保留在数据目录中：' + str(runtime))
        return
    try:
        confirmed = input('是否将 Codex 配置恢复为安装前备份？输入 y 确认，直接回车取消：[y/N] ')
    except EOFError:
        confirmed = ''
    if confirmed.strip().lower() not in ('y', 'yes'):
        print('已取消卸载。服务已停止，Codex 配置和本地数据均保留。')
        return
    args.action = 'rollback'
    return False


def run(args, runtime, state, settings, *, uninstalling=False):
    config_path = Path(state['config_path'])
    activating = args.action == 'activate'
    candidate_path = runtime / 'desktop-config.toml'
    current_data = config_path.read_bytes()
    current = digest(current_data)
    expected = state['original_sha256'] if activating else state['candidate_sha256']
    target = state['candidate_sha256'] if activating else state['original_sha256']
    if current == target:
        migrate_routing(config_path, settings, state, current_data, activating, current_data, runtime=runtime)
        return print('Configuration and sessions are in the requested state')
    if current != expected and activating:
        raise ValueError('Configuration changed since preparation; refusing to overwrite newer edits')
    if activating:
        lifecycle.health(settings, ensure_forwarding=True)
    data = (runtime / ('desktop-config.toml' if activating else 'original-config.toml')).read_bytes()
    if digest(data) != target:
        raise ValueError('Prepared file was changed; refusing activation/rollback')
    removed_bridge = False
    if uninstalling:
        try:
            cleaned, removed = remove_bridge_provider_table(data.decode())
        except ValueError as error:
            print('无法安全移除备份中的本地 provider 表：' + str(error))
            return
        if removed:
            data = cleaned.encode()
            removed_bridge = True
    if current != expected:
        print('检测到初始化后 Codex 配置又有修改（例如由 CC Switch 修改）。')
        print('回滚会覆盖这些修改，并恢复安装前备份：' + str(config_path))
        try:
            confirmed = input('输入 yes 确认覆盖并恢复，直接回车取消：')
        except EOFError:
            confirmed = ''
        if confirmed.strip().lower() != 'yes':
            return print('已取消回滚；Codex 配置未更改。服务已停止，数据仍保留。' if uninstalling
                         else '已取消回滚；Codex 配置未更改。')
        if config_path.read_bytes() != current_data:
            print('确认期间 Codex 配置再次变化，已取消回滚。请检查后重试。')
            return
        recovery = runtime / ('pre-rollback-' + secrets.token_hex(6) + '.toml')
        private_write(recovery, current_data)
        print('已在回滚前备份当前配置：' + str(recovery))
    # Commit routing and index changes while retaining the current model setting.
    migrate_routing(config_path, settings, state, data, activating, current_data, runtime=runtime)
    if uninstalling:
        print('已恢复安装前的 Codex 配置。请完全退出并重新打开 Codex。')
        print('卸载完成。配置文件和凭据仍保留在数据目录中：' + str(runtime))
    else:
        print(('已启用路由' if activating else '已恢复配置') + '；请完全退出并重新打开 Codex 以重新加载。')
