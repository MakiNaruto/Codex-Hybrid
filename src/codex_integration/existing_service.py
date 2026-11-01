"""macOS desktop adapter for an already-owned local management service."""
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

from model_catalog.catalog import ConfigError
from management.runtime import management_port


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ExistingService:
    def __init__(self, settings, directory):
        self.directory = Path(directory).resolve()
        self._verify_owner()
        self.origin = f'http://127.0.0.1:{management_port(settings)}'
        self.token = settings.get('management_token', '')
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _verify_owner(self):
        import psutil
        try:
            pid = int((self.directory / 'service.pid').read_text())
            command = psutil.Process(pid).cmdline()
            index = command.index('--settings') + 1
            entry = (command[1:3] == ['-m', 'gateway.server'] or
                     (len(command) > 1 and Path(command[1]).name in {'entry.py', 'gateway.py', 'server.py'}))
            if not entry or Path(command[index]).resolve() != self.directory / 'settings.json':
                raise ValueError('Unrelated service')
        except (OSError, ValueError, IndexError, psutil.Error):
            raise ConfigError('SERVICE_ALREADY_RUNNING') from None

    def api(self, path, method='GET', body=None):
        self._verify_owner()
        # Callers validate the same private API allowlist before reaching here.
        headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}
        data = json.dumps(body).encode() if method == 'POST' else None
        request = Request(self.origin + '/manage/api/' + path, data=data, headers=headers, method=method)
        timeout = 75 if path == 'test' else 120 if method == 'POST' else 15
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                code = json.load(error).get('code')
            except (ValueError, TypeError):
                code = None
            from codex_integration.web_api import ERRORS
            raise ConfigError(code if code in ERRORS else 'SERVICE_UNREACHABLE') from None
        except (OSError, URLError, ValueError):
            raise ConfigError('SERVICE_UNREACHABLE') from None
