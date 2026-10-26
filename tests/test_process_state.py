from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

from desktop.process_state import codex_process_state


class ProcessStateTests(unittest.TestCase):
    def test_client_sources_and_unidentified_app_server(self):
        cases = [
            (['/Applications/Codex.app/Contents/Resources/codex', 'app-server'], 'desktop'),
            (['/home/user/.vscode/extensions/openai.chatgpt-1/bin/codex', 'app-server'], 'vscode'),
            (['/usr/local/bin/codex'], 'cli'),
            (['/usr/local/bin/codex', 'app-server'], 'unknown'),
        ]
        for command, expected in cases:
            with self.subTest(expected=expected):
                process = self.process('codex')
                process.info['cmdline'] = command
                with patch('psutil.process_iter', return_value=[process]):
                    result = codex_process_state(Path.home()/'.codex')
                self.assertEqual(result['clients'][expected], 1)
                self.assertEqual(sum(result['clients'].values()), 1)

    def test_parent_desktop_identifies_shared_server(self):
        process = self.process('codex')
        process.info['cmdline'] = ['codex', 'app-server']
        process.parents = lambda: [SimpleNamespace(name=lambda: 'Codex', cmdline=lambda: ['/Applications/Codex.app/Contents/MacOS/Codex'])]
        with patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['clients']['desktop'], 1)

    def process(self, name, home=None, status='sleeping'):
        return SimpleNamespace(pid=-1, info={'name': name, 'status': status, 'cmdline': [name]},
                               environ=lambda: {'CODEX_HOME': str(home)} if home else {})

    def test_helpers_and_similarly_named_tools_are_not_codex_instances(self):
        processes = [self.process(name) for name in (
            'codex-helper', 'Codex Helper', 'codex-updater', 'codex-hybrid', 'codex-model-bridge')]
        with patch('psutil.process_iter', return_value=processes):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['status'], 'not_detected')

    def test_matching_instance_and_other_home_are_distinguished(self):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            with patch('psutil.process_iter', return_value=[self.process('codex', home)]):
                self.assertEqual(codex_process_state(home)['status'], 'running')
                self.assertEqual(codex_process_state(home/'other')['status'], 'not_detected')

    def test_denied_environment_is_unknown_instead_of_running(self):
        process = self.process('codex')
        def denied():
            raise psutil.AccessDenied()
        process.environ = denied
        with patch('psutil.process_iter', return_value=[process]):
            result = codex_process_state(Path.home()/'.codex')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['process_count'], 0)

    def test_dead_processes_are_ignored_and_scan_failure_is_unknown(self):
        with patch('psutil.process_iter', return_value=[self.process('codex', status='zombie')]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['status'], 'not_detected')
        with patch('psutil.process_iter', side_effect=psutil.AccessDenied()):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['status'], 'unknown')
