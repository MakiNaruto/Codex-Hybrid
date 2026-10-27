from pathlib import Path
import json
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

from desktop.process_state import codex_process_state
from management.service import Management


class ProcessStateTests(unittest.TestCase):
    def test_management_process_detection_uses_configured_home(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            home = root/'custom-codex'
            (root/'state.json').write_text(json.dumps({'config_path': str(home/'config.toml')}))
            manager = Management(SimpleNamespace(settings={}), root/'settings.json', None, None)
            with patch('desktop.process_state.codex_process_state', return_value={'status': 'not_detected'}) as scan:
                self.assertEqual(manager.process_state()['status'], 'not_detected')
                scan.assert_called_once_with(home)
            (root/'state.json').write_text('{}')
            self.assertEqual(manager.process_state()['status'], 'unknown')

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
                with patch('sys.platform', 'darwin'), patch('psutil.process_iter', return_value=[process]):
                    result = codex_process_state(Path.home()/'.codex')
                self.assertEqual(result['clients'][expected], 1)
                self.assertEqual(sum(result['clients'].values()), 1)

    def test_parent_desktop_identifies_shared_server(self):
        process = self.process('codex')
        process.info['cmdline'] = ['codex', 'app-server']
        process.parents = lambda: [SimpleNamespace(name=lambda: 'Codex', cmdline=lambda: ['/Applications/Codex.app/Contents/MacOS/Codex'])]
        with patch('sys.platform', 'darwin'), patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['clients']['desktop'], 1)

    def test_macos_embedded_cli_processes_belong_to_desktop(self):
        executable = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
        desktop = []
        for arguments in ([], ['app-server']):
            process = self.process('codex')
            process.exe = lambda: executable
            process.info['cmdline'] = ['codex', *arguments]
            desktop.append(process)
        vscode = self.process('codex')
        vscode.info['cmdline'] = ['/Users/test/.vscode/extensions/openai.chatgpt-26/bin/codex', 'app-server']
        with patch('sys.platform', 'darwin'), patch('psutil.process_iter', return_value=[*desktop, vscode]):
            result = codex_process_state(Path.home()/'.codex')
        self.assertEqual(result['clients'], {'desktop': 2, 'vscode': 1, 'cli': 0, 'unknown': 0})

    def test_macos_chatgpt_ancestry_identifies_shared_server(self):
        process = self.process('codex-app-server')
        process.info['cmdline'] = ['/usr/local/bin/codex-app-server', 'app-server']
        process.parents = lambda: [SimpleNamespace(name=lambda: 'ChatGPT', cmdline=lambda: [
            '/Applications/ChatGPT.app/Contents/MacOS/ChatGPT'])]
        with patch('sys.platform', 'darwin'), patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['clients']['desktop'], 1)

    def test_macos_desktop_executable_with_inaccessible_command_line(self):
        process = self.process('Codex')
        process.info.pop('cmdline')
        process.exe = lambda: '/Applications/Codex.app/Contents/MacOS/Codex'
        def denied():
            raise psutil.AccessDenied()
        process.cmdline = denied
        with patch('sys.platform', 'darwin'), patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['clients']['desktop'], 1)

    def test_macos_renderer_is_not_a_client_instance(self):
        process = self.process('Codex')
        process.info['cmdline'] = ['/Applications/Codex.app/Contents/MacOS/Codex', '--type=renderer']
        with patch('sys.platform', 'darwin'), patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['process_count'], 0)

    def test_windows_client_sources(self):
        cases = [
            (r'C:\Users\user\AppData\Local\OpenAI\Codex\bin\version\codex.exe', ['app-server'], 'desktop'),
            (r'C:\Program Files\WindowsApps\OpenAI.Codex_1_x64__id\app\Codex.exe', [], 'desktop'),
            (r'C:\Users\user\.vscode\extensions\openai.chatgpt-1\bin\codex.exe', ['app-server'], 'vscode'),
            (r'C:\Users\user\AppData\Roaming\npm\codex.exe', [], 'cli'),
            (r'C:\tools\codex.exe', ['app-server'], 'unknown'),
        ]
        for executable, arguments, expected in cases:
            with self.subTest(executable=executable):
                process = self.process('codex.exe')
                process.exe = lambda: executable
                process.info['cmdline'] = [executable, *arguments]
                with patch('sys.platform', 'win32'), patch('psutil.process_iter', return_value=[process]) as scan:
                    result = codex_process_state(Path.home()/'.codex')
                self.assertEqual(result['clients'][expected], 1)
                scan.assert_called_once_with(('pid', 'name', 'status'))

    def test_windows_parent_identifies_shared_server(self):
        process = self.process('codex.exe')
        process.info['cmdline'] = ['codex.exe', 'app-server']
        process.parents = lambda: [SimpleNamespace(name=lambda: 'Codex.exe', cmdline=lambda: [
            r'C:\Program Files\WindowsApps\OpenAI.Codex_1_x64__id\app\Codex.exe'])]
        with patch('sys.platform', 'win32'), patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['clients']['desktop'], 1)

    def test_windows_executable_identifies_desktop_without_command_line_access(self):
        process = self.process('codex.exe')
        process.info.pop('cmdline')
        process.exe = lambda: r'C:\Users\user\AppData\Local\OpenAI\Codex\bin\v1\codex.exe'
        def denied():
            raise psutil.AccessDenied()
        process.cmdline = denied
        with patch('sys.platform', 'win32'), patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['clients']['desktop'], 1)

    def test_windows_renderer_and_unrelated_inaccessible_process_are_ignored(self):
        renderer = self.process('codex.exe')
        renderer.info['cmdline'] = ['Codex.exe', '--type=renderer']
        inaccessible = self.process(None)
        def denied():
            self.fail('unrelated process details must not be read')
        inaccessible.cmdline = denied
        with patch('sys.platform', 'win32'), patch('psutil.process_iter', return_value=[renderer, inaccessible]):
            self.assertEqual(codex_process_state(Path.home()/'.codex')['status'], 'not_detected')

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
