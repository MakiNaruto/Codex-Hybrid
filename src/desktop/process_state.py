"""Best-effort process presence, separate from unknowable Codex task activity."""
import os
from pathlib import Path
import sys
import time


CODEX_EXECUTABLES = {'codex', 'codex.exe', 'codex-app-server', 'codex-app-server.exe',
                     'codex app', 'codex desktop'}


def _candidate_processes():
    import psutil
    if sys.platform != 'win32':
        yield from psutil.process_iter(('pid', 'name', 'status'))
        return
    from desktop.windows_processes import process_names
    for pid, name in process_names():
        if name.lower() not in CODEX_EXECUTABLES:
            continue
        try:
            process = psutil.Process(pid)
            # Re-read only candidates, guarding against PID reuse since the snapshot.
            process.info = {'name': process.name()}
            yield process
        except psutil.NoSuchProcess:
            continue


def _macos_client_type(process, command, executable):
    """Recognize macOS app bundles, including the desktop's embedded CLI."""
    import psutil
    entries = [(process.info.get('name') or '', [executable] if executable else command)]
    try:
        for parent in process.parents()[:8]:
            entries.append((parent.name(), parent.cmdline()))
    except (AttributeError, OSError, psutil.Error):
        pass
    paths = [str(args[0] if args else name).replace('\\', '/').lower()
             for name, args in entries]
    # Both app-server and interactive-looking codex processes are embedded in
    # the desktop app. Their argv alone cannot distinguish them from a CLI.
    if any('/codex.app/' in path or
           '/chatgpt.app/contents/resources/codex-cli/' in path or
           path.endswith('/chatgpt.app/contents/macos/chatgpt') for path in paths):
        return 'desktop'
    if any('/.vscode' in path or '/extensions/openai.chatgpt-' in path for path in paths):
        return 'vscode'
    if command and 'app-server' not in command[1:]:
        if str(command[0]).rsplit('/', 1)[-1].lower() == 'codex':
            return 'cli'
    return 'unknown'


def _client_type(process, command, executable, windows):
    """Classify by executable ancestry; never return paths or command arguments."""
    if sys.platform == 'darwin':
        return _macos_client_type(process, command, executable)
    import psutil
    entries = [(process.info.get('name') or '', [executable] if executable else command)]
    try:
        for parent in process.parents()[:8]:
            entries.append((parent.name(), parent.cmdline()))
    except (AttributeError, OSError, psutil.Error):
        pass
    for name, args in entries:
        executable = str(args[0] if args else name).replace('\\', '/').lower()
        if '/.vscode' in executable or '/.vscode-insiders' in executable or '/extensions/openai.chatgpt-' in executable:
            return 'vscode'
    for name, args in entries:
        executable = str(args[0] if args else name).replace('\\', '/').lower()
        desktop = (
            '/openai/codex/' in executable
            or '/windowsapps/openai.codex_' in executable
        ) if windows else '/codex.app/' in executable
        if desktop or name.lower() in {'codex app', 'codex desktop'}:
            return 'desktop'
    # An app-server without identifiable ancestry may belong to any client.
    if 'app-server' not in command[1:] and command:
        executable = str(command[0]).replace('\\', '/').rsplit('/', 1)[-1].lower()
        if executable in {'codex', 'codex.exe'}:
            return 'cli'
    return 'unknown'


def codex_process_state(home):
    import psutil
    home = Path(home).resolve()
    native_home = (Path.home() / '.codex').resolve()
    matching, unknown = [], False
    clients = {'desktop': 0, 'vscode': 0, 'cli': 0, 'unknown': 0}
    windows = sys.platform == 'win32'
    try:
        # Windows command-line reads can be slow or denied for unrelated apps.
        # Read expensive process details only after filtering by executable name.
        for process in _candidate_processes():
            if process.pid == os.getpid():
                continue
            try:
                info = process.info
                if info.get('status') in {'zombie', 'dead'}:
                    continue
                # Helpers/updaters, the gateway and similarly named third-party
                # programs are not a running Codex instance.
                name = (info.get('name') or '').lower()
                if name not in CODEX_EXECUTABLES:
                    continue
                try:
                    executable = process.exe() if hasattr(process, 'exe') else ''
                except (OSError, psutil.AccessDenied):
                    executable = ''
                try:
                    command = info.get('cmdline') or process.cmdline()
                except (AttributeError, OSError, psutil.AccessDenied):
                    command = []
                # Electron renderer/GPU/utility processes are not client instances.
                if (windows or sys.platform == 'darwin') and any(arg.startswith('--type=') for arg in command[1:]):
                    continue
                try:
                    configured = process.environ().get('CODEX_HOME')
                except psutil.AccessDenied:
                    unknown = True
                    continue
                uses_home = Path(configured).expanduser().resolve() == home if configured else home == native_home
                if uses_home:
                    matching.append(process.pid)
                    clients[_client_type(process, command, executable, windows)] += 1
            except psutil.NoSuchProcess:
                continue
            except (OSError, ValueError, psutil.Error):
                unknown = True
    except (OSError, psutil.Error):
        unknown = True
    return {'status': 'running' if matching else 'unknown' if unknown else 'not_detected',
            'process_count': len(matching), 'observed_at': time.time(),
            'clients': clients,
            'source': 'local_process_scan', 'task_status': 'unknown'}
