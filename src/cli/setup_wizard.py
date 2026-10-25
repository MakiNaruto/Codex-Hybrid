#!/usr/bin/env python3
"""Interactive local setup. Never copy credentials or runtime between machines."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

import yaml

import desktop.service as desktop
from desktop.paths import data_directory, environment_value
from desktop.preferences import load_defaults, save_data_directory
from model_catalog.catalog import Catalog


def ask(label, default=None):
    value = input(label + (f' [{default}]' if default else '') + '：').strip()
    value = value or default
    if not value:
        raise ValueError('必填项不能为空')
    return value


def run(action):
    subprocess.run([sys.executable, '-m', 'cli', action, '--data-dir', str(desktop.RUNTIME)], check=True)


def main():
    saved = load_defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', saved.get('codex_home', Path.home() / '.codex'))))
    parser.add_argument('--data-dir', type=Path, help='Private data directory (or CODEX_MODEL_BRIDGE_DATA_DIR)')
    parser.add_argument('--port', type=int, default=saved.get('port', 18891))
    args = parser.parse_args()
    print('Codex Model Bridge 本机配置向导（macOS / Windows / Python 3.11+）')
    if args.data_dir is not None or environment_value('DATA_DIR') or saved.get('data_dir'):
        desktop.RUNTIME = data_directory(args.data_dir)
    else:
        desktop.RUNTIME = data_directory(ask('路由器数据目录', str(desktop.RUNTIME)))
    runtime = desktop.RUNTIME
    print(f'数据目录：{runtime}')
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (runtime / 'state.json').exists():
        if not 1024 <= args.port <= 65535:
            raise ValueError('端口必须在 1024–65535 之间')
        home = args.codex_home.expanduser().resolve()
        if not (home / 'config.toml').is_file() or not (home / 'models_cache.json').is_file():
            raise ValueError('请先安装 Codex、登录并完成一次聊天，再运行向导；自定义目录用 --codex-home 指定')
        # Validate compatibility before collecting a secret or creating files.
        desktop.official_cache(home)
        desktop.candidate_config((home / 'config.toml').read_text(),
                                 {'catalog': str(runtime / 'models.json'), 'port': args.port, 'local_token': 'preflight'})
        print('1. 配置来源：1 = 手动填写 API，2 = 本机 CC Switch（只读）')
        choice = ask('选择', '1')
        if choice == '2':
            source = {'type': 'cc-switch', 'path': str(Path(ask('CC Switch 数据库', str(Path.home() / '.cc-switch/cc-switch.db'))).expanduser().resolve())}
        elif choice == '1':
            base = ask('API 前缀（按厂商要求包含 /v1，不填 /chat/completions）', 'https://api.deepseek.com')
            model = ask('准确的 API 模型 ID', 'deepseek-v4-flash')
            display = ask('模型显示名称', model)
            protocol = ask('协议：1 = Chat Completions，2 = Responses', '1')
            if protocol not in ('1', '2'):
                raise ValueError('协议选择无效')
            config = {'version': 1, 'default_model': 'custom/default', 'providers': {'custom': {
                'protocol': 'openai_chat_completions' if protocol == '1' else 'openai_responses',
                'base_url': base, 'credentials': {'api_key_env': 'CONNECTED_API_KEY', 'env_file': './provider.env'},
                'models': {'default': {'model_id': model, 'display_name': display}}}}}
            runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
            config_path = runtime / 'setup-models.yaml'
            # Never overwrite an earlier unfinished setup's credentials without consent.
            if config_path.exists() or (runtime / 'provider.env').exists():
                raise ValueError(f'存在未完成的配置，请先检查 {config_path} 和 {runtime / "provider.env"}')
            desktop.private_write(config_path, yaml.safe_dump(config, allow_unicode=True))
            try:
                Catalog(config_path)
                key = getpass.getpass('API Key（输入不显示）：').strip()
                if not key or any(c.isspace() for c in key) or key[0] in "\"'":
                    raise ValueError('API Key 不能为空或包含空白/外层引号')
                desktop.private_write(runtime / 'provider.env', 'CONNECTED_API_KEY=' + key + '\n')
            except BaseException:
                config_path.unlink(missing_ok=True)
                raise
            source = {'type': 'yaml', 'path': str(config_path)}
        else:
            raise ValueError('配置来源选择无效')
        desktop.prepare(args.port, home, source)
    else:
        print('1. 检查并复用已有配置')
    print('\n2. 启动本机服务（已有配置会保留）')
    start_now = ask('现在启动？y/n', 'y').lower()
    if start_now not in ('y', 'n'):
        raise ValueError('请输入 y 或 n')
    service_started = start_now == 'y'
    if service_started:
        run('start')
    settings = json.loads((runtime / 'settings.json').read_text())
    token = settings.get('management_token') if settings.get('management_auth_required', False) else ''
    save_data_directory(runtime)
    print('\n配置完成')
    print(f'  数据目录已保存为默认值：{runtime}')
    if service_started:
        print('  是否启用本地路由，可在管理页面点击“客户端路由”开关。')
        url = f'http://127.0.0.1:{settings["port"]}/manage/{"#" + token if token else ""}'
        try:
            opened = webbrowser.open(url)
        except (webbrowser.Error, OSError):
            opened = False
        if opened:
            print('  已请求浏览器打开管理页面。若页面没有显示，请手动访问：')
        else:
            print('  无法自动打开浏览器，请手动访问管理页面：')
        print(f'    {url}')
    else:
        print('  本次未启动服务。之后运行 start 启动服务，再打开管理页面并点击“客户端路由”开关。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # Catalog/config exceptions contain codes, never print arbitrary exception text.
        print('配置未完成。请检查 Python/Codex 登录、输入格式、端口及现有配置；不会覆盖后续用户配置。', file=sys.stderr)
        if isinstance(exc, ValueError) and type(exc) is ValueError:
            print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print('\n已取消；可重新运行 ./scripts/codex-model-bridge.sh install。', file=sys.stderr)
        sys.exit(1)
