#!/usr/bin/env python3
"""Local desktop provider. Tool execution stays inside the official Codex backend."""
import argparse
import http.server
import json
from pathlib import Path
import socketserver
import time

from gateway.transport import FreshProxyOpener, records as sse_events
from model_catalog.legacy_config import load_config
from gateway.http_handler import make_handler

# Preserve the established gateway.server function entry points.
from gateway.routing import (
    OPENAI_URL, MAX_BODY, OFFICIAL_HEADER_DENY, coordinated, official_header_passthrough,
    official_headers, resolve_requested_model, external_route, route,
)
from gateway.official_catalog import (
    OPENAI_MODELS_URL, authenticated_official_catalog, refresh_official_directory, cached_directory,
)
from gateway.streaming import (
    MAX_UNKNOWN_TOOL_RETRIES, OFFICIAL_UPSTREAM_TIMEOUT_SECONDS, usage_fields,
    connection_diagnostic, adapted_stream, retry_payload_after_unknown_tool,
)


class Gateway:
    def __init__(self, settings, settings_path=None, context=None):
        self.context = context
        self.settings_path = Path(settings_path) if settings_path else None
        self.started_at = time.monotonic()
        self.record = lambda observation: print(json.dumps(observation), flush=True)
        self.settings = settings
        self.deepseek = None if 'source' in settings else load_config(settings['env_file'])
        if self.deepseek and self.deepseek['DEEPSEEK_MODEL'] != settings['deepseek_model']:
            raise ValueError('DeepSeek model changed; prepare a matching catalog first')
        from gateway.activity import Activity
        self.activity = Activity()
        # No redirects: credentials can only go to the fixed official endpoints.
        self.opener = FreshProxyOpener(settings.get('upstream_proxy'))
        if context is not None:
            self.activity, self.opener = context.activity, context.opener
            self.record = context.record
        self.manager = None
        if settings_path is not None and 'source' in settings:
            from management.service import Management
            from infrastructure.files import write_private_text as private_write
            import secrets
            if 'management_token' not in settings:
                settings['management_token'] = secrets.token_urlsafe(32)
                private_write(settings_path, json.dumps(settings))
            self.manager = Management(self, settings_path, route, sse_events)

    @property
    def settings(self):
        return self.context.settings if self.context is not None else self._settings

    @settings.setter
    def settings(self, value):
        if self.context is not None:
            self.context.settings = value
        else:
            self._settings = value

    def handler(self):
        return make_handler(self)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # Avoid reverse DNS lookup during startup.
        socketserver.TCPServer.server_bind(self)
        self.server_name = '127.0.0.1'
        self.server_port = self.server_address[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    args = parser.parse_args()
    from infrastructure.locking import DirectoryLock
    from infrastructure.runtime_log import RuntimeLog
    from management.runtime import serve
    import sys
    with DirectoryLock(args.settings.resolve().parent, 'service.lock', 'SERVICE_ALREADY_RUNNING'):
        runtime_log = RuntimeLog(args.settings.resolve().parent)
        previous_stderr = sys.stderr
        sys.stderr = runtime_log.stderr
        try:
            serve(args.settings, runtime_log.emit)
        finally:
            sys.stderr = previous_stderr
            runtime_log.close()


if __name__ == '__main__':
    main()
