import io
import ssl
import unittest
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from unittest.mock import patch

from gateway.transport import FreshProxyOpener


def upstream_response(url, code=200, headers=None):
    response = urllib.response.addinfourl(io.BytesIO(b'OK'), headers or Message(), url, code)
    response.msg = 'OK' if code == 200 else 'Temporary Redirect'
    return response


class FreshProxyOpenerTests(unittest.TestCase):
    def test_running_service_tracks_proxy_changes_and_removal(self):
        transport = FreshProxyOpener()
        destinations = []

        def connect(handler, connection_type, request, **kwargs):
            destinations.append((request.host, request._tunnel_host))
            return upstream_response(request.full_url)

        configurations = [
            {'https': 'http://127.0.0.1:18001'},
            {'https': 'http://127.0.0.1:18002'},
            {},
        ]
        with patch('urllib.request.getproxies', side_effect=configurations), \
                patch('urllib.request.proxy_bypass', return_value=False), \
                patch('urllib.request.AbstractHTTPHandler.do_open', new=connect):
            for configured in (True, True, False):
                request = urllib.request.Request('https://upstream.example/responses', data=b'{}')
                with transport.open(request) as response:
                    self.assertEqual(response.read(), b'OK')
                self.assertEqual(request.connected_proxy_configured, configured)

        self.assertEqual(destinations, [
            ('127.0.0.1:18001', 'upstream.example'),
            ('127.0.0.1:18002', 'upstream.example'),
            ('upstream.example', None),
        ])

    def test_connection_failure_does_not_replay_post_and_next_call_can_recover(self):
        transport = FreshProxyOpener()
        failure = urllib.error.URLError(ssl.SSLEOFError(8, 'EOF'))
        with patch('urllib.request.getproxies', return_value={}), \
                patch('urllib.request.AbstractHTTPHandler.do_open', side_effect=failure) as connect:
            with self.assertRaises(urllib.error.URLError):
                transport.open(urllib.request.Request('https://upstream.example/responses', data=b'{}'))
            self.assertEqual(connect.call_count, 1)
        with patch('urllib.request.getproxies', return_value={}), \
                patch('urllib.request.AbstractHTTPHandler.do_open', return_value=
                      upstream_response('https://upstream.example')):
            with transport.open(urllib.request.Request('https://upstream.example/responses', data=b'{}')) as response:
                self.assertEqual(response.read(), b'OK')

    def test_new_openers_discover_current_platform_proxy_settings(self):
        destinations = []

        def connect(handler, connection_type, request, **kwargs):
            destinations.append((request.host, request._tunnel_host))
            return upstream_response(request.full_url)

        # The current transport delegates platform/environment precedence to
        # urllib.getproxies; mock that public boundary on every platform.
        with patch('urllib.request.getproxies', side_effect=[
                {'https': 'http://127.0.0.1:18001'}, {},
                {'https': 'http://127.0.0.1:18002'}]) as discover, \
                patch('urllib.request.proxy_bypass', return_value=False), \
                patch('urllib.request.AbstractHTTPHandler.do_open', new=connect):
            for _ in range(3):
                with FreshProxyOpener().open(urllib.request.Request(
                        'https://upstream.example/responses', data=b'{}')) as response:
                    self.assertEqual(response.read(), b'OK')
            self.assertEqual(discover.call_count, 3)
        self.assertEqual(destinations, [
            ('127.0.0.1:18001', 'upstream.example'),
            ('upstream.example', None),
            ('127.0.0.1:18002', 'upstream.example'),
        ])

    def test_redirect_cannot_forward_credentials(self):
        def redirect(handler, connection_type, request, **kwargs):
            headers = Message()
            headers['Location'] = 'https://other.example/responses'
            return upstream_response(request.full_url, 307, headers)

        with patch('urllib.request.getproxies', return_value={}), \
                patch('urllib.request.AbstractHTTPHandler.do_open', new=redirect):
            with self.assertRaises(urllib.error.HTTPError) as error:
                FreshProxyOpener().open(urllib.request.Request(
                    'https://upstream.example/responses', data=b'{}',
                    headers={'Authorization': 'Bearer test-only'}))
            self.assertEqual(error.exception.code, 307)
            error.exception.close()
