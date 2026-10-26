from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import urllib.request
import urllib.error
from management.http import handle

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import tomllib
import unittest

from desktop.service import PROVIDER, candidate_config, digest
from management.service import Management
from model_catalog.catalog import ConfigError


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / 'config.toml'
        self.settings = {'catalog': str(self.directory / 'models.json'), 'port': 18891,
                         'local_token': 'test-token', 'disable_legacy_plugin': True}
        self.manager = Management(SimpleNamespace(settings=self.settings),
                                  self.directory / 'settings.json', None, None)
        self.initialize('model = "gpt-test"\r\n[features]\r\nexample = true\r\n')

    def initialize(self, native):
        candidate = candidate_config(native, self.settings)
        for name, text in [('config.toml', native), ('original-config.toml', native),
                           ('desktop-config.toml', candidate)]:
            (self.directory / name).write_bytes(text.encode())
        (self.directory / 'state.json').write_text(json.dumps({
            'config_path': str(self.path), 'original_sha256': digest(native.encode()),
            'candidate_sha256': digest(candidate.encode()), 'activated': False}))

    def switch(self, mode):
        preview = self.manager.preview_routing(mode)
        return self.manager.set_routing(mode, preview['revision'])

    def test_preview_and_cancel_do_not_write(self):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        self.manager.preview_routing('project')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})

    def test_round_trip_restores_absent_fields_and_retains_other_edits(self):
        native = tomllib.loads(self.path.read_text())
        self.switch('project')
        active = tomllib.loads(self.path.read_text())
        self.assertEqual(active['model_provider'], PROVIDER)
        self.path.write_text(self.path.read_text() + '\n[notice]\ntext = "用户修改"\n', encoding='utf-8')
        self.switch('openai')
        expected = dict(native, notice={'text': '用户修改'})
        self.assertEqual(tomllib.loads(self.path.read_text(encoding='utf-8')), expected)
        self.switch('project')
        self.switch('openai')
        self.assertEqual(tomllib.loads(self.path.read_text(encoding='utf-8')), expected)

    def test_original_catalog_restored(self):
        self.initialize('model_provider = "openai"\nmodel_catalog_json = "custom.json"\n')
        self.switch('project')
        self.switch('openai')
        self.assertEqual(tomllib.loads(self.path.read_text()), {
            'model_provider': 'openai', 'model_catalog_json': 'custom.json'})

    def test_stale_preview_rejected_without_writes(self):
        preview = self.manager.preview_routing('project')
        self.path.write_text(self.path.read_text() + '\n[notice]\nvalue = 1\n')
        before = self.path.read_bytes()
        with self.assertRaises(ConfigError):
            self.manager.set_routing('project', preview['revision'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_managed_conflict_rejected(self):
        self.switch('project')
        self.path.write_text(self.path.read_text().replace('test-token', 'external-token'))
        before = self.path.read_bytes()
        with self.assertRaises(ConfigError):
            self.manager.preview_routing('openai')
        self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_baseline_rejected(self):
        self.switch('project')
        (self.directory / 'original-config.toml').write_text('model_provider = "openai"\n')
        with self.assertRaises(ConfigError):
            self.manager.preview_routing('openai')

    def test_legacy_active_config_can_restore_crlf_snapshot(self):
        self.path.write_bytes((self.directory / 'desktop-config.toml').read_bytes())
        self.switch('openai')
        self.assertNotIn('model_provider', tomllib.loads(self.path.read_text()))

    def test_existing_inactive_bridge_table_is_restored(self):
        inactive = candidate_config('model = "gpt-test"\n', self.settings)
        inactive = inactive.replace('model_provider = "codex-hybrid"', 'model_provider = "openai"')
        inactive = inactive.replace('test-token', 'previous-token')
        self.initialize(inactive)
        before = tomllib.loads(inactive)
        self.switch('project')
        self.switch('openai')
        self.assertEqual(tomllib.loads(self.path.read_text()), before)

    def test_profiles_and_other_providers_rejected(self):
        for text in ['profile = "work"\n', 'model_provider = "vendor"\n']:
            self.path.write_text(text)
            with self.assertRaises(ConfigError):
                self.manager.preview_routing('project')


    def test_authenticated_preview_and_commit(self):
        gateway = self.manager.gateway
        gateway.manager = self.manager
        gateway.settings.update(management_auth_required=True, management_token='local-test-token')

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                handle(self, gateway, 'GET')

            def do_POST(self):
                handle(self, gateway, 'POST')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def post(endpoint, body, authenticated=True, origin=None):
            headers = {'Content-Type': 'application/json'}
            if authenticated:
                headers['Authorization'] = 'Bearer local-test-token'
            if origin:
                headers['Origin'] = origin
            request = urllib.request.Request(
                f'http://127.0.0.1:{server.server_port}/manage/api/{endpoint}',
                data=json.dumps(body).encode(), headers=headers)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=3) as response:
                return json.load(response)

        before = self.path.read_bytes()
        for authenticated in (False, True):
            headers = {'Authorization': 'Bearer local-test-token'} if authenticated else {}
            request = urllib.request.Request(
                f'http://127.0.0.1:{server.server_port}/manage/api/diagnostics', headers=headers)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            if authenticated:
                with opener.open(request, timeout=3) as response:
                    diagnostic = json.load(response)
                self.assertEqual(diagnostic['schema_version'], 1)
                self.assertNotIn('test-token', json.dumps(diagnostic))
            else:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    opener.open(request, timeout=3)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
        for options in [{'authenticated': False}, {'origin': 'https://example.com'}]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                post('routing/preview', {'mode': 'project'}, **options)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        preview = post('routing/preview', {'mode': 'project'})
        self.assertEqual(before, self.path.read_bytes())
        self.assertNotIn('test-token', json.dumps(preview))
        result = post('routing', {'mode': 'project', 'revision': preview['revision']})
        self.assertTrue(result['restart_client'])
        self.assertEqual(self.manager.routing_state(), 'project')


if __name__ == '__main__':
    unittest.main()
