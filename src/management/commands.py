"""Shared management business dispatch for authenticated HTTP and private IPC."""
from infrastructure.errors import ConfigError


WRITE_ACTIONS = frozenset({'routing/preview', 'routing', 'desktop/preferences',
                           'source', 'models', 'provider', 'publish', 'test'})


def read(manager, action, *, period=None, identifier=None):
    if action == 'state':
        return manager.view()
    if action == 'activity':
        return manager.activity_state()
    if action == 'processes':
        return manager.process_state()
    if action == 'usage':
        from management.usage import report
        return report(manager.directory, days=period, labels=manager.model_labels())
    if action == 'diagnostics':
        from management.diagnostics import report
        return report(manager, days=period, include_details=True)
    if action == 'diagnostic_error':
        from management.diagnostics import error_detail
        return error_detail(manager.directory, identifier)
    raise ConfigError('INVALID_REQUEST')


def write(manager, action, body):
    if action == 'routing/preview':
        return manager.preview_routing(body['mode'])
    if action == 'desktop/preferences':
        return manager.save_desktop_preferences(body.get('mode'), body.get('value'))
    if action == 'routing':
        return manager.set_routing(body['mode'], body.get('revision'),
                                   body.get('confirm_activity', False), body.get('desktop_action', False),
                                   body.get('desktop_was_running', False), body.get('desktop_ticket'))
    if action == 'source':
        return manager.set_source(body['mode'], body.get('cc_db_path'))
    if action == 'models':
        return manager.save_models(body.get('source_id'), body.get('updates'))
    if action == 'provider':
        return manager.save_provider(body['id'], body.get('spec'), body.get('api_key'), body.get('delete', False))
    if action == 'publish':
        return manager.publish()
    if action == 'test':
        return manager.test_connection(body['key'])
    raise ConfigError('INVALID_REQUEST')
