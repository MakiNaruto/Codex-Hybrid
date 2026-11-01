import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.controller import Controller
from model_catalog.catalog import ConfigError


class ExistingServiceTests(unittest.TestCase):
    def test_mac_reuses_existing_owner_and_quit_does_not_stop_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'settings.json').write_text('{}')
            controller = Controller(directory=directory)
            with patch('desktop.controller.sys.platform', 'darwin'), \
                    patch.object(controller, 'own', side_effect=ConfigError('SERVICE_ALREADY_RUNNING')), \
                    patch('desktop.existing_service.ExistingService') as adapter:
                adapter.return_value.api.return_value = {'models': ['fixture'], 'routing_mode': 'openai',
                                                         'forwarding': {'status': 'running'}}
                result = controller.request({'action': 'web_api', 'method': 'GET', 'path': 'state', 'body': None})
                self.assertTrue(result['ok'])
                self.assertEqual(result['result']['models'], ['fixture'])
                self.assertTrue(result['result']['external_service'])
                adapter.return_value.api.reset_mock()
                self.assertTrue(controller.request({'action': 'shutdown'})['ok'])
                adapter.return_value.api.assert_not_called()

    def test_windows_keeps_existing_single_owner_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'settings.json').write_text('{}')
            controller = Controller(directory=directory)
            with patch('desktop.controller.sys.platform', 'win32'), \
                    patch.object(controller, 'own', side_effect=ConfigError('SERVICE_ALREADY_RUNNING')):
                self.assertEqual(controller.request({'action': 'status'})['error'], 'SERVICE_ALREADY_RUNNING')

    def test_adapter_keeps_token_off_frontend_and_never_uses_system_proxy(self):
        from desktop.existing_service import ExistingService
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
        from desktop.existing_service import ExistingService
        with tempfile.TemporaryDirectory() as tmp, patch('desktop.existing_service.build_opener') as opener:
            with self.assertRaises(ConfigError):
                ExistingService({'port': 18891}, tmp)
            opener.assert_not_called()
