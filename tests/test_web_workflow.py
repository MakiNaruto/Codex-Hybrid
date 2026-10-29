import json
from contextlib import closing
import sqlite3
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop import service
from gateway.server import Gateway
from model_catalog.catalog import ConfigError


class WebWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'codex'
        self.home.mkdir()
        (self.home/'config.toml').write_text('model = "official"\n')
        (self.home/'models_cache.json').write_text(json.dumps({'models': [{'slug': 'official'}]}))
        self.runtime = self.root/'runtime'
        self.runtime.mkdir()
        models = self.runtime/'empty.yaml'
        models.write_text('version: 1\nproviders: {}\n')
        with patch.object(service, 'RUNTIME', self.runtime):
            service.prepare(18891, self.home, {'type': 'yaml', 'path': str(models)})
        settings_path = self.runtime/'settings.json'
        self.gateway = Gateway(json.loads(settings_path.read_text()), settings_path)
        self.manager = self.gateway.manager
        self.addCleanup(self.manager.close)

    def switch(self, mode):
        preview = self.manager.preview_routing(mode)
        self.manager.set_routing(mode, preview['revision'])

    def test_empty_install_opens_management_without_switching_codex(self):
        view = self.manager.view()
        self.assertEqual(view['models'], [])
        self.assertIsNone(view['source_error'])
        self.assertEqual(view['routing_mode'], 'openai')
        self.assertNotIn('reload', view)
        self.assertEqual(view['desktop_preferences'], {'project': 'ask', 'openai': 'ask'})
        self.assertEqual((self.home/'config.toml').read_text(), 'model = "official"\n')

    def test_desktop_preferences_persist_independently(self):
        self.manager.save_desktop_preferences('project', 'auto')
        self.manager.save_desktop_preferences('openai', 'never')
        settings_path = self.runtime/'settings.json'
        restarted = Gateway(json.loads(settings_path.read_text()), settings_path).manager
        self.assertEqual(restarted.desktop_preferences(), {'project': 'auto', 'openai': 'never'})
        with self.assertRaises(ConfigError):
            self.manager.save_desktop_preferences('project', 'invalid')

    def desktop_switch(self, mode, running=False, close=True, launch='started', failure=False):
        from desktop import client as desktop_client
        target = {'executable': 'fixture', 'app_id': 'fixture!App'}
        with patch.object(desktop_client, 'discover', return_value=target), \
                patch.object(desktop_client, 'processes', return_value=[object()] if running else []), \
                patch.object(desktop_client, 'close', return_value=close) as closer, \
                patch.object(desktop_client, 'launch', return_value=launch) as launcher:
            preview = self.manager.preview_routing(mode)
            args = (mode, preview['revision'], True, True, running, preview['desktop_ticket'])
            if failure:
                with patch.object(self.manager, '_apply_routing', side_effect=ConfigError('FIXTURE_FAILED')):
                    with self.assertRaises(ConfigError):
                        self.manager.set_routing(*args)
                launcher.assert_not_called()
                return
            result = self.manager.set_routing(*args)
            self.assertEqual(closer.call_count, int(running))
            self.assertEqual(launcher.call_count, int((running and close) or (not running and mode == 'project')))
            return result

    def test_enable_launches_once_and_disable_does_not_open_stopped_desktop(self):
        self.assertEqual(self.desktop_switch('project')['desktop_result'], 'started')
        self.assertEqual(self.desktop_switch('openai')['desktop_result'], 'not_running')

    def test_close_failure_still_applies_configuration_without_launch(self):
        result = self.desktop_switch('project', running=True, close=False)
        self.assertEqual(result['desktop_result'], 'close_failed')
        self.assertEqual(self.manager.routing_state(), 'project')

    def test_specific_close_failure_survives_api_and_logging_failure(self):
        from desktop.client import CloseResult
        with patch.object(self.gateway, 'record', side_effect=OSError('log unavailable')):
            result = self.desktop_switch('project', running=True,
                                         close=CloseResult(False, 'restart_manager_shutdown_failed'))
            self.manager.desktop_records.close(timeout=1)
            self.assertEqual(self.manager.desktop_records.dropped, 1)
        self.assertEqual(result['desktop_result'], 'close_failed')
        self.assertEqual(result['desktop_error'], 'restart_manager_shutdown_failed')
        self.assertEqual(self.manager.routing_state(), 'project')

    def test_config_failure_never_reopens_closed_desktop(self):
        self.desktop_switch('project', running=True, failure=True)
        self.assertIsNone(self.manager.view()['routing_operation'])
        self.assertEqual(self.desktop_switch('project')['desktop_result'], 'started')

    def test_blocked_desktop_result_logging_does_not_hold_switch_open(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        errors, results = [], []

        def blocked_record(value):
            entered.set()
            release.wait(5)

        def switch():
            try:
                results.append(self.desktop_switch('project'))
            except Exception as error:
                errors.append(error)
            finally:
                done.set()

        with patch.object(self.gateway, 'record', side_effect=blocked_record):
            thread = threading.Thread(target=switch)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(done.wait(.5), 'Logging held the completed switch open')
                self.assertEqual(self.manager.view()['routing_mode'], 'project')
                self.assertIsNone(self.manager.view()['routing_operation'])
                self.assertEqual(results[0]['desktop_result'], 'started')
                # The routing guard must already be available for another switch.
                self.switch('openai')
                self.assertEqual(self.manager.routing_state(), 'openai')
            finally:
                release.set()
                thread.join(3)
        self.assertFalse(errors, errors)

    def test_launch_timeout_preserves_applied_config(self):
        result = self.desktop_switch('project', launch='launch_unconfirmed')
        self.assertEqual(result['desktop_result'], 'launch_unconfirmed')
        self.assertEqual(self.manager.routing_state(), 'project')

    def test_disable_restarts_running_desktop_once(self):
        self.switch('project')
        self.assertEqual(self.desktop_switch('openai', running=True)['desktop_result'], 'started')
        self.assertEqual(self.manager.routing_state(), 'openai')

    def test_new_desktop_after_preview_is_not_closed(self):
        from desktop import client as desktop_client
        with patch.object(desktop_client, 'discover', return_value={'executable': 'fixture'}), \
                patch.object(desktop_client, 'processes', side_effect=[[], [object()]]), \
                patch.object(desktop_client, 'close') as closer, \
                patch.object(desktop_client, 'launch') as launcher:
            preview = self.manager.preview_routing('project')
            result = self.manager.set_routing('project', preview['revision'], True, True,
                                              False, preview['desktop_ticket'])
            self.assertEqual(result['desktop_result'], 'state_changed')
            closer.assert_not_called()
            launcher.assert_not_called()
            self.assertEqual(self.manager.routing_state(), 'project')

    def test_missing_install_still_applies_and_invalid_ticket_never_closes(self):
        from desktop import client as desktop_client
        with patch.object(desktop_client, 'discover', return_value=None), \
                patch.object(desktop_client, 'close') as closer:
            preview = self.manager.preview_routing('project')
            with self.assertRaises(ConfigError):
                self.manager.set_routing('project', preview['revision'], True, True, False, 'invalid')
            closer.assert_not_called()
            result = self.manager.set_routing('project', preview['revision'], True, True,
                                              False, preview['desktop_ticket'])
            self.assertEqual(result['desktop_result'], 'unavailable')
            self.assertEqual(self.manager.routing_state(), 'project')

    def test_unknown_process_state_does_not_control_desktop(self):
        from desktop import client as desktop_client
        with patch.object(desktop_client, 'discover', return_value={'executable': 'fixture'}), \
                patch.object(desktop_client, 'processes', side_effect=OSError('denied')), \
                patch.object(desktop_client, 'close') as closer, \
                patch.object(desktop_client, 'launch') as launcher:
            preview = self.manager.preview_routing('project')
            self.assertEqual(preview['desktop']['status'], 'unknown')
            result = self.manager.set_routing('project', preview['revision'], True, True,
                                              False, preview['desktop_ticket'])
            self.assertEqual(result['desktop_result'], 'unknown')
            closer.assert_not_called()
            launcher.assert_not_called()

    def test_external_config_edit_during_close_is_not_overwritten_or_reopened(self):
        from desktop import client as desktop_client
        def close(_):
            path = self.home/'config.toml'
            path.write_text(path.read_text() + '\n# external edit\n')
            return True
        with patch.object(desktop_client, 'discover', return_value={'executable': 'fixture'}), \
                patch.object(desktop_client, 'processes', return_value=[object()]), \
                patch.object(desktop_client, 'close', side_effect=close), \
                patch.object(desktop_client, 'launch') as launcher:
            preview = self.manager.preview_routing('project')
            with self.assertRaises(ConfigError):
                self.manager.set_routing('project', preview['revision'], True, True,
                                         True, preview['desktop_ticket'])
            launcher.assert_not_called()
            self.assertIn('# external edit', (self.home/'config.toml').read_text())
            self.assertEqual(self.manager.routing_state(), 'openai')

    def test_provider_save_and_key_update_do_not_track_reload(self):
        spec = {'base_url': 'https://example.invalid/v1', 'protocol': 'openai_chat_completions',
                'models': {'test': {'model_id': 'example'}}}
        self.manager.save_provider('example', spec, 'private-key')
        view = self.manager.view()
        self.assertEqual(view['credential_status'], {'example': 'available'})
        self.assertNotIn('private-key', json.dumps(view))
        self.assertNotIn('reload', view)
        self.manager.save_provider('example', spec, 'replacement-key')
        self.assertNotIn('reload', self.manager.view())
        self.manager.save_provider('example', delete=True)
        self.assertEqual(self.manager.view()['models'], [])
        self.assertNotIn('deepseek_model', self.gateway.settings)

    def test_source_switch_retains_independent_data_and_does_not_write_cc_database(self):
        spec = {'base_url': 'https://example.invalid/v1', 'protocol': 'openai_chat_completions',
                'models': {'test': {'model_id': 'example'}}}
        self.manager.save_provider('example', spec, 'private-key')
        database = self.root/'cc.db'
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE providers (id, app_type, name, settings_config, meta, sort_index, created_at)')
            raw = json.dumps({'auth': {'OPENAI_API_KEY': 'cc-test-key'}, 'config': {
                'model_provider': 'custom', 'model': 'cc-model', 'model_providers': {
                    'custom': {'base_url': 'https://example.invalid/v1', 'wire_api': 'responses'}}}})
            db.execute('INSERT INTO providers VALUES (?,?,?,?,?,0,0)', ('cc', 'codex', 'CC demo', raw, '{}'))
            db.commit()
        before = database.read_bytes()
        self.manager.set_source('cc_switch', str(database))
        self.assertEqual(self.manager.view()['mode'], 'cc_switch')
        self.assertEqual(database.read_bytes(), before)
        self.manager.set_source('independent')
        self.assertEqual(self.manager.view()['models'][0]['key'], 'example/test')
        self.assertEqual(self.manager.view()['credential_status']['example'], 'available')

    def test_setup_wizard_can_skip_credentials_and_paid_requests(self):
        from cli import setup_wizard
        runtime = self.root/'new-install'
        argv = ['setup', '--data-dir', str(runtime), '--codex-home', str(self.home)]
        with patch.object(sys, 'argv', argv), patch.object(service, 'RUNTIME', runtime), \
                patch.object(setup_wizard, 'ask', side_effect=['3', 'n']), \
                patch.object(setup_wizard.getpass, 'getpass') as secret, \
                patch.object(setup_wizard, 'run') as start, \
                patch.object(setup_wizard.webbrowser, 'open') as browser:
            setup_wizard.main()
        secret.assert_not_called();start.assert_not_called();browser.assert_not_called()
        settings = json.loads((runtime/'settings.json').read_text())
        manager = Gateway(settings, runtime/'settings.json').manager
        self.assertEqual(manager.view()['models'], [])
        self.assertEqual(manager.routing_state(), 'openai')
