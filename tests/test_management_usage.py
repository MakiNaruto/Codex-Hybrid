import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from management.usage import report


class UsageTests(unittest.TestCase):
    def test_aggregation_rotation_missing_usage_and_invalid_records(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            now = 200000
            records = [
                {'time': now, 'model': 'provider/model', 'status': 'completed',
                 'usage': {'input_tokens': 100, 'output_tokens': 20, 'cached_tokens': 40}},
                {'time': now-100, 'model': 'provider/model', 'status': 'upstream_http_error'},
                {'time': now-86401, 'model': 'old', 'status': 'completed'},
                {'time': now+1, 'model': 'future', 'status': 'completed'},
                {'time': now, 'status': 'forwarding_exited'},
                {'time': 10**1000, 'model': 'huge', 'status': 'completed'},
                {'time': float('nan'), 'model': 'nan', 'status': 'completed'},
                {'time': now, 'model': 'bad', 'status': 'completed',
                 'usage': {'input_tokens': True, 'output_tokens': -1, 'total_tokens': float('nan')}},
            ]
            (root/'service.jsonl').write_text('\n'.join(map(json.dumps, records))+'\n[]\ninvalid\n')
            (root/'service.jsonl.1').write_text(json.dumps({'time': now-86400, 'model': 'other',
                'status': 'incomplete', 'usage': {'input_tokens': 10, 'output_tokens': 3,
                                                'total_tokens': 13, 'cached_tokens': 99},
                'message': 'secret', 'api_key': 'secret'}))
            result = report(root, days=1, now=now)
            self.assertEqual(len(result['models']), 3)
            first = next(m for m in result['models'] if m['model'] == 'provider/model')
            self.assertEqual(first['requests'], 2)
            self.assertEqual(first['total_tokens'], 120)
            self.assertEqual(first['requests_with_usage'], 1)
            self.assertEqual(sum(b['total_tokens'] for b in first['series']), 120)
            other = next(m for m in result['models'] if m['model'] == 'other')
            self.assertEqual(other['cached_tokens'], 10)
            self.assertNotIn('secret', json.dumps(result))
            self.assertTrue(result['coverage']['rotation_may_remove_history'])

    def test_missing_unreadable_and_partial_logs(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(report(root)['state'], 'missing')
            (root/'service.jsonl').mkdir()
            self.assertEqual(report(root)['state'], 'unavailable')
            (root/'service.jsonl.1').write_text('{}')
            self.assertEqual(report(root)['state'], 'partial')

    def test_period_validation(self):
        with self.assertRaises(ValueError):
            report(Path('.'), days=2)


class UsageHTTPTests(unittest.TestCase):
    def test_period_validation_and_authentication(self):
        import io
        from types import SimpleNamespace
        from unittest.mock import Mock
        from management.http import handle
        with TemporaryDirectory() as temp:
            gateway = SimpleNamespace(settings={'management_auth_required': True, 'management_token': 'fixture'},
                                      manager=SimpleNamespace(directory=Path(temp)))
            for query, authorized, status in [('days=7', False, 403), ('days=7', True, 200),
                    ('days=1', True, 200), ('days=30', True, 200), ('days=2', True, 400),
                    ('days=7&days=1', True, 400), ('days=', True, 400)]:
                with self.subTest(query=query, authorized=authorized):
                    headers={'Host': '127.0.0.1:1234'}
                    if authorized:
                        headers['Authorization']='Bearer fixture'
                    handler=SimpleNamespace(path='/manage/api/usage?'+query, headers=headers,
                        server=SimpleNamespace(server_port=1234), send_response=Mock(),
                        send_header=Mock(), end_headers=Mock(), wfile=io.BytesIO())
                    self.assertTrue(handle(handler, gateway, 'GET'))
                    handler.send_response.assert_called_once_with(status)
                    if status == 200:
                        self.assertEqual(json.loads(handler.wfile.getvalue())['period_days'], int(query[5:]))
