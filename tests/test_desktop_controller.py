import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from desktop.controller import Controller
from model_catalog.catalog import ConfigError


class Runtime:
    def __init__(self, context):
        self.context = context
        context.runtime = self
        self.running = False
        self.safe = True
        self.started = 0

    def snapshot(self):
        return {'status': 'running' if self.running else 'stopped', 'error': None}

    def start(self):
        self.started += 1
        self.running = True

    def stop_if_safe(self, manager):
        if self.safe:
            self.running = False
        return self.safe

    def close(self):
        self.running = False


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'codex'
        self.home.mkdir()
        self.config = self.home / 'config.toml'
        self.config.write_text('model = "official"\n')
        (self.home / 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'official'}]}))
        self.directory = self.root / 'runtime'
        self.controller = Controller(directory=self.directory, codex_home=self.home, runtime_factory=Runtime)
        self.addCleanup(self.controller.close)
        self.process = patch('management.service.Management.process_state', return_value={
            'status': 'not_detected', 'process_count': 0, 'clients': {}, 'observed_at': None})
        self.process.start()
        self.addCleanup(self.process.stop)
        self.discover = patch('desktop.client.discover', return_value=None)
        self.discover.start()
        self.addCleanup(self.discover.stop)

    def call(self, action, **kwargs):
        return self.controller.request({'action': action, **kwargs})

    def initialize(self):
        result = self.call('initialize')
        self.assertTrue(result['ok'], result)

    def commit(self, mode):
        preview = self.call('preview_routing', mode=mode)['result']
        return self.call('set_routing', mode=mode, revision=preview['revision'],
                         confirm_activity=True, desktop_action=False,
                         desktop_was_running=preview['desktop']['running'], desktop_ticket=preview['desktop_ticket'])

    def test_startup_and_preview_do_not_enable_or_modify_codex(self):
        self.assertFalse(self.call('status')['result']['configured'])
        self.assertFalse(self.directory.exists())
        self.initialize()
        self.assertEqual(self.call('status')['result']['forwarding']['status'], 'stopped')
        self.assertTrue(self.call('preview_routing', mode='project')['ok'])
        self.assertEqual(self.config.read_text(), 'model = "official"\n')
        self.assertEqual(self.controller.runtime.started, 0)
        self.assertTrue(self.call('cancel_preview')['ok'])
        self.assertFalse(self.call('set_routing', mode='project', revision='not-previewed',
            confirm_activity=True, desktop_action=False, desktop_was_running=False, desktop_ticket='x')['ok'])

    def test_confirmed_switch_and_safe_exit_use_shared_transactions(self):
        self.initialize()
        self.assertTrue(self.commit('project')['ok'])
        self.assertIn('model_provider = "codex-hybrid"', self.config.read_text())
        self.assertTrue(self.controller.runtime.running)
        self.assertEqual(self.call('shutdown')['error'], 'EXIT_BLOCKED')
        self.assertTrue(self.commit('openai')['ok'])
        self.assertEqual(tomllib.loads(self.config.read_text()), {'model': 'official'})
        self.assertFalse(self.controller.runtime.running)
        self.assertTrue(self.call('shutdown')['ok'])

    def test_failed_gateway_start_never_changes_codex(self):
        self.initialize()
        with patch.object(self.controller.runtime, 'start', side_effect=ConfigError('FORWARDING_START_FAILED')):
            result = self.commit('project')
        self.assertFalse(result['ok'])
        self.assertEqual(self.config.read_text(), 'model = "official"\n')

    def test_stale_preview_is_rejected(self):
        self.initialize()
        preview = self.call('preview_routing', mode='project')['result']
        self.config.write_text('model = "official"\n# external edit\n')
        result = self.call('set_routing', mode='project', revision=preview['revision'],
            confirm_activity=True, desktop_action=False, desktop_was_running=False, desktop_ticket=preview['desktop_ticket'])
        self.assertFalse(result['ok'])
        self.assertIn('# external edit', self.config.read_text())
        self.assertEqual(self.controller.runtime.started, 0)

    def test_retained_forwarder_blocks_exit(self):
        self.initialize()
        self.assertTrue(self.commit('project')['ok'])
        self.controller.runtime.safe = False
        result = self.commit('openai')
        self.assertTrue(result['ok'])
        self.assertTrue(result['result']['forwarding_retained'])
        self.assertEqual(self.call('shutdown')['error'], 'EXIT_BLOCKED')
        self.controller.runtime.safe = True
        self.assertTrue(self.call('shutdown')['ok'])

    def test_restart_requires_explicit_recovery(self):
        self.initialize()
        self.assertTrue(self.commit('project')['ok'])
        self.controller.close()
        restarted = Controller(directory=self.directory, codex_home=self.home, runtime_factory=Runtime)
        self.addCleanup(restarted.close)
        status = restarted.request({'action': 'status'})['result']
        self.assertTrue(status['recovery_required'])
        self.assertEqual(restarted.runtime.started, 0)
        self.assertTrue(restarted.request({'action': 'recover_forwarding'})['ok'])
        self.assertEqual(restarted.runtime.started, 1)

    def test_invalid_requests_do_not_create_state(self):
        for request in ({'action': 'set_routing', 'mode': 'project', 'revision': [],
                'confirm_activity': True, 'desktop_action': False, 'desktop_was_running': False, 'desktop_ticket': ''},
                {'action': 'recover_forwarding', 'path': '/untrusted'}, {'action': 'status', 'extra': True}):
            self.assertEqual(self.controller.request(request)['error'], 'INVALID_REQUEST')
        self.assertFalse(self.directory.exists())

    def test_preferences_do_not_auto_operate_codex_or_invalidate_preview(self):
        self.initialize()
        self.assertTrue(self.call('preview_routing', mode='project')['ok'])
        self.assertTrue(self.call('save_desktop_preferences', mode='project', value='auto')['ok'])
        self.assertEqual(self.call('status')['result']['desktop_preferences']['project'], 'auto')
        self.assertEqual(self.config.read_text(), 'model = "official"\n')
        self.assertEqual(self.controller.runtime.started, 0)

    def test_window_can_exit_after_another_instance_rejects_ownership(self):
        self.initialize()
        self.controller.close()
        other = Controller(directory=self.directory, codex_home=self.home, runtime_factory=Runtime)
        self.addCleanup(other.close)
        with patch.object(other, 'own', side_effect=ConfigError('SERVICE_ALREADY_RUNNING')):
            self.assertEqual(other.request({'action': 'status'})['error'], 'SERVICE_ALREADY_RUNNING')
            self.assertTrue(other.request({'action': 'shutdown'})['ok'])

    def test_restart_commands_are_macos_only_and_require_explicit_confirmation(self):
        self.initialize()
        with patch('desktop.controller.sys.platform', 'win32'):
            self.assertEqual(self.call('preview_restart')['error'], 'INVALID_REQUEST')
        with patch('desktop.controller.sys.platform', 'darwin'), \
                patch.object(self.controller.restart, 'preview', return_value={'ticket': 'fixture'}) as preview, \
                patch.object(self.controller.restart, 'confirm') as confirm:
            self.assertTrue(self.call('preview_restart')['ok'])
            preview.assert_called_once()
            self.assertEqual(self.call('restart_codex', ticket='fixture', confirm_activity=False)['error'], 'INVALID_REQUEST')
            confirm.assert_not_called()
            self.assertEqual(self.call('restart_codex', ticket=[], confirm_activity=True)['error'], 'INVALID_REQUEST')
        self.assertEqual(self.config.read_text(), 'model = "official"\n')

    def test_restart_refuses_client_relaunch_into_failed_forwarding(self):
        self.initialize()
        self.assertTrue(self.commit('project')['ok'])
        self.controller.runtime.running = False
        with patch('desktop.controller.sys.platform', 'darwin'), \
                patch.object(self.controller.restart, 'confirm') as confirm:
            self.assertEqual(self.call('restart_codex', ticket='fixture', confirm_activity=True)['error'], 'FORWARDING_UNAVAILABLE')
            confirm.assert_not_called()

    def test_routing_and_restart_previews_are_mutually_exclusive(self):
        from types import SimpleNamespace
        self.initialize()
        process = SimpleNamespace(pid=7, create_time=lambda: 42.0)
        with patch('desktop.controller.sys.platform', 'darwin'), \
                patch('desktop.client.discover', return_value={'bundle': '/fixture/Codex.app'}), \
                patch('desktop.client.processes', return_value=[process]), \
                patch('desktop.client.close') as close:
            restart = self.call('preview_restart')['result']
            self.assertTrue(self.call('preview_routing', mode='project')['ok'])
            self.assertEqual(self.call('restart_codex', ticket=restart['ticket'], confirm_activity=True)['error'], 'INVALID_PREVIEW')
            self.assertTrue(self.call('preview_restart')['ok'])
            self.assertIsNone(self.controller.pending)
            close.assert_not_called()

    def test_unsupported_restart_never_initializes_or_claims_a_directory(self):
        with patch('desktop.controller.sys.platform', 'win32'):
            self.assertEqual(self.call('preview_restart')['error'], 'INVALID_REQUEST')
            self.assertEqual(self.call('cancel_restart')['error'], 'INVALID_REQUEST')
        self.assertFalse(self.directory.exists())

    def web(self, path, body=None):
        return self.call('web_api', path=path, method='GET' if body is None else 'POST', body=body)

    def test_shared_web_startup_requires_explicit_initialization(self):
        self.assertEqual(self.web('state'), {'ok': True, 'result': {'configured': False}})
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.web('provider', {'id': 'demo'})['error'], 'NOT_CONFIGURED')
        self.assertFalse(self.directory.exists())

    def test_shared_web_provider_models_and_diagnostics_use_management(self):
        self.initialize()
        spec = {'base_url': 'https://example.invalid/v1', 'protocol': 'openai_chat_completions',
                'enabled': True, 'timeout_seconds': 120,
                'models': {'demo': {'model_id': 'demo', 'display_name': 'Demo', 'enabled': True}}}
        saved = self.web('provider', {'id': 'fixture', 'spec': spec, 'api_key': 'fixture-secret'})
        self.assertTrue(saved['ok'], saved)
        view = self.web('state')['result']
        self.assertNotIn('fixture-secret', json.dumps(view))
        self.assertEqual(view['models'][0]['key'], 'fixture/demo')
        self.assertTrue(self.web('models', {'source_id': view['source_id'],
            'updates': [{'key': 'fixture/demo', 'added': False}]})['ok'])
        self.assertFalse(self.web('state')['result']['models'][0]['enabled'])
        self.assertTrue(self.web('publish', {})['ok'])
        self.assertTrue(self.web('processes')['ok'])
        self.assertTrue(self.web('activity')['ok'])
        report = self.web('diagnostics?days=7')
        self.assertTrue(report['ok'], report)
        self.assertEqual(report['result']['period_days'], 7)
        self.assertEqual(self.config.read_text(), 'model = "official"\n')
        self.assertEqual(self.controller.runtime.started, 0)

    def test_shared_web_routing_requires_matching_preview(self):
        self.initialize()
        preview = self.web('routing/preview', {'mode': 'project'})['result']
        self.assertIn('warnings', preview)
        result = self.web('routing', {'mode': 'project', 'revision': preview['revision'],
            'confirm_activity': True, 'desktop_action': False, 'desktop_was_running': False,
            'desktop_ticket': preview['desktop_ticket']})
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.web('routing', {'mode': 'project', 'revision': preview['revision'],
            'confirm_activity': True, 'desktop_action': False, 'desktop_was_running': False,
            'desktop_ticket': preview['desktop_ticket']})['error'], 'INVALID_PREVIEW')

    def test_shared_web_rejects_unlisted_requests_before_claiming_ownership(self):
        for path, method, body in [('forwarding/ensure', 'POST', {}), ('../state', 'GET', None),
                ('shutdown', 'POST', {}), ('state', 'POST', {}), ('provider', 'GET', None),
                ('provider', 'POST', {'id': 'demo', 'arbitrary': True}),
                ('diagnostics?days=7&days=1', 'GET', None), ('diagnostics?days=2', 'GET', None)]:
            result = self.call('web_api', path=path, method=method, body=body)
            self.assertEqual(result['error'], 'INVALID_REQUEST', (path, result))
        self.assertFalse(self.directory.exists())

    def test_shared_web_connection_errors_are_safe_and_match_browser_codes(self):
        import urllib.error
        self.initialize()
        error = urllib.error.HTTPError('https://example.invalid/fixture-secret', 401,
            'fixture-secret', {}, None)
        self.addCleanup(error.close)
        with patch.object(self.controller.manager, 'test_connection', side_effect=error):
            result = self.web('test', {'key': 'fixture/demo'})
        self.assertEqual(result, {'ok': False, 'error': 'UPSTREAM_HTTP_401'})


class DesktopCCStartupTests(unittest.TestCase):
    def test_saved_cc_source_is_populated_on_first_state_and_keeps_syncing(self):
        import test_cc_model_identity as identity
        fixture = identity.CCModelIdentityTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        settings = dict(fixture.settings, max_concurrent_requests=2,
                        official_catalog=[{'slug': 'official'}])
        (fixture.root / 'settings.json').write_text(json.dumps(settings))
        controller = Controller(directory=fixture.root, codex_home=fixture.root / 'codex',
                                runtime_factory=Runtime)
        self.addCleanup(controller.close)
        request = {'action': 'web_api', 'path': 'state', 'method': 'GET', 'body': None}
        result = controller.request(request)
        self.assertTrue(result['ok'], result)
        self.assertEqual({model['key'] for model in result['result']['models']},
                         {'record-a/model-a', 'record-a/model-b'})
        manager = controller.manager
        self.assertTrue(manager.sync_thread.is_alive())
        self.assertEqual(controller.runtime.started, 0)
        # Already-booted reads must not restart synchronization or republish.
        with patch.object(manager, 'start_sync', side_effect=AssertionError('restarted sync')):
            self.assertTrue(controller.request(request)['ok'])
        controller.close()
        self.assertFalse(manager.sync_thread.is_alive())
