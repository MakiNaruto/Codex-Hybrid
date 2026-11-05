"""Allowlisted private adapter for the shared management page; never opens HTTP."""
import sys
import re

from model_catalog.catalog import ConfigError


READS = {'state', 'activity', 'processes', 'diagnostics?days=1', 'diagnostics?days=7',
         'diagnostics?days=30', 'diagnostics?days=all',
         'usage?period=today', 'usage?period=yesterday', 'usage?period=7', 'usage?period=30',
         'usage?days=1', 'usage?days=7', 'usage?days=30'}
WRITES = {
    'source': ({'mode'}, {'cc_db_path'}),
    'models': ({'source_id', 'updates'}, set()),
    'provider': ({'id'}, {'spec', 'api_key', 'delete'}),
    'publish': (set(), set()),
    'test': ({'key'}, set()),
    'routing/preview': ({'mode'}, set()),
    'routing': ({'mode', 'revision', 'confirm_activity', 'desktop_action',
                 'desktop_was_running', 'desktop_ticket'}, set()),
    'desktop/preferences': ({'mode', 'value'}, set()),
    'runtime/recover': (set(), set()),
}


def validate(request):
    if set(request) != {'action', 'path', 'method', 'body'}:
        raise ConfigError('INVALID_REQUEST')
    path, method, body = request['path'], request['method'], request['body']
    if not isinstance(path, str) or not isinstance(method, str):
        raise ConfigError('INVALID_REQUEST')
    if method == 'GET' and body is None and (path in READS or re.fullmatch(r'diagnostics/errors/[0-9a-f]{64}', path)):
        return
    if method == 'POST' and path in WRITES and isinstance(body, dict):
        required, optional = WRITES[path]
        if required <= set(body) <= required | optional:
            # Reuse controller validation for preview-bound lifecycle operations.
            actions = {'routing/preview': 'preview_routing', 'routing': 'set_routing',
                       'desktop/preferences': 'save_desktop_preferences'}
            if path in actions:
                from codex_integration.controller import validate as validate_control
                validate_control({'action': actions[path], **body})
            return
    raise ConfigError('INVALID_REQUEST')


def handle(controller, request):
    path, body = request['path'], request['body']
    if not controller.ensure_manager():
        if path == 'state':
            return {'configured': False}
        raise ConfigError('NOT_CONFIGURED')
    if controller.existing_service is not None:
        if request['method'] == 'POST':
            controller.restart.cancel()
        result = controller.existing_service.api(path, request['method'], body)
        if path == 'state':
            result.update(configured=True, restart_supported=True, external_service=True)
        return result
    manager = controller.manager
    if path == 'state':
        return dict(manager.view(), configured=True, restart_supported=sys.platform in ('darwin', 'win32'))
    if path == 'activity':
        return manager.activity_state()
    if path == 'processes':
        return manager.process_state()
    if path.startswith('usage?period=') or path.startswith('usage?days='):
        from management.usage import report
        return report(manager.directory, days=path.split('=', 1)[1],
                      labels=manager.model_labels())
    if path.startswith('diagnostics?days='):
        from management.diagnostics import report
        days = path.split('=', 1)[1]
        return report(manager, days=None if days == 'all' else int(days), include_