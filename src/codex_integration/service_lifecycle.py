"""Gateway readiness and process lifecycle, scoped to an explicit runtime."""
import json
import os
import subprocess
import sys

from infrastructure.files import write_snapshot_bytes as private_write
from codex_integration.paths import ROOT, RUNTIME
import signal
import time
import urllib.request

WINDOWS = sys.platform == 'win32'


def health(settings, ensure_forwarding=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    from management.runtime import management_port
    failure = None
    for port in (management_port(settings), settings['port']):
        try:
            with opener.open(f'http://127.0.0.1:{port}/healthz', timeout=3) as response:
                if json.load(response) != {'service': 'connected-native-gateway', 'version': 1}:
                    raise ValueError('Unexpected service at the configured port')
        except (OSError, ValueError) as error:
            failure = error
            continue
        if ensure_forwarding and port == management_port(settings):
            ensure_forwarding_ready(settings)
        return
    raise failure


def ensure_forwarding_ready(settings):
    from management.runtime import management_port, FORWARDING_CONTROL_TIMEOUT
    request = urllib.request.Request(
        f'http://127.0.0.1:{management_port(settings)}/manage/api/forwarding/ensure',
        data=b'{}', headers={'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + settings.get('management_token', '')})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=FORWARDING_CONTROL_TIMEOUT) as response:
        json.load(response)


def start_service(settings, *, runtime=RUNTIME, root=ROOT, windows=WINDOWS):
    try:
        health(settings)
    except (OSError, ValueError):
        healthy = False
    else:
        healthy = True
    if healthy:
        if not (runtime / 'service.pid').exists():
            matches = list(owned_gateway_processes(runtime=runtime, root=root))
            if len(matches) == 1:
                private_write(runtime / 'service.pid', str(matches[0].pid))
            elif len(matches) > 1:
                raise ValueError('Multiple gateway processes use this runtime')
            else:
                raise ValueError('Port is serving a gateway not owned by this runtime')
        return print('本机服务已在运行')
    # Keep inherited startup stderr separate: Windows cannot rotate an inherited open file.
    with (runtime / 'service.startup.stderr').open('wb') as err:
        # Suppress the console throughout Windows venv interpreter redirection.
        # DETACHED_PROCESS can let the redirected console executable create a new window.
        options = ({'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                   if windows else {'start_new_session': True})
        entry = ([str(root / 'src/gateway/entry.py')] if (root / 'src/gateway/entry.py').is_file()
                 else ['-m', 'gateway.server'])
        process = subprocess.Popen([sys.executable, *entry,
            '--settings', str(runtime / 'settings.json')], cwd=root, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=err, **options)
    for _ in range(30):
        if process.poll() is not None:
            raise ValueError(f'网关在就绪前退出（退出码 {process.returncode}）；请检查 '
                             f'{runtime / "service.stderr"} 和 {runtime / "service.startup.stderr"}')
        try:
            health(settings)
            break
        except (OSError, ValueError):
            time.sleep(.1)
    else:
        process.terminate()
        raise ValueError(f'管理服务启动后约 3 秒内未通过就绪检查；'
                         '请检查端口占用、服务日志和本机网络权限')
    private_write(runtime / 'service.pid', str(process.pid))
    print('本机服务已启动并通过就绪检查')


def stop_windows_process(pid, missing_ok=False, *, runtime=RUNTIME, root=ROOT):
    # psutil retains process identity across PID reuse when terminating/waiting.
    import psutil
    try:
        process = psutil.Process(pid)
        command = process.cmdline()
        script = str(root / 'src/gateway/entry.py')
        settings = str(runtime / 'settings.json')
        normalize = lambda value: os.path.normcase(os.path.abspath(value))
        owned_entry = (len(command) >= 2 and normalize(command[1]) in {
            normalize(script), normalize(root / 'scripts/gateway.py'),
            normalize(root / 'native_gateway/server.py')}) or command[1:3] == ['-m', 'gateway.server']
        if (len(command) < 4 or not owned_entry
                or '--settings' not in command
                or command.index('--settings') + 1 >= len(command)
                or normalize(command[command.index('--settings') + 1]) != normalize(settings)):
            raise ValueError('PID does not belong to this gateway')
        process.terminate()
        process.wait(timeout=10)
    except psutil.NoSuchProcess:
        if not missing_ok:
            raise ValueError('Gateway process is no longer running') from None
    except (psutil.AccessDenied, psutil.TimeoutExpired):
        raise ValueError('Unable to stop gateway; check process permissions and status') from None


def owned_gateway_processes(*, runtime=RUNTIME, root=ROOT):
    """Find this runtime's gateway when an older launch omitted service.pid."""
    import psutil

    script_paths = {os.path.normcase(os.path.abspath(root / path)) for path in
                    ('src/gateway/entry.py', 'scripts/gateway.py', 'native_gateway/server.py')}
    expected_settings = os.path.normcase(os.path.abspath(runtime / 'settings.json'))
    for process in psutil.process_iter(('pid', 'cmdline')):
        try:
            command = process.info['cmdline'] or []
            if len(command) < 3:
                continue
            entry = ((len(command) > 1 and os.path.normcase(os.path.abspath(command[1])) in script_paths)
                     or command[1:3] == ['-m', 'gateway.server'])
            if not entry or '--settings' not in command:
                continue
            index = command.index('--settings') + 1
            if index < len(command) and os.path.normcase(os.path.abspath(command[index])) == expected_settings:
                yield process
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue


def stop_service(missing_ok=False, *, runtime=RUNTIME, root=ROOT, windows=WINDOWS):
    from codex_integration.locking import DirectoryLock
    with DirectoryLock(runtime):
        return _stop_service_locked(missing_ok, runtime=runtime, root=root, windows=windows)


def _stop_service_locked(missing_ok=False, *, runtime, root, windows):
    pid_path = runtime / 'service.pid'
    pid = int(pid_path.read_text()) if pid_path.exists() else None
    if pid is not None and pid <= 0:
        raise ValueError('Invalid gateway PID')
    if pid is None:
        matches = list(owned_gateway_processes(runtime=runtime, root=root))
        if not matches:
            if missing_ok:
                return
            raise ValueError('Gateway process is not recorded and was not found')
        if len(matches) > 1:
            raise ValueError('Multiple gateway processes use this runtime; refusing to stop them')
        pid = matches[0].pid
    if windows:
        stop_windows_process(pid, missing_ok, runtime=runtime, root=root)
        pid_path.unlink(missing_ok=True)
        return
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], text=True, capture_output=True)
    if result.returncode == 1 and not result.stdout.strip() and missing_ok:
        pid_path.unlink()
        return
    result.check_returncode()
    owned_entry = any(str(root / path) in result.stdout for path in
                      ('src/gateway/entry.py', 'scripts/gateway.py', 'native_gateway/server.py')) or ' -m gateway.server ' in result.stdout
    if not owned_entry or str(runtime / 'settings.json') not in result.stdout:
        raise ValueError('PID does not belong to this gateway')
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while True:
        status = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], text=True, capture_output=True)
        if status.returncode == 1 and not status.stdout.strip():
            break
        status.check_returncode()
        if status.stdout.strip().startswith('Z'):
            break
        if time.monotonic() >= deadline:
            raise ValueError('Gateway did not stop; refusing to start a second process')
        time.sleep(.1)
    pid_path.unlink(missing_ok=True)
