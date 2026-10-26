"""Best-effort process presence, separate from unknowable Codex task activity."""
import os
from pathlib import Path
import time


CODEX_EXECUTABLES = {'codex', 'codex.exe', 'codex-app-server', 'codex-app-server.exe',
                     'codex app', 'codex desktop'}


def codex_process_state(home):
    import psutil
    home = Path(home).resolve()
    native_home = (Path.home() / '.codex').resolve()
    matching, unknown = [], False
    try:
        for process in psutil.process_iter(('pid', 'name', 'cmdline', 'status')):
            if process.pid == os.getpid():
                continue
            try:
                info = process.info
                if info.get('status') in {'zombie', 'dead'}:
                    continue
                # Helpers/updaters, the gateway and similarly named third-party
                # programs are not a running Codex instance.
                name = (info.get('name') or '').lower()
                command = info.get('cmdline') or []
                executable = str(command[0]).replace('\\', '/').rsplit('/', 1)[-1].lower() if command else ''
                if not name and not executable:
                    unknown = True
                    continue
                if name not in CODEX_EXECUTABLES and executable not in CODEX_EXECUTABLES:
                    continue
                try:
                    configured = process.environ().get('CODEX_HOME')
                except psutil.AccessDenied:
                    unknown = True
                    continue
                uses_home = Path(configured).expanduser().resolve() == home if configured else home == native_home
                if uses_home:
                    matching.append(process.pid)
            except psutil.NoSuchProcess:
                continue
            except (OSError, ValueError, psutil.Error):
                unknown = True
    except (OSError, psutil.Error):
        unknown = True
    return {'status': 'running' if matching else 'unknown' if unknown else 'not_detected',
            'process_count': len(matching), 'observed_at': time.time(),
            'source': 'local_process_scan', 'task_status': 'unknown'}
