import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop import service
from gateway.server import Gateway
from management.reload_state import status
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

    def switch(self, mode):
        preview = self.manager.preview_routing(mode)
        self.manager.set_routing(mode, preview['revision'])

    def test_empty_install_opens_management_without_switching_codex(self):
        view = self.manager.view()
        self.assertEqual(view['models'], [])
        self.assertIsNone(view['source_error'])
        self.assertEqual(view['routing_mode'], 'openai')
        self.assertFalse(view['reload']['required'])
        self.assertEqual((self.home/'config.toml').read_text(), 'model = "official"\n')

    def test_reload_confirmation_persists_and_rejects_stale_confirmation(self):
        self.switch('project')
        active = status(self.manager)
        self.assertTrue(active['required'])
        self.manager.acknowledge_reload(active['revision'])
        self.assertFalse(status(self.manager)['required'])
        self.switch('openai')
        self.assertTrue(status(self.manager)['required'])
        with self.assertRaises(ConfigError):
            self.manager.acknowledge_reload(active['revision'])
        settings_path = self.runtime/'settings.json'
        restarted = Gateway(json.loads(settings_path.read_text()), settings_path).manager
        self.assertTrue(status(restarted)['required'])

    def test_provider_save_and_key_update_have_distinct_reload_behavior(self):
        spec = {'base_url': 'https://example.invalid/v1', 'protocol': 'openai_chat_completions',
                'models': {'test': {'model_id': 'example'}}}
        self.manager.save_provider('example', spec, 'private-key')
        view = self.manager.view()
        self.assertEqual(view['credential_status'], {'example': 'available'})
        self.assertNotIn('private-key', json.dumps(view))
        self.assertTrue(view['reload']['required'])
        self.manager.acknowledge_reload(view['reload']['revision'])
        self.manager.save_provider('example', spec, 'replacement-key')
        self.assertFalse(self.manager.view()['reload']['required'])
        self.manager.save_provider('example', delete=True)
        self.assertEqual(self.manager.view()['models'], [])
        self.assertNotIn('deepseek_model', self.gateway.settings)

    def test_source_switch_retains_independent_data_and_does_not_write_cc_database(self):
        spec = {'base_url': 'https://example.invalid/v1', 'protocol': 'openai_chat_completions',
                'models': {'test': {'model_id': 'example'}}}
        self.manager.save_provider('example', spec, 'private-key')
        database = self.root/'cc.db'
        with sqlite3.connect(database) as db:
            db.execute('CREATE TABLE providers (id, app_type, name, settings_config, meta, sort_index, created_at)')
            raw = json.dumps({'auth': {'OPENAI_API_KEY': 'cc-test-key'}, 'config': {
                'model_provider': 'custom', 'model': 'cc-model', 'model_providers': {
                    'custom': {'base_url': 'https://example.invalid/v1', 'wire_api': 'responses'}}}})
            db.execute('INSERT INTO providers VALUES (?,?,?,?,?,0,0)', ('cc', 'codex', 'CC demo', raw, '{}'))
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
