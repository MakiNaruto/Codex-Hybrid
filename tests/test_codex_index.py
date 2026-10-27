import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop.codex_index import find_codex, repair_index
from model_catalog.catalog import ConfigError


class CodexIndexTests(unittest.TestCase):
    def test_metadata_only_protocol_and_child_credential_isolation(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)/'codex 中文 space'
            home.mkdir()
            script = home/'fake_codex.py'
            observed = home/'requests.jsonl'
            script.write_text('''import json, os, sys
from pathlib import Path
for line in sys.stdin:
    message = json.loads(line)
    record = {'method': message['method'], 'params': message['params'],
              'home': os.environ['CODEX_HOME'], 'has_key': 'OPENAI_API_KEY' in os.environ,
              'proxy': os.environ['HTTPS_PROXY']}
    with Path(sys.argv[1]).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record) + '\\n')
    if 'id' in message:
        print(json.dumps({'id': message['id'], 'result': {}}), flush=True)
''', encoding='utf-8')
            real_popen = subprocess.Popen
            commands = []
            def launch(command, **options):
                commands.append(command)
                return real_popen([sys.executable, '-u', str(script), str(observed)], **options)
            with patch('desktop.codex_index.subprocess.Popen', side_effect=launch), \
                    patch.dict(os.environ, {'OPENAI_API_KEY': 'do-not-inherit'}):
                repair_index(home, ['thread-b', 'thread-a'], sys.executable)
            messages = [json.loads(line) for line in observed.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([m['method'] for m in messages],
                             ['initialize', 'initialized', 'thread/read', 'thread/read'])
            self.assertEqual([m['params']['threadId'] for m in messages[2:]], ['thread-a', 'thread-b'])
            self.assertTrue(all(m['params']['includeTurns'] is False for m in messages[2:]))
            self.assertTrue(all(not m['has_key'] and m['home'] == str(home) for m in messages))
            self.assertTrue(all(m['proxy'] == 'http://127.0.0.1:9' for m in messages))
            self.assertIn('cli_auth_credentials_store="ephemeral"', commands[0])
            self.assertNotIn('do-not-inherit', observed.read_text(encoding='utf-8'))

    def test_protocol_error_stops_repair_and_releases_child(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            script = home/'fake_codex.py'
            script.write_text('''import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if 'id' in message:
        print(json.dumps({'id': message['id'], 'error': {'code': -32601}}), flush=True)
''', encoding='utf-8')
            real_popen = subprocess.Popen
            processes = []
            def launch(command, **options):
                process = real_popen([sys.executable, '-u', str(script)], **options)
                processes.append(process)
                return process
            with patch('desktop.codex_index.subprocess.Popen', side_effect=launch):
                with self.assertRaisesRegex(ConfigError, 'SESSION_INDEX_REPAIR_FAILED'):
                    repair_index(home, ['thread'], sys.executable)
            self.assertIsNotNone(processes[0].poll())

    def test_invalid_executable_fails_without_launching_a_shell(self):
        with patch('desktop.codex_index.subprocess.Popen') as launch:
            with self.assertRaisesRegex(ConfigError, 'SESSION_INDEX_CODEX_UNAVAILABLE'):
                find_codex('missing-codex-executable --arbitrary-argument')
        launch.assert_not_called()

    def test_no_missing_indexes_do_not_start_codex(self):
        with patch('desktop.codex_index.subprocess.Popen') as launch:
            repair_index(Path.cwd(), [])
        launch.assert_not_called()
