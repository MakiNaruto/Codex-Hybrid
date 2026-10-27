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
    def __init__(self, context):
        self.context = context
        context.runtime = self
        self.server = self.thread = None
        self.lock = threading.RLock()
        self.error = None

    def snapshot(self):
        with self.lock:
            return {'status': 'running' if self.server else 'fault' if self.error else 'stopped',
                    'error': self.error}

    def start(self):
        from gateway.server import Gateway, Server
        with self.lock:
            if self.server:
                return
            try:
                gateway = Gateway(self.context.settings, context=self.context)
                server = Server(('127.0.0.1', self.context.settings['port']), gateway.handler())
                self.thread = threading.Thread(target=server.serve_forever, daemon=True)
                self.thread.start()
                self.server, self.error = server, None
            except OSError:
                self.error = 'FORWARDING_START_FAILED'
                raise ConfigError(self.error) from None

    def stop(self):
        with self.lock:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
                self.thread.join(timeout=2)
                self.server = self.thread = None
            self.error = None

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
                try:
                    runtime.start()
                except ConfigError:
                    record({'status': 'forwarding_start_failed'})
            manager.start_sync()
            record({'status': 'management_listening', 'time': int(time.time())})
            try:
                server.serve_forever()
            finally:
                manager.stop_sync()
                runtime.stop()
