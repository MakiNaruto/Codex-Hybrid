"""Single-use restart previews. Called only by the macOS desktop controller."""
import secrets
import time

from desktop import client
from model_catalog.catalog import ConfigError


class Restart:
    def __init__(self, home):
        self.home = home
        self.pending = None

    @staticmethod
    def identities(target):
        return sorted((process.pid, process.create_time()) for process in client.processes(target))

    def cancel(self):
        self.pending = None

    def preview(self, activity):
        self.cancel()
        target, identities, status = None, [], 'unavailable'
        try:
            target = client.discover(self.home)
            if target:
                identities = self.identities(target)
                status = 'running' if identities else 'not_running'
        except Exception:
            status = 'unknown'
        ticket = secrets.token_urlsafe(32)
        available = status == 'running'
        if available:
            self.pending = (ticket, time.monotonic() + 120, target, identities)
        return {'ticket': ticket, 'available': available, 'status': status, 'activity': activity}

    def confirm(self, ticket):
        pending, self.pending = self.pending, None
        if pending is None or not secrets.compare_digest(ticket, pending[0]) or time.monotonic() > pending[1]:
            raise ConfigError('INVALID_PREVIEW')
        _, _, target, identities = pending
        try:
            if client.discover(self.home) != target or self.identities(target) != identities:
                raise ConfigError('INVALID_PREVIEW')
        except ConfigError:
            raise
        except Exception:
            raise ConfigError('INVALID_PREVIEW') from None
        try:
            if not client.close(target):
                return {'desktop_result': 'close_failed'}
        except Exception:
            return {'desktop_result': 'close_failed'}
        try:
            outcome = client.launch(target)
            return {'desktop_result': outcome if outcome in ('started', 'launch_unconfirmed') else 'launch_unconfirmed'}
        except Exception:
            return {'desktop_result': 'launch_unconfirmed'}
