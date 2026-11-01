"""Read-only build-tool and Codex process inventory. Does not inspect conversations."""
import json
import os
from pathlib import Path
import platform
import shutil

import psutil


def main():
    desktop = []
    backends = {'desktop': 0, 'vscode': 0, 'other': 0}
    unreadable = 0
    for process in psutil.process_iter(['name', 'exe']):
        try:
            name = (process.info['name'] or '').lower()
            executable = process.info['exe'] or ''
            normalized = executable.replace('\\', '/').lower()
            if name == 'chatgpt.exe' and '/windowsapps/openai.codex_' in normalized:
                package = next(part for part in Path(executable).parts if part.startswith('OpenAI.Codex_'))
                desktop.append(package)
            elif platform.system() == 'Darwin' and '/codex.app/contents/macos/' in normalized:
                desktop.append('Codex.app')
            if name in ('codex', 'codex.exe'):
                kind = 'vscode' if '/.vscode/extensions/' in normalized else (
                    'desktop' if '/openai/codex/' in normalized else 'other')
                backends[kind] += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            unreadable += 1

    vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    webview = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft/EdgeWebView/Application'
    report = {
        'platform': platform.system(), 'machine': platform.machine(),
        'tool_commands_found': {name: shutil.which(name) is not None for name in ('cargo', 'rustc', 'cl', 'msbuild', 'node')},
        'vswhere_found': vswhere.is_file() if os.name == 'nt' else None,
        'webview_runtime_directory_found': webview.is_dir() if os.name == 'nt' else None,
        'desktop_installations_seen_in_running_processes': sorted(set(desktop)),
        'codex_backend_process_counts': backends,
        'unreadable_process_records': unreadable,
        'conversation_activity': 'unknown',
        'limits': ['Read-only process metadata; no conversation contents or auth files read.',
                   'Missing executable on PATH is not a global proof of absence.',
                   'No active Codex instance was closed, started, or modified.'],
    }
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
