import io
import ssl
import unittest
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from unittest.mock import patch

from gateway.transport import FreshProxyOpener, discover_proxies


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
        with patch('gateway.transport.discover_proxies', side_effect=configurations), \
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
        with patch('gateway.transport.discover_proxies', return_value={}), \
                patch('urllib.request.AbstractHTTPHandler.do_open', side_effect=failure) as connect:
            with self.assertRaises(urllib.error.URLError):
                transport.open(urllib.request.Request('https://upstream.example/responses', data=b'{}'))
            self.assertEqual(connect.call_count, 1)
        with patch('gateway.transport.discover_proxies', return_value={}), \
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
        with patch('gateway.transport.discover_proxies', side_effect=[
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

        with patch('gateway.transport.discover_proxies', return_value={}), \
                patch('urllib.request.AbstractHTTPHandler.do_open', new=redirect):
            with self.assertRaises(urllib.error.HTTPError) as error:
                FreshProxyOpener().open(urllib.request.Request(
                    'https://upstream.example/responses', data=b'{}',
                    headers={'Authorization': 'Bearer test-only'}))
            self.assertEqual(error.exception.code, 307)
            error.exception.close()


class PlatformProxyTests(unittest.TestCase):
    def test_windows_no_proxy_does_not_hide_registry_proxy(self):
        with patch('gateway.transport.sys.platform', 'win32'), \
                patch('urllib.request.getproxies_registry', create=True, return_value={'https': 'http://127.0.0.1:7897'}), \
                patch('urllib.request.getproxies_environment', return_value={'no': 'localhost'}):
            self.assertEqual(discover_proxies(), {'https': 'http://127.0.0.1:7897'})

    def test_windows_system_proxy_overrides_inherited_environment(self):
        with patch('gateway.transport.sys.platform', 'win32'), \
                patch('urllib.request.getproxies_registry', create=True, return_value={'https': 'http://127.0.0.1:7897'}), \
                patch('urllib.request.getproxies_environment', return_value={'https': 'http://127.0.0.1:7898'}):
            self.assertEqual(discover_proxies()['https'], 'http://127.0.0.1:7897')

    def test_windows_requests_follow_system_changes_despite_all_overrides(self):
        destinations = []

        def connect(handler, connection_type, request, **kwargs):
            destinations.append((request.host, request._tunnel_host))
            return upstream_response(request.full_url)

        transport = FreshProxyOpener('http://127.0.0.1:18099')
        with patch('gateway.transport.sys.platform', 'win32'), \
                patch('urllib.request.getproxies_registry', create=True, side_effect=[
                    {'https': 'http://127.0.0.1:18001'},
                    {'https': 'http://127.0.0.1:18002'}, {}]), \
                patch('urllib.request.getproxies_environment', return_value={
                    'https': 'http://127.0.0.1:18098', 'no': '*'}), \
                patch('urllib.request.proxy_bypass_registry', create=True, return_value=False), \
                patch('urllib.request.AbstractHTTPHandler.do_open', new=connect):
            for _ in range(3):
                with transport.open(urllib.request.Request('https://upstream.example/responses')):
                    pass
        self.assertEqual(destinations, [
            ('127.0.0.1:18001', 'upstream.example'),
            ('127.0.0.1:18002', 'upstream.example'),
            ('upstream.example', None),
        ])

    def test_windows_system_bypass_keeps_local_requests_direct(self):
        with patch('gateway.transport.sys.platform', 'win32'), \
                patch('urllib.request.getproxies_registry', create=True, return_value={
                    'http': 'http://127.0.0.1:18001'}), \
                patch('urllib.request.proxy_bypass_registry', create=True, return_value=True), \
                patch('urllib.request.AbstractHTTPHandler.do_open', return_value=
                      upstream_response('http://localhost/')):
            request = urllib.request.Request('http://localhost/')
            with FreshProxyOpener().open(request):
                self.assertEqual(request.host, 'localhost')
                self.assertIsNone(request._tunnel_host)

    def test_macos_keeps_explicit_upstream_proxy(self):
        with patch('gateway.transport.sys.platform', 'darwin'), \
                patch('urllib.request.proxy_bypass', return_value=False), \
                patch('urllib.request.AbstractHTTPHandler.do_open', return_value=
                      upstream_response('https://upstream.example/')):
            request = urllib.request.Request('https://upstream.example/')
            with FreshProxyOpener('http://127.0.0.1:18001').open(request):
                self.assertEqual(request.host, '127.0.0.1:18001')
                self.assertEqual(request._tunnel_host, 'upstream.example')

    def test_macos_keeps_native_discovery(self):
        with patch('gateway.transport.sys.platform', 'darwin'), \
                patch('urllib.request.getproxies', return_value={'https': 'http://127.0.0.1:7897'}) as discover:
            self.assertEqual(discover_proxies()['https'], 'http://127.0.0.1:7897')
            discover.assert_called_once()
