"""Independent management listener, forwarding lifecycle and process ownership."""
import json
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from desktop import service
from desktop.locking import DirectoryLock
from gateway.server import Server, route, sse_events
from management.runtime import ManagementContext, ForwardingRuntime, handler, management_port
from management.service import Management
from model_catalog.catalog import ConfigError

SRC = str(Path(__file__).resolve().parents[1] / 'src')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.home = self.root/'codex'
        self.home.mkdir()
        (self.home/'config.toml').write_text('model="official"\n')
        (self.home/'models_cache.json').write_text('{"models":[{"slug":"official"}]}')
        self.directory = self.root/'runtime'
        self.directory.mkdir()
        source = self.directory/'models.yaml'
        source.write_text('version: 1\nproviders: {}\n')
        with patch.object(service, 'RUNTIME', self.directory):
            service.prepare(free_port(), self.home, {'type': 'yaml', 'path': str(source)})
        self.path = self.directory/'settings.json'
        settings = json.loads(self.path.read_text())
        settings.update(management_port=free_port(), management_token='private-test-token')
        self.path.write_text(json.dumps(settings))
        self.context = ManagementContext(settings)
        self.manager = self.context.manager = Management(self.context, self.path, route, sse_events)
        self.runtime = ForwardingRuntime(self.context)
        self.addCleanup(self.runtime.stop)
        self.server = Server(('127.0.0.1', settings['management_port']), handler(self.context))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        processes = patch('desktop.process_state._candidate_processes', return_value=[])
        processes.start()
        self.addCleanup(processes.stop)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, body=None, headers=None):
        request = urllib.request.Request(
            f'http://127.0.0.1:{management_port(self.context.settings)}'+path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', **(headers or {})})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=3)

    def switch(self, mode):
        preview = self.manager.preview_routing(mode)
        return self.manager.set_routing(mode, preview['revision'], confirm_activity=True)

    def test_management_edits_without_constructing_forwarder(self):
        with patch('gateway.server.Gateway', side_effect=AssertionError('must remain stopped')):
            with self.request('/manage/') as response:
                self.assertIn('模型管理', response.read().decode())
            with self.request('/manage/api/desktop/preferences', {'mode': 'project', 'value': 'never'}) as response:
                self.assertTrue(json.load(response)['saved'])
            self.assertEqual(self.runtime.snapshot()['status'], 'stopped')
            with self.assertRaises(OSError), socket.create_connection(('127.0.0.1', self.context.settings['port']), timeout=.2):
                pass

    def test_switch_starts_forwarding_and_safe_close_preserves_management(self):
        self.switch('project')
        self.assertEqual(self.runtime.snapshot()['status'], 'running')
        with urllib.request.urlopen(f'http://127.0.0.1:{self.context.settings["port"]}/healthz') as response:
            self.assertEqual(response.status, 200)
        result = self.switch('openai')
        self.assertFalse(result['forwarding_retained'])
        self.assertEqual(self.runtime.snapshot()['status'], 'stopped')
        with self.request('/manage/api/state') as response:
            self.assertEqual(json.load(response)['routing_mode'], 'openai')

    def test_close_retains_forwarding_for_running_or_unknown_clients(self):
        self.switch('project')
        with patch.object(self.manager, 'process_state', return_value={'status': 'unknown'}):
            result = self.switch('openai')
        self.assertTrue(result['forwarding_retained'])
        self.assertEqual(self.runtime.snapshot()['status'], 'running')

    def test_busy_forwarder_is_not_stopped(self):
        self.runtime.start()
        self.context.activity.begin()
        self.addCleanup(self.context.activity.end)
        self.assertFalse(self.runtime.stop_if_safe(self.manager))
        self.assertEqual(self.runtime.snapshot()['status'], 'running')

    def test_port_conflict_keeps_management_and_config_usable(self):
        original = (self.home/'config.toml').read_bytes()
        with socket.socket() as blocker:
            blocker.bind(('127.0.0.1', self.context.settings['port']))
            blocker.listen()
            with self.assertRaisesRegex(ConfigError, 'FORWARDING_START_FAILED'):
                self.switch('project')
            self.assertEqual((self.home/'config.toml').read_bytes(), original)
            with self.request('/manage/api/state') as response:
                self.assertEqual(json.load(response)['forwarding']['status'], 'fault')

    def test_management_cannot_forward_or_bypass_origin_checks(self):
        for path, body, headers, expected in [
            ('/responses', {}, {}, 404),
            ('/manage/api/forwarding/ensure', {}, {}, 403),
            ('/manage/api/desktop/preferences', {'mode': 'project', 'value': 'auto'}, {'Origin': 'https://external.example'}, 403),
            ('/manage/api/state', None, {'Host': 'attacker.example'}, 403),
        ]:
            with self.subTest(path=path, headers=headers), self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, body, headers)
            self.assertEqual(error.exception.code, expected)
            error.exception.close()

    def test_cli_readiness_can_start_stopped_forwarding(self):
        service.health(self.context.settings, ensure_forwarding=True)
        self.assertEqual(self.runtime.snapshot()['status'], 'running')

    def test_settings_snapshot_reloads_after_cooperating_cli_write(self):
        script = '''import json,sys
from pathlib import Path
from desktop.locking import DirectoryLock
p=Path(sys.argv[1])
with DirectoryLock(p.parent):
 s=json.loads(p.read_text());s['official_models']=['official','new'];p.write_text(json.dumps(s))
'''
        subprocess.run([sys.executable, '-c', script, str(self.path)],
                       env=dict(os.environ, PYTHONPATH=SRC), check=True, timeout=5)
        self.assertEqual(self.manager.view()['official_model_count'], 2)

    def test_saved_provider_and_connection_test_do_not_need_forwarding(self):
        spec = {'protocol': 'openai_chat_completions', 'base_url': 'https://provider.example/v1',
                'models': {'test': {'model_id': 'test-model'}}}
        self.manager.save_provider('demo', spec, api_key='test-only-key')
        response = io.BytesIO(b'not an actual network response')
        events = [{'type': 'response.completed'}]
        self.manager.route = lambda *args: ('https://provider.example/v1/chat/completions', {}, {}, lambda event: event)
        self.manager.sse_events = lambda stream: iter(events)
        with patch.object(self.context.opener, 'open', return_value=response):
            result = self.manager.test_connection('demo/test')
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.runtime.snapshot()['status'], 'stopped')

    def test_recovery_restarts_forwarding_without_rewriting_routing(self):
        self.switch('project')
        self.runtime.stop()
        before = (self.home/'config.toml').read_bytes()
        with self.request('/manage/api/runtime/recover', {}) as response:
            self.assertEqual(json.load(response)['status'], 'running')
        self.assertEqual((self.home/'config.toml').read_bytes(), before)

    def test_cli_write_is_rejected_before_touching_configuration(self):
        before = self.path.read_bytes()
        with DirectoryLock(self.directory):
            result = subprocess.run([sys.executable, '-m', 'cli', 'refresh-models',
                '--data-dir', str(self.directory)], env=dict(os.environ, PYTHONPATH=SRC),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.path.read_bytes(), before)

    def test_other_instance_cannot_migrate_the_same_codex_home(self):
        script = """import sys,time
from desktop.locking import DirectoryLock
with DirectoryLock(sys.argv[1],'.codex-hybrid.lock'):
 print('locked',flush=True);time.sleep(10)
"""
        process = subprocess.Popen([sys.executable, '-c', script, str(self.home)],
            env=dict(os.environ, PYTHONPATH=SRC), stdout=subprocess.PIPE)
        try:
            self.assertEqual(process.stdout.readline(), b'locked\n')
            before = (self.home/'config.toml').read_bytes()
            with self.assertRaisesRegex(ConfigError, 'INSTANCE_BUSY'):
                self.switch('project')
            self.assertEqual((self.home/'config.toml').read_bytes(), before)
        finally:
            process.kill()
            process.wait(5)
            process.stdout.close()

    def test_real_service_survives_without_forwarding_and_rejects_second_instance(self):
        settings = dict(self.context.settings, management_port=free_port(), port=free_port())
        self.path.write_text(json.dumps(settings))
        command = [sys.executable, '-m', 'gateway.server', '--settings', str(self.path)]
        process = subprocess.Popen(command, env=dict(os.environ, PYTHONPATH=SRC),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic()+5
            while True:
                try:
                    service.health(settings)
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic()>deadline:
                        self.fail('Management service did not start')
                    threading.Event().wait(.05)
            with self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', settings['port']), timeout=.2)
            before = self.path.read_bytes()
            other = self.directory/'other-settings.json'
            other.write_text(json.dumps(dict(settings, port=free_port(), management_port=free_port())))
            duplicate = subprocess.run([*command[:-1], str(other)], env=dict(os.environ, PYTHONPATH=SRC),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn(b'SERVICE_ALREADY_RUNNING', duplicate.stderr)
            self.assertEqual(self.path.read_bytes(), before)
            service.health(settings)
        finally:
            process.terminate()
            process.wait(5)


class LockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def test_operation_and_service_locks_exclude_other_processes(self):
        script = '''import sys
from desktop.locking import DirectoryLock
from model_catalog.catalog import ConfigError
try:
 with DirectoryLock(sys.argv[1],sys.argv[2]): pass
except ConfigError:
 sys.exit(7)
'''
        for name in ('operation.lock', 'service.lock'):
            with DirectoryLock(self.root, name):
                result = subprocess.run([sys.executable, '-c', script, str(self.root), name],
                    env=dict(os.environ, PYTHONPATH=SRC), timeout=5)
                self.assertEqual(result.returncode, 7)
        with DirectoryLock(self.root):
            with DirectoryLock(self.root):
                pass

    def test_process_death_releases_ownership_without_deleting_inode(self):
        script = '''import sys,time
from desktop.locking import DirectoryLock
with DirectoryLock(sys.argv[1],'service.lock'):
 print('locked',flush=True);time.sleep(10)
'''
        process = subprocess.Popen([sys.executable, '-c', script, str(self.root)],
            stdout=subprocess.PIPE, env=dict(os.environ, PYTHONPATH=SRC))
        try:
            self.assertEqual(process.stdout.readline(), b'locked\n')
            inode = (self.root/'service.lock').stat().st_ino
            process.kill()
            process.wait(5)
            with DirectoryLock(self.root, 'service.lock'):
                self.assertEqual((self.root/'service.lock').stat().st_ino, inode)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(5)
            process.stdout.close()
