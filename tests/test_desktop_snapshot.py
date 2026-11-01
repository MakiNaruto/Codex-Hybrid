import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_integration.snapshot import snapshot


class DesktopSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / '中文 config'
        self.directory.mkdir()

    def test_missing_settings_is_an_empty_state_without_creating_files(self):
        result = snapshot(self.directory)
        self.assertEqual(result['status'], 'not_configured')
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_catalog_is_read_only_and_credentials_are_never_returned(self):
        models = self.directory / 'models.yaml'
        models.write_text('''version: 1
providers:
  demo:
    protocol: openai_chat_completions
    base_url: https://example.invalid/v1
    credentials:
      api_key: secret-fixture-value
    models:
      test:
        model_id: test-model
        display_name: 中文模型
''', encoding='utf-8')
        settings = self.directory / 'settings.json'
        settings.write_text(json.dumps({'source': {'type': 'yaml', 'path': str(models)},
                                        'management_token': 'private-token'}), encoding='utf-8')
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        with patch('socket.socket', side_effect=AssertionError('No listener or request allowed')):
            result = snapshot(self.directory)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['models'][0]['display_name'], '中文模型')
        self.assertEqual(result['providers'], [{'id': 'demo', 'protocol': 'openai_chat_completions'}])
        self.assertNotIn('secret-fixture-value', json.dumps(result))
        self.assertNotIn('private-token', json.dumps(result))
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.iterdir()}, before)

    def test_invalid_input_does_not_leak_source_excerpt(self):
        (self.directory / 'settings.json').write_text('{secret-invalid', encoding='utf-8')
        result = snapshot(self.directory)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('secret-invalid', json.dumps(result))

    def test_settings_changed_during_read_does_not_get_a_fresh_revision(self):
        from codex_integration.snapshot import revision
        models = self.directory / 'models.yaml'
        models.write_text('version: 1\nproviders: {}\n', encoding='utf-8')
        settings = self.directory / 'settings.json'
        value = {'source': {'type': 'yaml', 'path': str(models)}}
        settings.write_text(json.dumps(value), encoding='utf-8')
        def change_before_revision(directory, settings_bytes=None):
            settings.write_text(json.dumps({**value, 'changed': True}), encoding='utf-8')
            return revision(directory, settings_bytes=settings_bytes)
        with patch('codex_integration.snapshot.revision', side_effect=change_before_revision):
            self.assertEqual(snapshot(self.directory)['status'], 'unavailable')

    def test_private_command_uses_fixed_home_and_returns_json(self):
        data = self.directory / '.codex-hybrid'
        data.mkdir()
        models = data / 'models.yaml'
        models.write_text('version: 1\nproviders: {}\n', encoding='utf-8')
        (data / 'settings.json').write_text(json.dumps({
            'source': {'type': 'yaml', 'path': str(models)}}), encoding='utf-8')
        root = Path(__file__).resolve().parents[1]
        executable = os.environ.get('STAGE0_SNAPSHOT_EXECUTABLE')
        command = [str(Path(executable).resolve())] if executable else [
            sys.executable, '-X', 'utf8', str(root / 'apps/desktop/stage0/probe.py')]
        environment = os.environ.copy()
        environment['HOME'] = str(self.directory)
        environment['PYTHONPATH'] = str(root / 'src')
        environment['CODEX_HYBRID_DATA_DIR'] = str(self.directory / 'ignored-cli-override')
        before = {p.name: p.read_bytes() for p in data.iterdir()}
        completed = subprocess.run([*command, 'desktop-snapshot'], cwd=self.directory,
                                   env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'], 'ready')
        self.assertEqual({p.name: p.read_bytes() for p in data.iterdir()}, before)
