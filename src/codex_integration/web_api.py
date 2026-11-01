"""Allowlisted private adapter for the shared management page; never opens HTTP."""
import sys

from model_catalog.catalog import ConfigError


READS = {'state', 'activity', 'processes', 'diagnostics?days=1', 'diagnostics?days=7',
         'diagnostics?days=30', 'diagnostics?days=all',
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
    if method == 'GET' and path in READS and body is None:
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
        return dict(manager.view(), configured=True, restart_supported=sys.platform == 'darwin')
    if path == 'activity':
        return manager.activity_state()
    if path == 'processes':
        return manager.process_state()
    if path.startswith('usage?days='):
        from management.usage import report
        return report(manager.directory, days=int(path.split('=', 1)[1]))
    if path.startswith('diagnostics?days='):
        from management.diagnostics import report
        days = path.split('=', 1)[1]
        return report(manager, days=None if days == 'all' else int(days))
    actions = {'routing/preview': 'preview_routing', 'routing': 'set_routing',
               'desktop/preferences': 'save_desktop_preferences', 'runtime/recover': 'recover_forwarding'}
    if path in actions:
        result = controller.handle({'action': actions[path], **body})
        if path == 'routing/preview':
            # Same fixed migration warnings and impact summary as the browser page.
            result.update({key: controller.pending[key] for key in ('warnings', 'changes')})
        return result
    if path == 'test':
        return manager.test_connection(body['key'])
    controller.pending = None
    controller.restart.cancel()
    if path == 'source':
        return manager.set_source(body['mode'], body.get('cc_db_path'))
    if path == 'models':
        return manager.save_models(body['source_id'], body['updates'])
    if path == 'provider':
        return manager.save_provider(body['id'], body.get('spec'), body.get('api_key'), body.get('delete', False))
    if path == 'publish':
        return manager.publish()
    raise ConfigError('INVALID_REQUEST')


# Fixed business error codes only; no exception messages cross the IPC boundary.
ERRORS = frozenset({
    'CC_CONFIG_CHANGED_RELOAD', 'CC_CONFIG_INVALID', 'CC_CUSTOM_HEADERS_NOT_SUPPORTED',
    'CC_DATABASE_UNAVAILABLE', 'CC_MODE_IS_READ_ONLY', 'CC_OFFICIAL_LOGIN_NOT_SUPPORTED',
    'CC_PROTOCOL_NOT_SUPPORTED', 'CC_STATIC_API_KEY_REQUIRED', 'CLIENT_BASELINE_UNAVAILABLE',
    'CLIENT_CONFIG_CHANGED', 'CLIENT_ROUTING_ALREADY_SET', 'CLIENT_ROUTING_UNAVAILABLE',
    'CONCURRENCY_LIMIT', 'CONFIG_AMBIGUOUS_CREDENTIALS', 'CONFIG_DEFAULT_MODEL_DISABLED',
    'CONFIG_DEFAULT_MODEL_UNKNOWN', 'CONFIG_DUPLICATE_KEY', 'CONFIG_DUPLICATE_MODEL_KEY',
    'CONFIG_INVALID_BASE_URL', 'CONFIG_INVALID_ENABLED', 'CONFIG_INVALID_ENV_NAME',
    'CONFIG_INVALID_IDENTIFIER', 'CONFIG_INVALID_LIMIT', 'CONFIG_INVALID_PARAMETERS',
    'CONFIG_INVALID_RESPONSES_COMPATIBILITY', 'CONFIG_INVALID_STRING', 'CONFIG_INVALID_TOKEN_FIELD',
    'CONFIG_INVALID_YAML', 'CONFIG_KEYS_MUST_BE_STRINGS', 'CONFIG_MAPPING_REQUIRED',
    'CONFIG_MISSING_FIELD', 'CONFIG_MODELS_REQUIRED', 'CONFIG_PARAMETERS_MUST_BE_JSON',
    'CONFIG_PROVIDERS_REQUIRED', 'CONFIG_RESERVED_PARAMETER', 'CONFIG_TOO_LARGE',
    'CONFIG_UNKNOWN_FIELD', 'CONFIG_UNSUPPORTED_PROTOCOL', 'CONFIG_UNSUPPORTED_PROTOCOL_OPTIONS',
    'CONFIG_UNSUPPORTED_VERSION', 'CONFIG_YAML_ALIASES_UNSUPPORTED', 'CREDENTIALS_INVALID_ENV_FILE',
    'CREDENTIALS_NOT_FOUND', 'EXTERNAL_MODEL_REQUIRED', 'INSTANCE_BUSY',
    'INVALID_ACTIVITY_CONFIRMATION', 'INVALID_API_KEY', 'INVALID_DELETE_FLAG',
    'INVALID_DESKTOP_ACTION', 'INVALID_DESKTOP_PREFERENCE', 'INVALID_MODEL_PREFERENCES',
    'INVALID_PROVIDER_SPEC', 'INVALID_RESPONSES_ADAPTATIONS', 'INVALID_ROUTING_MODE',
    'INVALID_SOURCE_MODE', 'MODEL_DISABLED', 'MODEL_DISABLED_AT_SOURCE',
    'MODEL_NAME_COLLIDES_WITH_OFFICIAL', 'MODEL_NOT_CONFIGURED', 'MODEL_SELECTION_REQUIRED',
    'MODEL_SOURCE_CHANGED', 'PROVIDER_NOT_FOUND', 'SESSION_BACKUP_TIMEOUT',
    'SESSION_BASELINE_UNAVAILABLE', 'SESSION_DATABASE_AMBIGUOUS', 'SESSION_DATABASE_UNSUPPORTED',
    'SESSION_HISTORY_INVALID', 'SESSION_ID_AMBIGUOUS', 'SESSION_INDEX_CODEX_UNAVAILABLE',
    'SESSION_INDEX_REPAIR_FAILED', 'SESSION_INDEX_REPAIR_INCOMPLETE', 'SESSION_MIGRATION_CHANGED',
    'SESSION_MIGRATION_CODEX_RUNNING', 'SESSION_MIGRATION_NOT_INTERRUPTED', 'SESSION_MIGRATION_PROCESS_CHECK_FAILED',
    'SESSION_MIGRATION_RECOVERY_REQUIRED', 'SESSION_MODEL_LIST_EMPTY', 'SESSION_PATH_UNSAFE',
    'SOURCE_NOT_SUPPORTED', 'UPSTREAM_OUTPUT_BUDGET_EXHAUSTED', 'UPSTREAM_STREAM_ENDED_EARLY',
    'UPSTREAM_STREAM_ERROR', 'YAML_DEPENDENCY_MISSING',
})
