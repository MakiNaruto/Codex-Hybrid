import json
from datetime import datetime, time, timedelta
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
            (root/'service.jsonl.1').write_text(json.dumps({'time': now-200, 'model': 'other',
                'status': 'incomplete', 'usage': {'input_tokens': 10, 'output_tokens': 3,
                                                'total_tokens': 13, 'cached_tokens': 99},
                'message': 'secret', 'api_key': 'secret'}))
            result = report(root, days='today', now=now)
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

    def test_model_labels_follow_the_reported_models(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            now = 200000
            (root/'service.jsonl').write_text(json.dumps(
                {'time': now, 'model': 'record/model-a', 'status': 'completed'})+'\n')
            labeled = report(root, days='today', now=now,
                             labels={'record/model-a': ('Vendor', 'Label model-a')})
            row = labeled['models'][0]
            self.assertEqual((row['provider_name'], row['model_name']), ('Vendor', 'Label model-a'))
            self.assertNotIn('model_name', report(root, days='today', now=now)['models'][0])

    def test_calendar_periods_use_exclusive_local_midnight_boundaries(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            local_noon = datetime(2026, 11, 2, 12, 30).astimezone()
            now = local_noon.timestamp()
            today_start = local_noon.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            yesterday_start = (local_noon.replace(hour=0, minute=0, second=0, microsecond=0)
                               - timedelta(days=1)).timestamp()
            tomorrow_start = (local_noon.replace(hour=0, minute=0, second=0, microsecond=0)
                              + timedelta(days=1)).timestamp()
            records = [
                {'time': yesterday_start - 1, 'model': 'model', 'status': 'completed'},
                {'time': yesterday_start, 'model': 'model', 'status': 'completed'},
                {'time': today_start - 1, 'model': 'model', 'status': 'completed'},
                {'time': today_start, 'model': 'model', 'status': 'completed'},
                {'time': today_start + 3600, 'model': 'model', 'status': 'completed'},
                {'time': tomorrow_start, 'model': 'model', 'status': 'completed'},
            ]
            (root/'service.jsonl').write_text('\n'.join(map(json.dumps, records))+'\n')

            today = report(root, days='today', now=now)
            yesterday = report(root, days='yesterday', now=now)
            legacy_today = report(root, days='1', now=now)

            self.assertEqual(today['period'], 'today')
            self.assertEqual(legacy_today['period'], 'today')
            self.assertEqual(today['period_days'], 1)
            self.assertEqual(today['period_start'], today_start)
            self.assertEqual(today['period_end'], tomorrow_start)
            self.assertEqual(today['bucket_seconds'], 3600)
            self.assertEqual(len(today['buckets']), 24)
            self.assertEqual(datetime.fromtimestamp(today['buckets'][0]).time(), time(0, 0))
            self.assertEqual(today['models'][0]['requests'], 2)
            self.assertEqual(sum(row['requests'] for row in today['models'][0]['series']), 2)

            self.assertEqual(yesterday['period'], 'yesterday')
            self.assertEqual(yesterday['period_start'], yesterday_start)
            self.assertEqual(yesterday['period_end'], today_start)
            self.assertEqual(len(yesterday['buckets']), 24)
            self.assertEqual(yesterday['models'][0]['requests'], 2)

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
                                      manager=SimpleNamespace(directory=Path(temp), model_labels=lambda: {}))
            for query, authorized, status in [('period=7', False, 403), ('period=7', True, 200),
                    ('period=today', True, 200), ('period=yesterday', True, 200),
                    ('period=30', True, 200), ('period=2', True, 400),
                    ('period=7&days=1', True, 400), ('period=', True, 400)]:
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
                        result = json.loads(handler.wfile.getvalue())
                        self.assertIn(result['period'], {'today', 'yesterday', 7, 30})
