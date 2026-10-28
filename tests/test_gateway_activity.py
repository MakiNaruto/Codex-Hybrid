import concurrent.futures
from contextlib import nullcontext
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from types import SimpleNamespace

from gateway.server import Gateway, Server


class ActivityTests(unittest.TestCase):
    def test_request_failure_exports_safe_support_context(self):
        from management.diagnostics import safe_details
        gateway = Gateway({'source': {}, 'max_concurrent_requests': 1,
                           'models': [], 'local_token': 'test-token'})
        records = []
        recorded = threading.Event()
        def record(entry):
            records.append(entry)
            recorded.set()
        gateway.record = record
        server = Server(('127.0.0.1', 0), gateway.handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/responses',
            data=b'{"model":"private-model","input":[],"stream":true}',
            headers={'X-Connected-Token': 'test-token'})
        with patch('gateway.server.route', side_effect=ValueError('private-chat-secret')):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with self.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(request, timeout=5)
            caught.exception.close()
            self.assertTrue(recorded.wait(3))
        result = safe_details(records[0])
        self.assertEqual(result['error_code'], 'GATEWAY_STREAM_ADAPTATION_FAILED')
        self.assertEqual(result['error_type'], 'ValueError')
        self.assertEqual(result['route_type'], 'external')
        self.assertTrue(result['stream'])
        self.assertIn('request_ref', result)
        self.assertTrue(any(p.startswith('gateway/server.py:') for p in result['error_locations']))
        self.assertNotIn('private', json.dumps(result))

    def test_stream_remains_busy_until_terminal_or_transport_failure(self):
        for fails in (False, True):
            with self.subTest(transport_failure=fails):
                gateway = Gateway({'source': {}, 'max_concurrent_requests': 1,
                                   'models': [], 'local_token': 'test-token'})
                gateway.opener = SimpleNamespace(open=lambda *args, **kwargs: nullcontext(object()))
                entered, release, finished = threading.Event(), threading.Event(), threading.Event()
                gateway.record = lambda observation: finished.set()
                server = Server(('127.0.0.1', 0), gateway.handler())
                threading.Thread(target=server.serve_forever, daemon=True).start()

                def stream(*args):
                    entered.set()
                    release.wait(5)
                    if fails:
                        raise TimeoutError()
                    yield None, {'type': 'response.completed', 'response': {'status': 'completed'}}

                def request():
                    req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/responses',
                        data=b'{"model":"test","input":[]}', headers={'X-Connected-Token': 'test-token'})
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(req, timeout=5) as response:
                        return response.read()

                try:
                    with patch('gateway.server.route', return_value=(
                            'https://example.invalid/responses', {}, {}, lambda event: event)), \
                            patch('gateway.server.adapted_stream', side_effect=stream), \
                            concurrent.futures.ThreadPoolExecutor() as pool:
                        pending = pool.submit(request)
                        try:
                            self.assertTrue(entered.wait(3))
                            self.assertEqual(gateway.activity.snapshot()['active_requests'], 1)
                        finally:
                            release.set()
                        data = pending.result(timeout=5)
                        self.assertIn(b'response.failed' if fails else b'response.completed', data)
                        self.assertTrue(finished.wait(3))
                        self.assertEqual(gateway.activity.snapshot()['active_requests'], 0)
                finally:
                    release.set();server.shutdown();server.server_close()

    def test_inflight_and_rejected_requests_release_activity(self):
        gateway = Gateway({'source': {}, 'max_concurrent_requests': 1,
                           'models': [], 'local_token': 'test-token'})
        server = Server(('127.0.0.1', 0), gateway.handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        entered, release = threading.Event(), threading.Event()

        def route(*args):
            entered.set()
            release.wait(5)
            raise ValueError('TEST_REJECTION')

        def request():
            req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/responses',
                data=json.dumps({'model': 'test', 'input': []}).encode(),
                headers={'X-Connected-Token': 'test-token'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(req, timeout=5) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                with error:
                    error.read()
                    return error.code

        with patch('gateway.server.route', side_effect=route):
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pending = pool.submit(request)
                try:
                    self.assertTrue(entered.wait(3))
                    snapshot = gateway.activity.snapshot()
                    self.assertEqual(snapshot['active_requests'], 1)
                    self.assertEqual(snapshot['gateway_status'], 'busy')
                    self.assertEqual(snapshot['codex_status'], 'unknown')
                    self.assertEqual(request(), 429)
                    self.assertEqual(gateway.activity.snapshot()['active_requests'], 1)
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=5), 400)
        self.assertEqual(gateway.activity.snapshot()['active_requests'], 0)
        self.assertEqual(gateway.activity.snapshot()['gateway_status'], 'no_activity')
