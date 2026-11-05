"""Isolated tray lifecycle checks: no real Codex discovery, shutdown or launch."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))

from codex_integration.controller import Controller
from codex_integration.restart import Restart
from codex_integration import web_api
from model_catalog.catalog import ConfigError


class TrayLifecycleTests(unittest.TestCase):
    def test_windows_exits_with_routing_disabled_and_idle_retained_gateway(self):
        for mode in ('openai', 'external'):
            with self.subTest(mode=mode), patch('sys.platform', 'win32'):
                controller = self.controller()
                controller.manager.routing_state.return_value = mode
                controller.manager.process_state.return_value = {'status': 'running'}
                controller.runtime.snapshot.return_value = {'status': 'running'}
                controller.runtime.stop_if_safe.return_value = False
                self.assertEqual(controller.request({'action': 'shutdown'}),
                                 {'ok': True, 'result': {'stopped': True}})
                controller.runtime.close.assert_called_once_with()
                controller.runtime.stop_if_safe.assert_not_called()
                controller.manager.process_state.assert_not_called()

    def test_windows_exit_requires_confirmation_for_busy_or_uncertain_gateway(self):
        for mode, active in (('openai', 1), ('openai', None), ('unsupported', 0)):
            with self.subTest(mode=mode, active=active), patch('sys.platform', 'win32'):
                controller = self.controller()
                controller.manager.routing_state.return_value = mode
                controller.manager.activity_state.return_value = {'active_requests': active}
                controller.runtime.snapshot.return_value = {'status': 'running'}
                self.assertEqual(controller.request({'action': 'shutdown'})['error'], 'EXIT_BLOCKED')
                controller.runtime.close.assert_not_called()

    def test_macos_retained_gateway_still_requires_safe_stop(self):
        controller = self.controller()
        controller.runtime.snapshot.return_value = {'status': 'running'}
        controller.runtime.stop_if_safe.return_value = False
        with patch('sys.platform', 'darwin'):
            self.assertEqual(controller.request({'action': 'shutdown'})['error'], 'EXIT_BLOCKED')
        controller.runtime.stop_if_safe.assert_called_once_with(controller.manager)
        controller.runtime.close.assert_not_called()

    def test_windows_confirmed_exit_cleans_up_only_hybrid(self):
        controller = self.controller()
        controller.manager.routing_state.return_value = 'project'
        with patch('sys.platform', 'win32'):
            self.assertEqual(controller.request({'action': 'shutdown'})['error'], 'EXIT_BLOCKED')
            controller.runtime.close.assert_not_called()
            self.assertTrue(controller.request({'action': 'shutdown_confirmed'})['ok'])
        controller.runtime.close.assert_called_once_with()
        controller.manager.close.assert_called_once_with()
        self.assertTrue(controller.closed)

    def test_macos_cannot_bypass_safe_exit(self):
        controller = self.controller()
        with patch('sys.platform', 'darwin'):
            self.assertEqual(
                controller.request({'action': 'shutdown_confirmed'})['error'], 'INVALID_REQUEST')
        controller.runtime.close.assert_not_called()

    def controller(self):
        controller = Controller(directory='unused-fixture', codex_home='unused-codex')
        controller.ensure_manager = Mock(return_value=True)
        controller.manager = Mock()
        controller.manager.routing_state.return_value = 'openai'
        controller.manager.view.return_value = {}
        controller.manager.activity_state.return_value = {'active_requests': 0}
        controller.runtime = Mock()
        controller.runtime.snapshot.return_value = {'status': 'stopped'}
        return controller

    def test_both_desktop_platforms_offer_restart_through_existing_client(self):
        for platform in ('win32', 'darwin'):
            with self.subTest(platform=platform), patch('sys.platform', platform):
                controller = self.controller()
                controller.restart = Mock()
                controller.restart.preview.return_value = {'available': True, 'ticket': 'test'}
                self.assertTrue(controller.status()['restart_supported'])
                self.assertTrue(web_api.handle(controller, {
                    'path': 'state', 'method': 'GET', 'body': None})['restart_supported'])
                self.assertTrue(controller.handle({'action': 'preview_restart'})['available'])
                controller.handle({'action': 'cancel_restart'})
                controller.restart.cancel.assert_called_once()

    def test_unsupported_platform_rejects_restart(self):
        with patch('sys.platform', 'linux'):
            with self.assertRaises(ConfigError):
                self.controller().handle({'action': 'preview_restart'})

    def test_unhealthy_gateway_blocks_restart_on_both_platforms(self):
        for platform in ('win32', 'darwin'):
            with self.subTest(platform=platform), patch('sys.platform', platform):
                controller = self.controller()
                controller.manager.routing_state.return_value = 'project'
                controller.restart = Mock()
                with self.assertRaises(ConfigError) as error:
                    controller.handle({'action': 'preview_restart'})
                self.assertEqual(error.exception.code, 'FORWARDING_UNAVAILABLE')
                controller.restart.preview.assert_not_called()

    def test_restart_requires_same_identity_single_use_ticket_and_graceful_close(self):
        restart = Restart('unused-codex')
        process = Mock(pid=123)
        process.create_time.return_value = 42
        with patch('codex_integration.restart.client.discover', return_value={'fixture': True}), \
                patch('codex_integration.restart.client.processes', return_value=[process]), \
                patch('codex_integration.restart.client.close', return_value=False) as close, \
                patch('codex_integration.restart.client.launch') as launch:
            ticket = restart.preview({})['ticket']
            process.create_time.return_value = 43
            with self.assertRaises(ConfigError):
                restart.confirm(ticket)
            close.assert_not_called()
            ticket = restart.preview({})['ticket']
            self.assertEqual(restart.confirm(ticket)['desktop_result'], 'close_failed')
            launch.assert_not_called()
            with self.assertRaises(ConfigError):
                restart.confirm(ticket)

    def test_cancel_and_expiry_do_not_touch_client(self):
        restart = Restart('unused-codex')
        process = Mock(pid=123)
        process.create_time.return_value = 42
        with patch('codex_integration.restart.client.discover', return_value={'fixture': True}), \
                patch('codex_integration.restart.client.processes', return_value=[process]), \
                patch('codex_integration.restart.client.close') as close, \
                patch('codex_integration.restart.client.launch') as launch:
            ticket = restart.preview({})['ticket']
            restart.cancel()
            with self.assertRaises(ConfigError):
                restart.confirm(ticket)
            with patch('codex_integration.restart.time.monotonic', return_value=0):
                ticket = restart.preview({})['ticket']
            with patch('codex_integration.restart.time.monotonic', return_value=121):
                with self.assertRaises(ConfigError):
                    restart.confirm(ticket)
            close.assert_not_called()
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
