"""Real local gateway lifecycle in a temporary HOME; never sends inference requests."""
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
import urllib.request


class ControllerProcessTests(unittest.TestCase):
    def test_private_session_owns_gateway_and_eof_reaps_it(self):
        root = Path(__file__).resolve().parents[1]
        binary = os.environ.get('STAGE0_SNAPSHOT_EXECUTABLE')
        command = [str(Path(binary).resolve())] if binary else [sys.executable, '-X', 'utf8', str(root / 'desktop/stage0/probe.py')]
        with tempfile.TemporaryDirectory(prefix='controller-session-') as temporary:
            home = Path(temporary)
            codex = home / '.codex'
            codex.mkdir()
            config = codex / 'config.toml'
            config.write_text('model = "official"\n')
            (codex / 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'official'}]}))
            environment = os.environ.copy()
            environment.update(HOME=str(home), PYTHONPATH=str(root / 'src'))
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            process = subprocess.Popen([*command, 'desktop-controller'], cwd=home, env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
            responses = queue.Queue()
            errors = []
            def read_stdout():
                for line in process.stdout:
                    responses.put(line)
                responses.put(None)
            def read_stderr():
                errors.extend(process.stderr.readlines())
            reader = threading.Thread(target=read_stdout, daemon=True)
            stderr = threading.Thread(target=read_stderr, daemon=True)
            reader.start(); stderr.start()
            def call(action, **values):
                process.stdin.write(json.dumps({'action': action, **values}) + '\n')
                process.stdin.flush()
                line = responses.get(timeout=45)
                self.assertIsNotNone(line, ''.join(errors))
                return json.loads(line)
            def switch(mode):
                preview = call('preview_routing', mode=mode)
                self.assertTrue(preview['ok'], preview)
                preview = preview['result']
                return call('set_routing', mode=mode, revision=preview['revision'], confirm_activity=True,
                    desktop_action=False, desktop_was_running=preview['desktop']['running'], desktop_ticket=preview['desktop_ticket'])
            try:
                self.assertFalse(call('status')['result']['configured'])
                self.assertEqual(call('web_api', method='GET', path='state', body=None)['result'], {'configured': False})
                self.assertFalse((home / '.codex-hybrid').exists())
                self.assertTrue(call('initialize')['ok'])
                if sys.platform == 'darwin':
                    # Read-only discovery plus cancellation exercises the frozen module;
                    # never confirm a valid ticket against the developer's real Codex.
                    preview = call('preview_restart')
                    self.assertTrue(preview['ok'], preview)
                    self.assertIsInstance(preview['result']['available'], bool)
                    self.assertTrue(call('cancel_restart')['ok'])
                    self.assertEqual(call('restart_codex', ticket=preview['result']['ticket'],
                        confirm_activity=True)['error'], 'INVALID_PREVIEW')
                    self.assertEqual(config.read_text(), 'model = "official"\n')
                view = call('web_api', method='GET', path='state', body=None)
                self.assertTrue(view['ok'], view)
                self.assertEqual(view['result']['routing_mode'], 'openai')
                self.assertNotIn('management_token', json.dumps(view))
                self.assertTrue(call('web_api', method='GET', path='diagnostics?days=1', body=None)['ok'])
                path = home / '.codex-hybrid/settings.json'
                settings = json.loads(path.read_text())
                settings['port'] = port
                path.write_text(json.dumps(settings))
                self.assertEqual(call('status')['result']['forwarding']['status'], 'stopped')
                self.assertEqual(config.read_text(), 'model = "official"\n')
                self.assertTrue(switch('project')['ok'])
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f'http://127.0.0.1:{port}/healthz', timeout=3) as response:
                    self.assertEqual(json.load(response)['service'], 'connected-native-gateway')
                self.assertEqual(call('shutdown')['error'], 'EXIT_BLOCKED')
                self.assertTrue(switch('openai')['ok'])
                self.assertEqual(tomllib.loads(config.read_text()), {'model': 'official'})
                # Exercise owner loss while the gateway is actually running again.
                self.assertTrue(switch('project')['ok'])
                process.stdin.close()
                self.assertEqual(process.wait(timeout=25), 0)
                self.assertEqual(tomllib.loads(config.read_text())['model_provider'], 'codex-hybrid')
                with self.assertRaises(OSError):
                    socket.create_connection(('127.0.0.1', port), timeout=1)
                # Next launch must request explicit recovery instead of starting automatically.
                completed = subprocess.run([*command, 'desktop-controller'], input='{"action":"status"}\n',
                    cwd=home, env=environment, text=True, capture_output=True, timeout=45)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                status = json.loads(completed.stdout)['result']
                self.assertTrue(status['recovery_required'])
                self.assertEqual(status['forwarding']['status'], 'stopped')
            finally:
                if process.poll() is None:
                    process.stdin.close()
                    try:
                        process.wait(timeout=25)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                reader.join(2); stderr.join(2)
                process.stdout.close(); process.stderr.close()
