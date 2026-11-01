"""Persistent private desktop owner. No management HTTP listener or auto activation."""
from contextlib import ExitStack
import json
import sys
from pathlib import Path

from desktop import management, web_api
from desktop.locking import DirectoryLock
from desktop.snapshot import snapshot
from desktop.restart import Restart
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
              'shutdown': set(), 'recover_forwarding': set(),
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
            from desktop.existing_service import ExistingService
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
                'restart_supported': sys.platform == 'darwin',
                'activity': self.manager.activity_state(), 'codex_process': self.manager.process_state(),
                'desktop_preferences': self.manager.desktop_preferences(),
                'recovery_required': mode == 'project' and forwarding['status'] in ('stopped', 'fault')}

    def handle(self, request):
        action = request['action']
        if action == 'web_api':
            return web_api.handle(self, request)
        if action in ('preview_restart', 'cancel_restart', 'restart_codex') and sys.platform != 'darwin':
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
        if action == 'shutdown':
            # A failed attempt to claim another service must not trap this window.
            if self.runtime is not None:
                self.ensure_manager()
                if self.manager.routing_state() == 'project':
                    raise ConfigError('EXIT_BLOCKED')
                if self.runtime.snapshot()['status'] != 'stopped' and not self.runtime.stop_if_safe(self.manager):
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
                return management.save(self.manager, request)
        if action == 'test_connection':
            return self.manager.test_connection(request['key'])
        if action == 'save_desktop_preferences':
            return self.manager.save_desktop_preferences(request['mode'], request['value'])
        if action == 'preview_routing':
            preview = self.manager.preview_routing(request['mode'])
            self.pending = preview
            # Do not expose session filenames, config contents or arbitrary warning text.
            return {key: preview[key] for key in ('mode', 'revision', 'desktop', 'desktop_ticket',
                    'session_count', 'model_change_count', 'index_repair_count', 'missing_rollouts',
                    'activity', 'codex_process')}
        if action == 'recover_forwarding':
            if self.manager.routing_state() != 'project':
                raise ConfigError('FORWARDING_UNAVAILABLE')
            self.runtime.start()
            if self.manager.routing_state() != 'project':
                self.runtime.stop_if_safe(self.manager)
                raise ConfigError('CLIENT_CONFIG_CHANGED')
            return self.runtime.snapshot()
        if action == 'set_routing':
            pending, self.pending = self.pending, None
            if pending is None or any(request[key] != pending[key] for key in ('mode', 'revision', 'desktop_ticket')):
                raise ConfigError('INVALID_PREVIEW')
            try:
                return self.manager.set_routing(request['mode'], request['revision'], request['confirm_activity'],
                    request['desktop_action'], request['desktop_was_running'], request['desktop_ticket'])
            except Exception:
                # Failed activation may have started forwarding; stop only if proven safe.
                try:
                    self.runtime.stop_if_safe(self.manager)
                except Exception:
                    pass
                raise
        raise ConfigError('INVALID_REQUEST')

    def request(self, request):
        try:
            validate(request)
            if self.closed:
                raise ConfigError('FORWARDING_UNAVAILABLE')
            return {'ok': True, 'result': self.handle(request)}
        except Exception as error:
            if isinstance(request, dict) and request.get('action') == 'web_api' and not isinstance(error, ConfigError):
                from gateway.transport import error_event
                return {'ok': False, 'error': error_event(error, 'management')['code']}
            code = error.code if isinstance(error, ConfigError) else None
            return {'ok': False, 'error': code if code in ERRORS else 'OPERATION_FAILED'}

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.runtime is not None:
                self.runtime.close()
        finally:
            try:
                if self.manager is not None:
                    self.manager.close()
            finally:
                self.locks.close()


def main():
    import sys
    controller = Controller()
    try:
        while True:
            line = sys.stdin.buffer.readline(65537)
            if not line:
                break
            try:
                if len(line) > 65536:
                    # A framing violation ends the session, never parse the remainder as a command.
                    print(json.dumps({'ok': False, 'error': 'INVALID_REQUEST'}), flush=True)
                    break
                result = controller.request(json.loads(line))
            except Exception:
                result = {'ok': False, 'error': 'INVALID_REQUEST'}
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if controller.closed:
                break
    finally:
        # Owner loss is crash cleanup, not a successful safe exit. Keep routing/baseline
        # on disk for explicit recovery next launch; no worker may outlive its owner.
        controller.close()
