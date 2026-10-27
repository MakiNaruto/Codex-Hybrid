import unittest
from unittest.mock import Mock, patch
from pathlib import Path
from tempfile import TemporaryDirectory

import psutil

from desktop import windows_client as client


class WindowsClientTests(unittest.TestCase):
    def test_running_manifest_fallback_when_package_registration_is_unreadable(self):
        with TemporaryDirectory() as directory:
            package = Path(directory)/'WindowsApps'/'OpenAI.Codex_1.0_x64__fixture'
            executable = package/'app'/'ChatGPT.exe'
            executable.parent.mkdir(parents=True)
            executable.touch()
            (package/'AppxManifest.xml').write_text('''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
              <Identity Name="OpenAI.Codex"/><Applications><Application Id="App" Executable="app/ChatGPT.exe"/></Applications>
              </Package>''')
            process = Mock()
            process.info = {'name': 'ChatGPT.exe'}
            process.exe.return_value = str(executable)
            with patch.object(client.sys, 'platform', 'win32'), \
                    patch.object(client.subprocess, 'run', return_value=Mock(stdout='')), \
                    patch.object(client.psutil, 'process_iter', return_value=[process]):
                self.assertEqual(client.discover(Path.home()/'.codex'),
                                 {'executable': str(executable), 'app_id': 'OpenAI.Codex_fixture!App'})

    def test_custom_home_never_activates_default_desktop(self):
        with TemporaryDirectory() as directory, patch.object(client.subprocess, 'run') as run:
            self.assertIsNone(client.discover(Path(directory)))
            run.assert_not_called()

    def test_exact_install_identity_excludes_renderer_and_unrelated_apps(self):
        def process(path, args):
            item = Mock()
            item.info = {'name': 'ChatGPT.exe'}
            item.exe.return_value = path
            item.cmdline.return_value = args
            return item
        main = process('C:/fixture/ChatGPT.exe', ['ChatGPT.exe'])
        renderer = process('C:/fixture/ChatGPT.exe', ['ChatGPT.exe', '--type=renderer'])
        other = process('C:/other/ChatGPT.exe', ['ChatGPT.exe'])
        with patch.object(client.psutil, 'process_iter', return_value=[main, renderer, other]):
            self.assertEqual(client.processes({'executable': 'C:/fixture/ChatGPT.exe'}), [main])

    def test_denied_process_is_unknown_not_absent(self):
        process = Mock()
        process.info = {'name': 'ChatGPT.exe'}
        process.exe.side_effect = psutil.AccessDenied(1)
        with patch.object(client.psutil, 'process_iter', return_value=[process]):
            with self.assertRaises(psutil.AccessDenied):
                client.processes({'executable': 'C:/fixture/ChatGPT.exe'})

    def test_launch_only_activates_once_on_timeout(self):
        with patch.object(client, 'processes', return_value=[]), \
                patch.object(client.subprocess, 'Popen') as launch, \
                patch.object(client.time, 'monotonic', side_effect=[0, 21]):
            self.assertEqual(client.launch({'app_id': 'fixture!App'}), 'launch_unconfirmed')
            launch.assert_called_once()
            self.assertEqual(launch.call_args.args[0], ['explorer.exe', 'shell:AppsFolder\\fixture!App'])

    def test_background_process_does_not_skip_activation_or_report_success(self):
        process = Mock(pid=123)
        with patch.object(client, 'processes', return_value=[process]), \
                patch.object(client, '_windows', return_value=[]), \
                patch.object(client.subprocess, 'Popen') as launch, \
                patch.object(client.time, 'monotonic', side_effect=[0, 0, 21]), \
                patch.object(client.time, 'sleep'):
            self.assertEqual(client.launch({'app_id': 'fixture!App'}), 'launch_unconfirmed')
            launch.assert_called_once()

    def test_launch_requires_visible_window_after_activation(self):
        process = Mock(pid=123)
        with patch.object(client, 'processes', return_value=[process]), \
                patch.object(client, '_windows', return_value=[456]) as windows, \
                patch.object(client.subprocess, 'Popen') as launch, \
                patch.object(client.time, 'monotonic', side_effect=[0, 0]):
            self.assertEqual(client.launch({'app_id': 'fixture!App'}), 'started')
            windows.assert_called_once_with({123})
            launch.assert_called_once()

    def test_close_requests_application_quit_and_waits_for_process_exit(self):
        process = Mock(pid=123)
        with patch.object(client, 'processes', side_effect=[[process], []]), \
                patch.object(client, '_request_quit', return_value=True) as quit_app, \
                patch.object(client.psutil, 'wait_procs', return_value=([process], [])) as wait:
            self.assertTrue(client.close({}))
            quit_app.assert_called_once_with([process])
            wait.assert_called_once_with([process], timeout=12)

    def test_window_closing_without_process_exit_is_not_a_successful_quit(self):
        process = Mock(pid=123)
        with patch.object(client, 'processes', return_value=[process]), \
                patch.object(client, '_request_quit', return_value=True), \
                patch.object(client.psutil, 'wait_procs', return_value=([], [process])):
            result = client.close({})
            self.assertFalse(result)
            self.assertEqual(result.reason, 'exit_timeout')

    def test_failed_quit_request_does_not_close_windows_as_fallback(self):
        with patch.object(client, 'processes', return_value=[Mock(pid=123)]), \
                patch.object(client, '_request_quit', return_value=False), \
                patch.object(client.psutil, 'wait_procs') as wait:
            self.assertFalse(client.close({}))
            wait.assert_not_called()
