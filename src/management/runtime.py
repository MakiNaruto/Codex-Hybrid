"""Always-on management, independently controlled model forwarding listener."""
import json
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler

from gateway.activity import Activity
from gateway.transport import FreshProxyOpener
from management.supervisor import (
    ForwardingRuntime,
    FORWARDING_START_TIMEOUT as FORWARDING_START_TIMEOUT,
    FORWARDING_CONTROL_TIMEOUT as FORWARDING_CONTROL_TIMEOUT,
    FAILURE_REASONS as FAILURE_REASONS,
)


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
        self.activity = Activity()
        self.opener = FreshProxyOpener(settings.get('upstream_proxy'))
        self.record = lambda value: None
        self.runtime = None




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
    from infrastructure.locking import DirectoryLock
    from gateway.server import Server, route, sse_events
    from management.service import Management
    from infrastructure.files import write_private_text as private_write
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
                runtime.restore()
            manager.start_sync()
            record({'status': 'management_listening', 'time': int(time.time())})
            try:
                server.serve_forever()
            finally:
                manager.close()
                runtime.close()
