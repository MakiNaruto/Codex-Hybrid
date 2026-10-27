import ctypes
from ctypes import wintypes
import unittest
from unittest.mock import Mock, patch

from desktop import windows_restart_manager as manager


class RestartManagerTests(unittest.TestCase):
    def identity(self, pid=123, low=10):
        return manager.UniqueProcess(pid, wintypes.FILETIME(low, 0))

    def api(self):
        api = Mock()
        api.RmStartSession.return_value = 0
        api.RmRegisterResources.return_value = 0
        api.RmShutdown.return_value = 0
        return api

    def test_shutdown_registers_only_exact_processes_and_never_forces(self):
        api = self.api()
        with patch.object(manager, '_api', return_value=api), \
                patch.object(manager, '_identity', return_value=self.identity()), \
                patch.object(manager, '_scope_matches', return_value=True):
            self.assertTrue(manager.shutdown([Mock(pid=123)]))
        args = api.RmRegisterResources.call_args.args
        self.assertEqual((args[1], args[2], args[3], args[5], args[6]), (0, None, 1, 0, None))
        self.assertEqual(manager._key(args[4][0]), (123, 0, 10))
        self.assertEqual(api.RmShutdown.call_args.args[1:], (0, None))
        api.RmShutdown.assert_called_once()
        api.RmEndSession.assert_called_once()

    def test_refusal_never_retries_or_force_terminates(self):
        api = self.api()
        api.RmShutdown.return_value = 351
        with patch.object(manager, '_api', return_value=api), \
                patch.object(manager, '_identity', return_value=self.identity()), \
                patch.object(manager, '_scope_matches', return_value=True):
            result = manager.shutdown([Mock()])
        self.assertFalse(result)
        self.assertEqual(result.reason, 'restart_manager_shutdown_failed')
        api.RmShutdown.assert_called_once()
        self.assertEqual(api.RmShutdown.call_args.args[1], 0)
        api.RmEndSession.assert_called_once()

    def test_scope_or_registration_failure_does_not_send_shutdown(self):
        for register_error, scope_matches in ((0, False), (5, True)):
            api = self.api()
            api.RmRegisterResources.return_value = register_error
            with self.subTest(register_error=register_error), patch.object(manager, '_api', return_value=api), \
                    patch.object(manager, '_identity', return_value=self.identity()), \
                    patch.object(manager, '_scope_matches', return_value=scope_matches):
                self.assertFalse(manager.shutdown([Mock()]))
            api.RmShutdown.assert_not_called()
            api.RmEndSession.assert_called_once()

    def test_session_start_failure_does_not_use_or_end_invalid_session(self):
        api = self.api()
        api.RmStartSession.return_value = 5
        with patch.object(manager, '_api', return_value=api), \
                patch.object(manager, '_identity', return_value=self.identity()):
            self.assertFalse(manager.shutdown([Mock()]))
        api.RmRegisterResources.assert_not_called()
        api.RmShutdown.assert_not_called()
        api.RmEndSession.assert_not_called()

    def test_shutdown_exception_still_ends_session(self):
        api = self.api()
        api.RmShutdown.side_effect = OSError('fixture')
        with patch.object(manager, '_api', return_value=api), \
                patch.object(manager, '_identity', return_value=self.identity()), \
                patch.object(manager, '_scope_matches', return_value=True):
            with self.assertRaises(OSError):
                manager.shutdown([Mock()])
        api.RmEndSession.assert_called_once()

    def test_scope_rejects_pid_reuse_other_apps_and_services(self):
        for actual_pid, actual_low, app_type, expected in (
                (123, 10, 1, True), (123, 11, 1, False), (456, 10, 1, False), (123, 10, 3, False)):
            api = Mock()
            def get_list(session, needed, count, entries, reboot):
                needed._obj.value = 1
                if entries is None:
                    return 234
                entries[0].process = self.identity(actual_pid, actual_low)
                entries[0].application_type = app_type
                count._obj.value = 1
                return 0
            api.RmGetList.side_effect = get_list
            with self.subTest(pid=actual_pid, low=actual_low, app_type=app_type):
                self.assertEqual(manager._scope_matches(api, 1, [self.identity()]), expected)

    def test_kernel_identity_validation_closes_process_handle(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = 1234
        def image(handle, flags, path, length):
            path.value = 'C:/fixture/app.exe'
            return True
        def times(handle, started, exited, system, user):
            started._obj.dwLowDateTime = 10
            return True
        kernel.QueryFullProcessImageNameW.side_effect = image
        kernel.GetProcessTimes.side_effect = times
        process = Mock(pid=123)
        process.exe.return_value = 'C:/fixture/app.exe'
        process.is_running.return_value = True
        with patch.object(ctypes, 'WinDLL', return_value=kernel, create=True):
            self.assertEqual(manager._key(manager._identity(process)), (123, 0, 10))
        kernel.CloseHandle.assert_called_once_with(1234)
