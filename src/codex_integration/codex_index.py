"""Ask the installed Codex to repair thread metadata, without resuming turns."""
import contextlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

from model_catalog.catalog import ConfigError


def find_codex(configured=None):
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.resolve()
        raise ConfigError('SESSION_INDEX_CODEX_UNAVAILABLE')
    candidates = []
    found = shutil.which('codex.exe' if sys.platform == 'win32' else 'codex')
    if found:
        candidates.append(Path(found))
    if sys.platform == 'win32':
        local = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData'/'Local'))
        candidates.extend(sorted((local/'OpenAI'/'Codex'/'bin').glob('*/codex.exe'),
                                 key=lambda p: p.stat().st_mtime, reverse=True))
    else:
        candidates.extend(root/'Codex.app'/'Contents'/'Resources'/'codex'
                          for root in (Path('/Applications'), Path.home()/'Applications'))
    # Includes Store installations and installations outside the usual folder.
    import psutil
    try:
        for process in psutil.process_iter(('name',)):
            if (process.info.get('name') or '').lower() not in {'codex', 'codex.exe'}:
                continue
            try:
                candidates.append(Path(process.exe()))
            except (OSError, psutil.Error):
                pass
    except (OSError, psutil.Error):
        pass
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise ConfigError('SESSION_INDEX_CODEX_UNAVAILABLE')


def repair_index(home, thread_ids, executable=None):
    """Read stored metadata through Codex; never call resume or turn/start.

    Credentials are ephemeral and all HTTP traffic is blocked by a loopback
    proxy. Configuration overrides affect this child only, never config.toml.
    The helper exits before the caller opens its migration write transaction.
    """
    if not thread_ids:
        return
    executable = find_codex(executable)
    env = dict(os.environ, CODEX_HOME=str(home))
    for name in list(env):
        if name.startswith(('CODEX_INTERNAL_', 'CODEX_APP_SERVER_')) or name in {
            'OPENAI_API_KEY', 'OPENAI_ORG_ID', 'OPENAI_ORGANIZATION', 'OPENAI_PROJECT_ID',
        }:
            env.pop(name)
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        env[name] = 'http://127.0.0.1:9'
    env['NO_PROXY'] = env['no_proxy'] = ''
    command = [str(executable), 'app-server', '--stdio',
               '-c', 'cli_auth_credentials_store="ephemeral"',
               '-c', 'analytics.enabled=false', '-c', 'feedback.enabled=false']
    process = None
    messages = queue.Queue()
    sequence = 0
    try:
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        process = subprocess.Popen(command, cwd=home, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **options)

        def read():
            try:
                for line in process.stdout:
                    value = json.loads(line)
                    # Ignore notifications and their potentially private payloads.
                    if 'id' in value:
                        messages.put(value)
            except (OSError, ValueError):
                pass
            finally:
                messages.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def send(value):
            process.stdin.write((json.dumps(value) + '\n').encode())
            process.stdin.flush()

        def call(method, params):
            nonlocal sequence
            sequence += 1
            send({'id': sequence, 'method': method, 'params': params})
            deadline = time.monotonic() + 20
            while True:
                response = messages.get(timeout=max(0, deadline - time.monotonic()))
                if response is None or response.get('error'):
                    raise ConfigError('SESSION_INDEX_REPAIR_FAILED')
                # Decline unexpected server requests; no tools or approvals are
                # needed for metadata reads and no external side effects are allowed.
                if 'method' in response:
                    raise ConfigError('SESSION_INDEX_REPAIR_FAILED')
                if response.get('id') == sequence:
                    return

        call('initialize', {'clientInfo': {'name': 'codex_hybrid_index_repair', 'version': '0.1.0'}})
        send({'method': 'initialized', 'params': {}})
        for thread_id in sorted(thread_ids):
            call('thread/read', {'threadId': thread_id, 'includeTurns': False})
    except (OSError, queue.Empty, ValueError):
        raise ConfigError('SESSION_INDEX_REPAIR_FAILED') from None
    finally:
        if process is not None:
            with contextlib.suppress(OSError):
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdout.close()
