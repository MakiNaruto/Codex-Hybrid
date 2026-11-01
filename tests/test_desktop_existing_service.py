import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from codex_integration.controller import Controller
from model_catalog.catalog import ConfigError


class ExistingServiceTests(unittest.TestCase):
    def test_mac_reuses_existing_owner_and_quit_does_not_stop_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'settings.json').write_text('{}')
            controller = Controller(directory=directory)
            with patch('codex_integration.controller.sys.platform', 'darwin'), \
                    patch.object(controller, 'own', side_effect=ConfigError('SERVICE_ALREADY_RUNNING')), \
                    patch('codex_integration.existing_service.ExistingService') as adapter:
                adapter.return_value.api.return_value = {'models': ['fixture'], 'routing_mode': 'openai',
                                                         'forwarding': {'status': 'running'}}
                result = controller.request({'action': 'web_api', 'method': 'GET', 'path': 'state', 'body': None})
                self.assertTrue(result['ok'])
                self.assertEqual(result['result']['models'], ['fixture'])
                self.assertTrue(result['result']['external_service'])
                self.assertTrue(result['result']['restart_supported'])
                adapter.return_value.api.reset_mock()
                self.assertTrue(controller.request({'action': 'shutdown'})['ok'])
                adapter.return_value.api.assert_not_called()

    def test_windows_keeps_existing_single_owner_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'settings.json').write_text('{}')
            controller = Controller(directory=directory)
            with patch('codex_integration.controller.sys.platform', 'win32'), \
                    patch.object(controller, 'own', side_effect=ConfigError('SERVICE_ALREADY_RUNNING')):
                self.assertEqual(controller.request({'action': 'status'})['error'], 'SERVICE_ALREADY_RUNNING')

    def test_adapter_keeps_token_off_frontend_and_never_uses_system_proxy(self):
        from codex_integration.existing_service import ExistingService
        with patch.object(ExistingService, '_verify_owner'):
            service = ExistingService({'port': 18891, 'management_token': 'fixture-token'}, '/fixture')
        import io
        with patch.object(service, '_verify_owner'), \
                patch.object(service.opener, 'open', return_value=io.BytesIO(json.dumps({'models': []}).encode())) as send:
            self.assertEqual(service.api('state'), {'models': []})
            request = send.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:18892/manage/api/state')
            self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-token')
            self.assertFalse(any(type(handler).__name__ == 'ProxyHandler' for handler in service.opener.handlers))

    def test_unrelated_service_is_never_contacted(self):
        from codex_integration.existing_service import ExistingService
        with tempfile.TemporaryDirectory() as tmp, patch('codex_integration.existing_service.build_opener') as opener:
            with self.assertRaises(ConfigError):
                ExistingService({'port': 18891}, tmp)
            opener.assert_not_called()

    def test_mac_external_service_restart_uses_live_state_and_single_use_ticket(self):
        controller = Controller(directory='/fixture')
        controller.existing_service = Mock()
        state = {'routing_mode': 'project', 'forwarding': {'status': 'running'}}
        controller.existing_service.api.side_effect = lambda path, *args: (
            {'active_requests': 2} if path == 'activity' else dict(state))
        with patch('codex_integration.controller.sys.platform', 'darwin'), \
                patch('codex_integration.client.discover', return_value={'bundle': '/fixture/Codex.app'}), \
                patch('codex_integration.client.processes', return_value=[Mock(pid=17, create_time=lambda: 100)]), \
                patch('codex_integration.client.close', return_value=True) as close, \
                patch('codex_integration.client.launch', return_value='started') as launch:
            preview = controller.request({'action': 'preview_restart'})
            self.assertTrue(preview['ok'], preview)
            self.assertEqual(preview['result']['activity']['active_requests'], 2)
            close.assert_not_called()
            request = {'action': 'restart_codex', 'ticket': preview['result']['ticket'], 'confirm_activity': True}
            self.assertEqual(controller.request(request)['result']['desktop_result'], 'started')
            self.assertEqual(controller.request(request)['error'], 'INVALID_PREVIEW')
            close.assert_called_once()
            launch.assert_called_once()
            preview = controller.request({'action': 'preview_restart'})
            state['forwarding']['status'] = 'fault'
            request['ticket'] = preview['result']['ticket']
            self.assertEqual(controller.request(request)['error'], 'FORWARDING_UNAVAILABLE')
            close.assert_called_once()
            self.assertTrue(controller.request({'action': 'cancel_restart'})['ok'])

    def test_external_web_write_invalidates_local_restart_preview(self):
        controller = Controller(directory='/fixture')
        controller.existing_service = Mock()
        controller.restart.pending = ('fixture',)
        result = controller.request({'action': 'web_api', 'path': 'routing/preview',
                                     'method': 'POST', 'body': {'mode': 'openai'}})
        self.assertTrue(result['ok'])
        self.assertIsNone(controller.restart.pending)

    def test_external_service_disconnect_blocks_restart_and_cancel_stays_local(self):
        controller = Controller(directory='/fixture')
        controller.existing_service = Mock()
        controller.existing_service.api.side_effect = ConfigError('SERVICE_UNREACHABLE')
        with patch('codex_integration.controller.sys.platform', 'darwin'), \
                patch.object(controller.restart, 'confirm') as confirm:
            result = controller.request({'action': 'restart_codex', 'ticket': 'fixture',
                                         'confirm_activity': True})
            self.assertEqual(result['error'], 'SERVICE_UNREACHABLE')
            confirm.assert_not_called()
            controller.existing_service.api.reset_mock()
            self.assertTrue(controller.request({'action': 'cancel_restart'})['ok'])
            controller.existing_service.api.assert_not_called()
