"""Client cancellation must not produce a second HTTP response or traceback."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gateway.server import Gateway
from management.http import handle


class ClientDisconnectTests(unittest.TestCase):
    def test_management_disconnect_does_not_retry_response(self):
        for stage in ('end_headers', 'write'):
            for error in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                with self.subTest(stage=stage, error=error):
                    request = SimpleNamespace(
                        path='/manage/api/activity', headers={'Host': '127.0.0.1:1234'},
                        server=SimpleNamespace(server_port=1234), send_response=Mock(),
                        send_header=Mock(), end_headers=Mock(), wfile=SimpleNamespace(write=Mock()))
                    target = request.end_headers if stage == 'end_headers' else request.wfile.write
                    target.side_effect = error()
                    gateway = SimpleNamespace(settings={}, manager=SimpleNamespace(
                        activity_state=lambda: {'active_requests': 0}))
                    self.assertTrue(handle(request, gateway, 'GET'))
                    request.send_response.assert_called_once_with(200)
                    self.assertTrue(request.close_connection)

    def test_gateway_boundary_handles_disconnect_but_preserves_unexpected_errors(self):
        gateway = Gateway({'source': {}, 'models': [], 'max_concurrent_requests': 1})
        handler = gateway.handler()
        for error in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            request = object.__new__(handler)
            with patch('http.server.BaseHTTPRequestHandler.handle', side_effect=error()):
                request.handle()
            self.assertTrue(request.close_connection)
        with patch('http.server.BaseHTTPRequestHandler.handle', side_effect=RuntimeError('bug')):
            with self.assertRaises(RuntimeError):
                object.__new__(handler).handle()
