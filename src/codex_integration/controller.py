"""Persistent private desktop owner. No management HTTP listener or auto activation."""
from contextlib import ExitStack
import json
import sys
from pathlib import Path

from codex_integration import management, web_api
from codex_integration.locking import DirectoryLock
from codex_integration.snapshot import snapshot
from codex_integration.restart import Restart
from model_catalog.catalog import ConfigError

ERRORS = management.ERRORS | web_api.ERRORS | {'EXIT_BLOCKED', 'CLIENT_CONFIG_CHANGED', 'INVALID_PREVIEW',
    'FORWARDING_START_FAILED', 'FORWARDING_UNAVAILABLE', 'CLIENT_BASELINE_UNAVAILABLE',
    'CLIENT_ROUTING_UNAVAILABLE', 'CLIENT_ROUTING_ALREADY_SET', 'SESSION_MIGRATION_CHANGED',
    'SESSION_MIGRATION_CODEX_RUNNING', 'SESSION_MIGRATION_PROCESS_CHECK_FAILED',
    'SESSION_MIGRATION_RECOVERY_REQUIRED', 'SESSION_INDEX_REPAIR_INCOMPLETE', 'SERVICE_UNREACHABLE'}


def validate(request):
    if not isinstance(request, dict):
        raise ConfigError('INVALID_REQUEST')
    action = request.get('action')
    if action == 'web_api':
        web_api.validate(request)
        return
    if action in ('initialize', 'save_provider', 'test_connection'):
        management.validate(request)
        return
    fields = {'snapshot': set(), 'status': set(), 'cancel_preview': set(),
              'shutdown': set(), 'shutdown_confirmed': set(), 'recover_forwarding': set(),
              'preview_restart': set(), 'cancel_restart': set(), 'restart_codex': {'ticket', 'confirm_activity'},
              'preview_routing': {'mode'}, 'set_routing': {'mode', 'revision',
              'confirm_activity', 'desktop_action', 'desktop_was_running', 'desktop_ticket'},
              'save_desktop_preferences': {'mode', 'value'}}
    if not isinstance(action, str) or action not in fields or set(request) != {'action'} | fields[action]:
        raise ConfigError('INVALID_REQUEST')
    if action in ('preview_routing', 'set_routing') and request['mode'] not in ('project', 'openai'):
        raise ConfigError('INVALID_REQUEST')
    if action == 'set_routing':
        if any(type(request[key]) is not bool for key in ('confirm_activity', 'desktop_action', 'desktop_was_running')):
            raise ConfigError('INVALID_REQUEST')
        if any(not isinstance(request[key], str) for key in ('revision', 'desktop_ticket')):
            raise ConfigError('INVALID_REQUEST')
    if action == 'restart_codex' and (not isinstance(request['ticket'], str)
            or type(request['confirm_activity']) is not bool):
        raise ConfigError('INVALID_REQUEST')
    if action == 'save_desktop_preferences' and (request['mode'] not in ('project', 'openai')
            or request['value'] not in ('ask', 'auto', 'never')):
        raise ConfigError('INVALID_REQUEST')


class Controller:
    def __init__(self, *, directory=None, codex_home=None, runtime_factory=None):
        self.directory = Path(directory) if directory is not None else Path.home() / '.codex-hybrid'
        self.codex_home = Path(codex_home) if codex_home is not None else Path.home() / '.codex'
        self.runtime_factory = runtime_factory
        self.locks = ExitStack()
        self.owned = False
        self.manager = self.runtime = self.context = None
        self.existing_service = None
        self.pending = None
        self.closed = False
        self.restart = Restart(self.codex_home)

    def own(self):
        if not self.owned:
            self.locks.enter_context(DirectoryLock(self.directory, 'service.lock', 'SERVICE_ALREADY_RUNNING'))
            self.owned = True

    def ensure_manager(self):
        if self.existing_service is not None:
            return True
        if self.manager is not None:
            with self.manager.lock:
                pass  # Refresh an externally committed settings snapshot.
            return True
        path = self.directory / 'settings.json'
        if not path.is_file():
            return False
        try:
            self.own()
        except ConfigError as error:
            if sys.platform != 'darwin' or error.code != 'SERVICE_ALREADY_RUNNING':
                raise
            from codex_integration.existing_service import ExistingService
            service = ExistingService(json.loads(path.read_text(encoding='utf-8')), self.directory)
            service.api('state')  # Verify the local service before retaining the adapter.
            self.existing_service = service
            return True
        from management.runtime import ManagementContext, ForwardingRuntime
        from management.service import Management
        from gateway.server import route, sse_events
        self.context = ManagementContext(json.loads(path.read_text(encoding='utf-8')))
        self.manager = self.context.manager = Management(self.context, path, route, sse_events)
        self.runtime = (self.runtime_factory or ForwardingRuntime)(self.context)
        # Match the web service: fill CC's in-memory catalog before the first
        # view, then keep watching saved sources while the window is hidden.
        # This publishes model metadata only; it never enables routing or starts Codex.
        self.manager.start_sync()
        return True

    def status(self):
        if not self.ensure_manager():
            return {'configured': False, 'routing': 'unavailable', 'forwarding': {'status': 'stopped'},
                    'recovery_required': False}
        if self.existing_service is not None:
            state = self.existing_service.api('state')
            return {'configured': True, 'routing': state['routing_mode'],
                    'forwarding': state['forwarding'], 'restart_supported': True,
                    'external_service': True, 'recovery_required': False}
        mode = self.manager.routing_state()
        forwarding = self.runtime.snapshot()
        return {'configured': True, 'routing': mode, 'forwarding': forwarding,
                'restart_supported': sys.platform in ('darwin', 'win32'),
                'activity': self.manager.activity_state(), 'codex_process': self.manager.process_state(),
                'desktop_preferences': self.manager.desktop_preferences(),
                'recovery_required': mode == 'project' and forwarding['status'] in ('stopped', 'fault')}

    def handle(self, request):
        action = request['action']
        if action == 'web_api':
            return web_api.handle(self, request)
        if action in ('preview_restart', 'cancel_restart', 'restart_codex') and sys.platform not in ('darwin', 'win32'):
            raise ConfigError('INVALID_REQUEST')
        if action in ('initialize', 'save_provider', 'preview_routing', 'set_routing', 'recover_forwarding'):
            self.restart.cancel()
        if action == 'initialize':
            self.own()
            with DirectoryLock(self.directory):
                result = management.initialize(self.directory, self.codex_home)
            self.ensure_manager()
            return result
        if action == 'snapshot':
            self.ensure_manager()
            return snapshot(self.directory)
        if action == 'status':
            return self.status()
        if action == 'cancel_preview':
            self.pending = None
            return {'cancelled': True}
        if action == 'shutdown_confirmed':
            if sys.platform != 'win32':
                raise ConfigError('INVALID_REQUEST')
            # Close our controller and worker, keeping the saved routing choice.
            self.close()
            return {'stopped': True}
        if action == 'shutdown':
            # A failed attempt to claim another service must not trap this window.
            if self.runtime is not None:
                self.ensure_manager()
                mode = self.manager.routing_state()
                if mode == 'project':
                    raise ConfigError('EXIT_BLOCKED')
                if self.runtime.snapshot()['status'] != 'stopped':
                    if sys.platform == 'win32':
                        # An idle retained gateway does not require a prompt
                        # just because Codex is open after routing was disabled.
                        if (mode not in {'openai', 'external'}
                                or self.manager.activity_state()['active_requests'] != 0):
                            raise ConfigError('EXIT_BLOCKED')
                    elif not self.runtime.stop_if_safe(self.manager):
                        raise ConfigError('EXIT_BLOCKED')
            self.close()
            return {'stopped': True}
        if not self.ensure_manager():
            raise ConfigError('NOT_CONFIGURED')
        if action in ('preview_restart', 'cancel_restart', 'restart_codex'):
            if action == 'cancel_restart':
                self.restart.cancel()
                return {'cancelled': True}
            # Read the current owner's state again at confirmation time.
            if self.existing_service is not None:
                state = self.existing_service.api('state')
                mode, forwarding = state['routing_mode'], state['forwarding']
            else:
                mode, forwarding = self.manager.routing_state(), self.runtime.snapshot()
            # Do not reopen a client into an unavailable gateway.
            if mode == 'project' and forwarding['status'] != 'running':
                self.restart.cancel()
                raise ConfigError('FORWARDING_UNAVAILABLE')
            if action == 'preview_restart':
                self.pending = None
                activity = (self.existing_service.api('activity') if self.existing_service is not None
                            else self.manager.activity_state())
                return self.restart.preview(activity)
            if not request['confirm_activity']:
                self.restart.cancel()
                raise ConfigError('INVALID_REQUEST')
            return self.restart.confirm(request['ticket'])
        if self.existing_service is not None:
            raise ConfigError('SERVICE_ALREADY_RUNNING')
        if action == 'save_provider':
            self.pending = None
            with self.manager.lock:
                return management