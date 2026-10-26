import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from management.diagnostics import recent_errors, report


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.log = self.directory / 'service.jsonl'

    def test_export_uses_allowlist_even_when_log_contains_secrets(self):
        self.log.write_text(json.dumps({'status': 'upstream_http_error', 'phase': 'connect_upstream',
            'http_status': 401, 'time': 123, 'elapsed_ms': 10, 'api_key': 'secret-key',
            'message': 'private-chat', 'request_id': 'private-id', 'model': 'private-model',
            'headers': {'Authorization': 'secret-token'}}) + '\n')
        manager = SimpleNamespace(directory=self.directory, gateway=SimpleNamespace(),
            routing_state=lambda: 'project', activity_state=lambda: {'codex_status': 'unknown'})
        result = report(manager)
        self.assertEqual(result['log']['errors'], [{'status': 'upstream_http_error',
            'phase': 'connect_upstream', 'http_status': 401, 'time': 123, 'elapsed_ms': 10}])
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))

    def test_malformed_records_and_fields_are_not_exported(self):
        self.log.write_text('\n'.join(['invalid', '[]', '{"status": {}}',
            json.dumps({'status': 'private-status'}), json.dumps({'status': 'completed'}),
            json.dumps({'status': 'failed', 'phase': [], 'time': 'private-time',
                        'elapsed_ms': float('inf'), 'http_status': True})]) + '\n')
        self.assertEqual(recent_errors(self.directory)['errors'], [{'status': 'failed'}])

    def test_tail_is_bounded_and_keeps_latest_twenty_errors(self):
        self.log.write_bytes(b'x' * 150000 + b'\n' + b'\n'.join(
            json.dumps({'status': 'failed', 'time': index}).encode() for index in range(30)))
        result = recent_errors(self.directory)
        self.assertEqual([e['time'] for e in result['errors']], list(range(10, 30)))

    def test_missing_and_unreadable_logs_are_explicit(self):
        self.assertEqual(recent_errors(self.directory), {'state': 'missing', 'errors': []})
        self.log.mkdir()
        self.assertEqual(recent_errors(self.directory), {'state': 'unavailable', 'errors': []})
