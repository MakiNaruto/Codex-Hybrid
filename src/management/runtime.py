"""Always-on management, independently controlled model forwarding listener."""
import json
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler

from gateway.activity import Activity
from gateway.transport import FreshProxyOpener
from model_catalog.catalog import ConfigError


def management_port(settings):
    port = settings.get('management_port', settings['port'] + 1 if settings['port'] < 65535 else 65534)
    if type(port) is not int or not 1024 <= port <= 65535 or port == settings['port']:
        raise ValueError('management_port must be a distinct unprivileged port (1024–65535)')
    return port


class ManagementContext:
    """Shared immutable settings snapshots and request resources; no listener required."""
    def __init__(self, settings):
        self.settings = settings
        self.started_at = time.monotonic()
        self.slots = threading.BoundedSemaphore(settings['max_concurrent_requests'])
        self.activity = Activity()
        self.opener = FreshProxyOpener()
        self.record = lambda value: None
        self.runtime = None


class ForwardingRuntime:
    RETRY_DELAYS = (1, 3, 10)
    STABLE_SECONDS = 60

    def __init__(self, context):
        import multiprocessing
        from management.forwarding_worker import SharedActivity
        self.mp = multiprocessing.get_context('spawn')
        self.counter = self.mp.Value('i', 0, lock=False)
        self.context = context
        context.runtime = self
        context.activity = SharedActivity(self.counter)
        self.process = self.connection = None
        self.lock = threading.RLock()
        self.error = None
        self.status = 'stopped'
        self.attempt = 0
        self.retry_at = None
        self.retry_deadline = None
        self.started = None
        self.wanted = False
        self.wake = threading.Event()
        self.closed = False
        self.monitor = threading.Thread(target=self._watch, daemon=True)
        self.monitor.start()

    def snapshot(self):
        with self.lock:
            return {'status': self.status, 'error': self.error, 'retry_attempt': self.attempt,
                    'retry_at': self.retry_at, 'retry_limit': len(self.RETRY_DELAYS)}

    def _launch(self):
        from management.forwarding_worker import run
        parent, child = self.mp.Pipe()
        manager = getattr(self.context, 'manager', None)
        path = str(manager.settings_path) if manager else None
        process = self.mp.Process(target=run, args=(child, self.context.settings, path, self.counter), daemon=True)
        try:
            process.start()
            child.close()
            if not parent.poll(10) or parent.recv()[0] != 'ready':
                raise OSError('Child did not become ready')
        except (OSError, EOFError, ValueError):
            child.close()
            parent.close()
            if process.pid:
                if process.is_alive():
                    process.terminate()
                process.join(2)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            self._record({'status': 'forwarding_start_failed'})
            self.status, self.error, self.wanted = 'fault', 'FORWARDING_START_FAILED', False
            self.retry_at = None
            raise ConfigError(self.error) from None
        self.process, self.connection = process, parent
        self.status, self.error, self.retry_at = 'running', None, None
        self.started = time.monotonic()

    def start(self):
        with self.lock:
            if self.closed:
                raise ConfigError('FORWARDING_UNAVAILABLE')
            if self.process and self.process.is_alive():
                return
            self._dispose()
            self.attempt = 0
            self.wanted = True
            self._launch()
        self.wake.set()

    def _dispose(self):
        if self.process:
            self.process.join(2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            self.process.close()
            self.process = None
        if self.connection:
            self.connection.close()
            self.connection = None
        self.counter.value = 0

    def stop(self):
        with self.lock:
            self.wanted = False
            self.retry_at = None
            if self.connection:
                try:
                    self.connection.send('stop')
                except (OSError, EOFError):
                    pass
            self._dispose()
            self.status, self.error = 'stopped', None
            self.attempt = 0
        self.wake.set()

    def close(self):
        self.stop()
        self.closed = True
        self.wake.set()
        self.monitor.join(2)

    def _record(self, value):
        try:
            self.context.record(value)
        except Exception:
            # A diagnostic sink failure must not disable process supervision.
            pass

    def _watch(self):
        while not self.closed:
            self.wake.wait(.1)
            self.wake.clear()
            with self.lock:
                if self.connection:
                    try:
                        while self.connection.poll():
                            kind, value = self.connection.recv()
                            if kind == 'record':
                                self._record(value)
                    except (EOFError, OSError):
                        pass
                if self.process and not self.process.is_alive():
                    exitcode = self.process.exitcode
                    stable = time.monotonic() - self.started >= self.STABLE_SECONDS
                    self._dispose()
                    if self.wanted:
                        if stable:
                            self.attempt = 0
                        if self.attempt < len(self.RETRY_DELAYS):
                            delay = self.RETRY_DELAYS[self.attempt]
                            self.attempt += 1
                            self.retry_at = time.time() + delay
                            self.retry_deadline = time.monotonic() + delay
                            self.status, self.error = 'recovering', 'FORWARDING_EXITED'
                        else:
                            self.wanted = False
                            self.status, self.error = 'fault', 'FORWARDING_RETRIES_EXHAUSTED'
                        self._record({'status': 'forwarding_exited', 'exit_code': exitcode,
                                      'retry_attempt': self.attempt})
                if self.wanted and self.retry_at is not None and time.monotonic() >= self.retry_deadline:
                    try:
                        self._launch()
                        self._record({'status': 'forwarding_restarted', 'retry_attempt': self.attempt})
                    except ConfigError:
                        pass  # _launch records the failure and stops automatic retries.

    def stop_if_safe(self, manager):
        # Disk routing alone does not prove an existing client reloaded it.
        with self.lock:
            if manager.routing_state() != 'openai' or self.context.activity.snapshot()['active_requests']:
                return False
            state = manager.process_state()
            if state['status'] != 'not_detected':
                return False
            self.stop()
            return True


def handler(context):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(180)

        def dispatch(self, method):
            from management.http import handle
            if handle(self, context, method):
                return
            # Compatible liveness probe, with no inference endpoints on this listener.
            body = json.dumps({'service': 'connected-native-gateway', 'version': 1}).encode()
            status = 200 if method == 'GET' and self.path == '/healthz' else 404
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.dispatch('GET')

        def do_POST(self):
            self.dispatch('POST')
    return Handler


def serve(settings_path, record):
    from desktop.locking import DirectoryLock
    from gateway.server import Server, route, sse_events
    from management.service import Management, private_write
    import secrets
    settings_path = Path(settings_path).resolve()
    # Take ownership before reading or writing any instance state, even on another port.
    with DirectoryLock(settings_path.parent, 'service.lock', 'SERVICE_ALREADY_RUNNING'):
        with DirectoryLock(settings_path.parent):
            settings = json.loads(settings_path.read_text(encoding='utf-8'))
            if 'management_token' not in settings:
                settings['management_token'] = secrets.token_urlsafe(32)
                private_write(settings_path, json.dumps(settings))
        context = ManagementContext(settings)
        context.record = record
        manager = context.manager = Management(context, settings_path, route, sse_events)
        runtime = ForwardingRuntime(context)
        # Bind management first: forwarding failure must leave diagnosis available.
        with Server(('127.0.0.1', management_port(settings)), handler(context)) as server:
            if manager.routing_state() == 'project':
                runtime.status = 'recovery_required'
                runtime.error = 'FORWARDING_RECOVERY_REQUIRED'
            manager.start_sync()
            record({'status': 'management_listening', 'time': int(time.time())})
            try:
                server.serve_forever()
            finally:
                manager.stop_sync()
                runtime.close()
