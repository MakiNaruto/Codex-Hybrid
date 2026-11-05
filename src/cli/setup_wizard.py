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

from codex_integration import service
from codex_integration.paths import data_directory, environment_value, check_legacy_installation
from model_catalog.catalog import Catalog


def ask(label, default=None):
    value = input(label + (f' [{default}]' if default else '') + '：').strip()
    value = value or default
    if not value:
        raise ValueError('必填项不能为空')
    return value


def run(action):
    subprocess.run([sys.executable, '-m', 'cli', action, '--data-dir', str(service.RUNTIME)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')))
    parser.add_argument('--data-dir', type=Path, help='Private data directory (or CODEX_HYBRID_DATA_DIR)')
    parser.add_argument('--port', type=int, default=18891)
    args = parser.parse_args()
    print('Codex Hybrid 本机配置向导（macOS / Windows / Python 3.11+）')
    service.RUNTIME = data_directory(args.data_dir)
    check_legacy_installation(service.RUNTIME, explicit=args.data_dir is not None or bool(environment_value('DATA_DIR')))
    runtime = service.RUNTIME
    print(f'数据目录：{runtime}')
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    from codex_integration.locking import DirectoryLock
    with DirectoryLock(runtime):
        if not (runtime / 'state.json').exists():
            if not 1024 <= args.port <= 65535:
                raise ValueError('端口必须在 1024–65535 之间')
            home = args.codex_home.expanduser().resolve()
            if not (home / 'config.toml').is_file() or not (home / 'models_cache.json').is_file():
                raise ValueError('请先安装 Codex、登录并完成一次聊天，再运行向导；自定义目录用 --codex-home 指定')
            # Validate compatibility before collecting a secret or creating files.
            service.official_cache(home)
            service.candidate_config((home / 'config.toml').read_text(),
                                     {'catalog': str(runtime / 'models.json'), 'port': args.port, 'local_token': 'preflight'})
            print('1. 配置来源：1 = 手动填写 API，2 = 本机 CC Switch（只读），3 = 稍后在网页配置')
            choice = ask('选择', '1')
            if choice == '2':
                source = {'type': 'cc-switch', 'path': str(Path(ask('CC Switch 数据库', str(Path.home() / '.cc-switch/cc-switch.db'))).expanduser().resolve())}
            elif choice == '1':
                base = ask('Responses API 前缀（按厂商要求�