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

    def test_quit_shortcut_is_one_ctrl_q_sequence(self):
        user32 = Mock()
        user32.GetForegroundWindow.return_value = 456
        user32.GetAsyncKeyState.return_value = 0
        user32.SendInput.return_value = 4
        self.assertTrue(client._send_quit_shortcut(user32, 456))
        user32.SendInput.assert_called_once()
        count, sequence, _ = user32.SendInput.call_args.args
        self.assertEqual(count, 4)
        self.assertEqual([(item.value.keyboard.key, item.value.keyboard.flags) for item in sequence],
                         [(0x11, 0), (0x51, 0), (0x51, 2), (0x11, 2)])

    def test_foreground_change_or_held_modifier_prevents_shortcut(self):
        user32 = Mock()
        user32.GetForegroundWindow.return_value = 999
        self.assertFalse(client._send_quit_shortcut(user32, 456))
        user32.SendInput.assert_not_called()
        user32.GetForegroundWindow.return_value = 456
        user32.GetAsyncKeyState.return_value = 0x8000
        self.assertFalse(client._send_quit_shortcut(user32, 456))
        user32.SendInput.assert_not_called()

    def test_partial_shortcut_only_releases_keys_without_retrying_quit(self):
        user32 = Mock()
        user32.GetForegroundWindow.return_value = 456
        user32.GetAsyncKeyState.return_value = 0
        user32.SendInput.side_effect = [2, 2]
        self.assertFalse(client._send_quit_shortcut(user32, 456))
        count, sequence, _ = user32.SendInput.call_args.args
        self.assertEqual(count, 2)
        self.assertEqual([(item.value.keyboard.key, item.value.keyboard.flags) for item in sequence],
                         [(0x51, 2), (0x11, 2)])

    def test_cannot_obtain_target_foreground_does_not_send_quit(self):
        user32 = Mock()
        user32.GetForegroundWindow.return_value = 999
        user32.IsIconic.return_value = False
        with patch.object(client, '_windows', return_value=[456]), \
                patch.object(client, '_user32', return_value=user32), \
                patch.object(client, '_send_quit_shortcut') as send, \
                patch.object(client, '_focus_window', return_value=False):
            result = client._request_quit([Mock(pid=123)])
            self.assertFalse(result)
            self.assertEqual(result.reason, 'foreground_denied')
            send.assert_not_called()

    def test_background_thread_temporarily_attaches_and_always_detaches(self):
        user32 = Mock()
        user32.GetForegroundWindow.side_effect = [999, 999, 999, 456]
        user32.GetWindowThreadProcessId.return_value = 22
        user32.AttachThreadInput.return_value = True
        with patch.object(client, '_current_thread_id', return_value=11):
            self.assertTrue(client._focus_window(user32, 456))
        self.assertEqual([call.args for call in user32.AttachThreadInput.call_args_list],
                         [(11, 22, True), (11, 22, False)])

    def test_failed_focus_detaches_before_returning(self):
        user32 = Mock()
        user32.GetForegroundWindow.return_value = 999
        user32.GetWindowThreadProcessId.return_value = 22
        user32.AttachThreadInput.return_value = True
        with patch.object(client, '_current_thread_id', return_value=11), \
                patch.object(client.time, 'monotonic', side_effect=[0, 2]):
            self.assertFalse(client._focus_window(user32, 456))
        self.assertEqual([call.args for call in user32.AttachThreadInput.call_args_list],
                         [(11, 22, True), (11, 22, False)])

    def test_disallowed_input_attachment_does_not_send_shortcut(self):
        user32 = Mock()
        user32.GetForegroundWindow.return_value = 999
        user32.GetWindowThreadProcessId.return_value = 22
        user32.AttachThreadInput.return_value = False
        with patch.object(client, '_current_thread_id', return_value=11):
            self.assertFalse(client._focus_window(user32, 456))
        user32.AttachThreadInput.assert_called_once_with(11, 22, True)
