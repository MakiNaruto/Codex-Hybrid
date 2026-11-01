import io
import json
from pathlib import Path
import tempfile
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from codex_integration.management import execute
from codex_integration.snapshot import snapshot


class DesktopManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'runtime'
        self.home = self.root / 'codex'
        self.home.mkdir()
        (self.home / 'config.toml').write_text('model = "official"\n')
        (self.home / 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'official'}]}))

    def call(self, request):
        return execute(request, directory=self.directory, codex_home=self.home)

    def initialize(self):
        self.assertTrue(self.call({'action': 'initialize'})['ok'])

    def provider(self):
        return {'action': 'save_provider', 'revision': snapshot(self.directory)['revision'],
                'id': 'demo', 'base_url': 'https://example.invalid/v1',
                'protocol': 'openai_chat_completions', 'enabled': True, 'timeout_seconds': 180,
                'api_key': 'secret-fixture', 'models': [{'alias': 'test', 'model_id': 'test',
                'display_name': '测试模型', 'enabled': True}]}

    def test_initialize_preserves_codex_and_does_not_bind(self):
        before = (self.home / 'config.toml').read_bytes()
        with patch('socket.socket', side_effect=AssertionError('No network')):
            self.initialize()
        self.assertEqual((self.home / 'config.toml').read_bytes(), before)
        self.assertEqual(snapshot(self.directory)['models'], [])
        self.assertTrue(json.loads((self.directory / 'settings.json').read_text())['management_auth_required'])
        saved = (self.directory / 'settings.json').read_bytes()
        self.assertFalse(self.call({'action': 'initialize'})['ok'])
        self.assertEqual((self.directory / 'settings.json').read_bytes(), saved)

    def test_save_key_retention_revision_and_no_auto_connection(self):
        self.initialize()
        request = self.provider()
        with patch('socket.socket', side_effect=AssertionError('No auto-test')):
            result = self.call(request)
        self.assertTrue(result['ok'], result)
        self.assertNotIn('secret-fixture', json.dumps(result))
        self.assertEqual(self.call(request)['error'], 'CONFIG_CHANGED')
        request['revision'] = snapshot(self.directory)['revision']
        request['api_key'] = ''
        request['models'][0]['display_name'] = '保留密钥'
        self.assertTrue(self.call(request)['ok'])
        import yaml
        raw = yaml.safe_load((self.directory / 'managed-models.yaml').read_text())
        self.assertEqual(raw['providers']['demo']['credentials']['api_key'], 'secret-fixture')
        self.assertEqual((self.home / 'config.toml').read_text(), 'model = "official"\n')

    def test_connection_only_on_explicit_request_and_omits_upstream_content(self):
        self.initialize()
        self.assertTrue(self.call(self.provider())['ok'])
        stream = {'choices': [{'index': 0, 'delta': {'content': 'do-not-return-upstream'}, 'finish_reason': 'stop'}]}
        response = io.BytesIO(('data: ' + json.dumps(stream) + '\n\ndata: [DONE]\n\n').encode())
        with patch('management.runtime.FreshProxyOpener') as opener:
            opener.return_value.open.return_value = response
            result = self.call({'action': 'test_connection', 'key': 'demo/test'})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['status'], 'completed')
        self.assertNotIn('do-not-return-upstream', json.dumps(result))
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.invalid/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer secret-fixture')
        with patch('management.runtime.FreshProxyOpener') as failing:
            failing.return_value.open.side_effect = ValueError('secret-fixture upstream private response')
            result = self.call({'action': 'test_connection', 'key': 'demo/test'})
        self.assertEqual(result, {'ok': False, 'error': 'OPERATION_FAILED'})

    def test_existing_service_blocks_a_separate_desktop_process(self):
        from codex_integration.locking import DirectoryLock
        self.initialize()
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        with DirectoryLock(self.directory, 'service.lock'):
            child = subprocess.run([sys.executable, '-c',
                'from codex_integration.management import execute; import json,sys; '
                'print(json.dumps(execute({"action":"initialize"},directory=sys.argv[1])))',
                str(self.directory)], env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(child.stdout)['error'], 'SERVICE_ALREADY_RUNNING')

    def test_preserves_advanced_fields_and_rejects_external_source_edits(self):
        import yaml
        self.initialize()
        self.assertTrue(self.call(self.provider())['ok'])
        source = self.directory / 'managed-models.yaml'
        raw = yaml.safe_load(source.read_text())
        raw['providers']['demo']['parameters'] = {'temperature': 0.2}
        raw['providers']['demo']['models']['test']['context_window'] = 131072
        stale = self.provider()
        source.write_text(yaml.safe_dump(raw), encoding='utf-8')
        self.assertEqual(self.call(stale)['error'], 'CONFIG_CHANGED')
        request = self.provider()
        self.assertTrue(self.call(request)['ok'])
        current = yaml.safe_load(source.read_text())['providers']['demo']
        self.assertEqual(current['parameters'], {'temperature': 0.2})
        self.assertEqual(current['models']['test']['context_window'], 131072)

    def test_cc_switch_rejects_saves_without_touching_source(self):
        self.initialize()
        request = self.provider()
        settings = self.directory / 'settings.json'
        value = json.loads(settings.read_text())
        value['source'] = {'type': 'cc-switch', 'path': str(self.root / 'unopened.db')}
        settings.write_text(json.dumps(value))
        self.assertEqual(self.call(request)['error'], 'CC_MODE_IS_READ_ONLY')
        self.assertFalse((self.root / 'unopened.db').exists())

    def test_unknown_action_and_errors_are_safe(self):
        result = self.call({'action': 'arbitrary_shell', 'secret': 'do-not-return'})
        self.assertFalse(result['ok'])
        self.assertNotIn('do-not-return', json.dumps(result))
        self.assertFalse(self.directory.exists())
