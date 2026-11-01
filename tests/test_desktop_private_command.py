"""Same stdin-only private workflow against source or an explicitly supplied frozen binary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DesktopPrivateCommandTests(unittest.TestCase):
    def test_initialize_save_and_refresh_without_changing_codex(self):
        root = Path(__file__).resolve().parents[1]
        executable = os.environ.get('STAGE0_SNAPSHOT_EXECUTABLE')
        command = ([str(Path(executable).resolve())] if executable else
                   [sys.executable, '-X', 'utf8', str(root / 'desktop/stage0/probe.py')])
        with tempfile.TemporaryDirectory(prefix='desktop-control-') as temporary:
            home = Path(temporary)
            codex = home / '.codex'
            codex.mkdir()
            config = codex / 'config.toml'
            config.write_text('model = "official"\n')
            (codex / 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'official'}]}))
            environment = os.environ.copy()
            environment.update(HOME=str(home), PYTHONPATH=str(root / 'src'))
            def run(mode, request=None):
                completed = subprocess.run([*command, mode], input=json.dumps(request) + '\n',
                    cwd=home, env=environment, text=True, encoding='utf-8', capture_output=True, timeout=40)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertNotIn('fake-secret', completed.stdout + completed.stderr)
                return json.loads(completed.stdout)
            self.assertTrue(run('desktop-manage', {'action': 'initialize'})['ok'])
            view = run('desktop-snapshot')
            result = run('desktop-manage', {'action': 'save_provider', 'id': 'example',
                'revision': view['revision'], 'base_url': 'https://example.invalid/v1',
                'protocol': 'openai_chat_completions', 'timeout_seconds': 120, 'enabled': True,
                'api_key': 'fake-secret', 'models': [{'alias': 'demo', 'model_id': 'demo',
                'display_name': '桌面模型', 'enabled': True}]})
            self.assertTrue(result['ok'], result)
            view = run('desktop-snapshot')
            self.assertEqual(view['models'][0]['display_name'], '桌面模型')
            self.assertEqual(config.read_text(), 'model = "official"\n')
