"""Private child process entry point; no management HTTP surface."""
import json
import os
import threading
from pathlib import Path

from gateway.activity import Activity


class SharedActivity(Activity):
    def __init__(self, counter):
        self.counter = counter
        # Only child request threads write while running. Parent resets after exit.
        # A process-shared semaphore could remain locked after a hard crash.
        self.lock = threading.Lock()

    def begin(self):
        with self.lock:
            self.counter.value += 1

    def end(self):
        with self.lock:
            self.counter.value -= 1

    def snapshot(self):
        with self.lock:
            active = self.counter.value
        import time
        return {'active_requests': active, 'observed_at': time.time(),
                'gateway_status': 'busy' if active else 'no_activity', 'codex_status': 'unknown'}


def run(connection, settings, settings_path, counter):
    from gateway.server import Gateway, Server
    from management.runtime import ManagementContext
    from desktop.locking import DirectoryLock
    send_lock = threading.Lock()

    def send(value):
        with send_lock:
            connection.send(value)

    context = ManagementContext(settings)
    context.activity = SharedActivity(counter)
    context.record = lambda value: send(('record', value))
    gateway = Gateway(settings, context=context)
    base = gateway.handler()

    class Handler(base):
        def refresh_settings(self):
            # Match the management/CLI lock: one committed settings snapshot per request.
            if settings_path:
                from model_catalog.catalog import ConfigError
                try:
                    with DirectoryLock(Path(settings_path).parent):
                        context.settings = json.loads(Path(settings_path).read_text(encoding='utf-8'))
                except ConfigError as error:
                    if error.code != 'INSTANCE_BUSY':
                        raise
                    # A save is in progress; keep the last committed snapshot.

        def do_GET(self):
            self.refresh_settings()
            super().do_GET()

        def do_POST(self):
            self.refresh_settings()
            super().do_POST()

    try:
        server = Server(('127.0.0.1', settings['port']), Handler)
    except (OSError, ValueError):
        send(('failed', 'FORWARDING_START_FAILED'))
        connection.close()
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    send(('ready', None))
    thread.start()
    try:
        # EOF also stops the child if its management owner dies.
        connection.recv()
    except (EOFError, OSError):
        pass
    finally:
        server.shutdown()
        server.server_close()
        connection.close()
    # No in-flight request may outlive the process owner after shutdown.
    os._exit(0)
