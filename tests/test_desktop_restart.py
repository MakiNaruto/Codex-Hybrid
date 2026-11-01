"""macOS-only restart intent; never controls a real application."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from codex_integration.restart import Restart
from codex_integration.client import CloseResult
from model_catalog.catalog import ConfigError


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.restart = Restart(Path('/fixture/.codex'))
        self.target = {'bundle': '/fixture/Codex.app'}
        self.process = SimpleNamespace(pid=17, create_time=lambda: 100.0)
        self.discover = patch('codex_integration.client.discover', return_value=self.target).start()
        self.processes = patch('codex_integration.client.processes', return_value=[self.process]).start()
        self.close = patch('codex_integration.client.close', return_value=CloseResult(True)).start()
        self.launch = patch('codex_integration.client.launch', return_value='started').start()
        self.addCleanup(patch.stopall)

    def test_preview_and_cancel_never_operate_application(self):
        preview = self.restart.preview({'active_requests': 2})
        self.assertTrue(preview['available'])
        self.assertEqual(preview['activity']['active_requests'], 2)
        self.close.assert_not_called()
        self.launch.assert_not_called()
        self.restart.cancel()
        with self.assertRaises(ConfigError):
            self.restart.confirm(preview['ticket'])
        self.close.assert_not_called()

    def test_confirmation_is_single_use_and_graceful(self):
        preview = self.restart.preview({})
        self.assertEqual(self.restart.confirm(preview['ticket']), {'desktop_result': 'started'})
        self.close.assert_called_once_with(self.target)
        self.launch.assert_called_once_with(self.target)
        with self.assertRaises(ConfigError):
            self.restart.confirm(preview['ticket'])
        self.close.assert_called_once()

    def test_changed_identity_expiry_and_wrong_ticket_cannot_close(self):
        for scenario in ('identity', 'expiry', 'ticket'):
            with self.subTest(scenario=scenario):
                self.processes.return_value = [self.process]
                with patch('codex_integration.restart.time.monotonic', return_value=10):
                    preview = self.restart.preview({})
                if scenario == 'identity':
                    self.processes.return_value = [SimpleNamespace(pid=17, create_time=lambda: 101.0)]
                with patch('codex_integration.restart.time.monotonic', return_value=200 if scenario == 'expiry' else 11):
                    with self.assertRaises(ConfigError):
                        self.restart.confirm('wrong' if scenario == 'ticket' else preview['ticket'])
        self.close.assert_not_called()
        self.launch.assert_not_called()

    def test_close_failure_never_launches_or_exposes_raw_reason(self):
        self.close.return_value = CloseResult(False, 'private error text')
        preview = self.restart.preview({})
        self.assertEqual(self.restart.confirm(preview['ticket']), {'desktop_result': 'close_failed'})
        self.launch.assert_not_called()

    def test_not_running_and_unknown_are_not_restartable(self):
        for result in ([], None):
            self.processes.side_effect = OSError('private') if result is None else None
            self.processes.return_value = result
            preview = self.restart.preview({})
            self.assertFalse(preview['available'])
            with self.assertRaises(ConfigError):
                self.restart.confirm(preview['ticket'])
        self.close.assert_not_called()
        self.launch.assert_not_called()

    def test_launch_exception_returns_only_a_fixed_outcome(self):
        self.launch.side_effect = OSError('fixture private data')
        preview = self.restart.preview({})
        self.assertEqual(self.restart.confirm(preview['ticket']), {'desktop_result': 'launch_unconfirmed'})
        self.launch.assert_called_once()

    def test_installation_change_invalidates_preview(self):
        preview = self.restart.preview({})
        self.discover.return_value = {'bundle': '/different/Codex.app'}
        with self.assertRaises(ConfigError):
            self.restart.confirm(preview['ticket'])
        self.close.assert_not_called()
