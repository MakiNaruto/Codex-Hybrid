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
        result = report(manager, days=None)
        self.assertEqual(result['log']['errors'], [{'status': 'upstream_http_error',
            'phase': 'connect_upstream', 'http_status': 401, 'time': 123, 'elapsed_ms': 10}])
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))

    def test_forwarding_faults_export_metadata_without_raw_failure(self):
        self.log.write_text('\n'.join(json.dumps({'status': status, 'time': 123,
            'message': 'private-details', 'settings': {'api_key': 'secret'}})
            for status in ('forwarding_exited', 'forwarding_start_failed'))+'\n')
        errors = recent_errors(self.directory)['errors']
        self.assertEqual(len(errors), 2)
        self.assertNotIn('private', json.dumps(errors))
        self.assertNotIn('secret', json.dumps(errors))

    def test_only_allowlisted_startup_reasons_are_exported(self):
        self.log.write_text('\n'.join(json.dumps({'status': 'forwarding_start_failed', 'time': 123,
            'error_reason': reason}) for reason in ('port_in_use', 'raw-secret-message'))+'\n')
        errors = recent_errors(self.directory)['errors']
        self.assertEqual(errors[0]['error_reason'], 'port_in_use')
        self.assertNotIn('error_reason', errors[1])

    def test_malformed_records_and_fields_are_not_exported(self):
        self.log.write_text('\n'.join(['invalid', '[]', '{"status": {}}',
            json.dumps({'status': 'private-status'}), json.dumps({'status': 'completed'}),
            json.dumps({'status': 'failed', 'phase': [], 'time': 'private-time',
                        'elapsed_ms': float('inf'), 'http_status': True})]) + '\n')
        self.assertEqual(recent_errors(self.directory)['errors'], [{'status': 'failed', 'time': self.log.stat().st_mtime, 'time_source': 'file_modified'}])

    def test_full_log_is_scanned_without_twenty_error_limit(self):
        self.log.write_bytes(b'x' * 150000 + b'\n' + b'\n'.join(
            json.dumps({'status': 'failed', 'time': index}).encode() for index in range(30)))
        result = recent_errors(self.directory)
        self.assertEqual([e['time'] for e in result['errors']], list(reversed(range(30))))
        self.assertNotIn('truncated', result)

    def test_stderr_and_startup_errors_are_safe_and_include_windows_codes(self):
        (self.directory / 'service.stderr').write_text(
            'Traceback (most recent call last):\n'
            '  File "secret-path", line 1\n'
            '    secret_key = "private-chat"\n'
            'ConnectionAbortedError: [WinError 10053] secret-token\n', encoding='utf-8')
        (self.directory / 'service.startup.stderr').write_text(
            'ValueError: secret-startup-message\n', encoding='utf-8')
        result = recent_errors(self.directory)
        self.assertEqual(result['state'], 'available')
        self.assertCountEqual(result['errors'], [
            {'status': 'other', 'source': 'service.stderr',
             'exception_type': 'ConnectionAbortedError', 'winerror': 10053, 'time': (self.directory / 'service.stderr').stat().st_mtime, 'time_source': 'file_modified'},
            {'status': 'other', 'source': 'service.startup.stderr', 'exception_type': 'ValueError', 'time': (self.directory / 'service.startup.stderr').stat().st_mtime, 'time_source': 'file_modified'}])
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))

    def test_rotated_sources_and_unrecognized_stderr_are_included(self):
        (self.directory / 'service.jsonl.1').write_text('{"status":"failed"}\n')
        (self.directory / 'service.stderr.3').write_text('unrecognized secret failure\n')
        result = recent_errors(self.directory)
        self.assertCountEqual(result['errors'], [
            {'status': 'failed', 'time': (self.directory / 'service.jsonl.1').stat().st_mtime, 'time_source': 'file_modified'}, {'status': 'other', 'source': 'service.stderr.3', 'time': (self.directory / 'service.stderr.3').stat().st_mtime, 'time_source': 'file_modified'}])
        self.assertNotIn('secret', json.dumps(result))

    def test_timestamped_runtime_exception_retains_actual_time(self):
        from gateway.runtime_log import RuntimeLog
        log = RuntimeLog(self.directory)
        log.stderr.write('ConnectionAbortedError: [WinError 10053] private-message\n')
        log.close()
        raw = json.loads((self.directory / 'service.stderr').read_text())
        result = recent_errors(self.directory)['errors'][0]
        self.assertEqual(result['time'], raw['time'])
        self.assertEqual(result['winerror'], 10053)
        self.assertNotIn('time_source', result)
        self.assertNotIn('private-message', json.dumps(result))

    def test_partial_read_failure_is_visible(self):
        self.log.write_text('{"status":"failed"}\n')
        (self.directory / 'service.stderr').mkdir()
        result = recent_errors(self.directory)
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(result['errors'], [{'status': 'failed', 'time': self.log.stat().st_mtime, 'time_source': 'file_modified'}])

    def test_date_filters_include_boundary_and_exclude_future_records(self):
        now = 4000000
        ages = [0, 86400, 86401, 7*86400, 7*86400+1, 30*86400, 30*86400+1, -1]
        self.log.write_text('\n'.join(json.dumps({'status': 'failed', 'time': now-age}) for age in ages))
        for days, count in [(1, 2), (7, 4), (30, 6), (None, 8)]:
            with self.subTest(days=days):
                self.assertEqual(len(recent_errors(self.directory, days=days, now=now)['errors']), count)

    def test_date_filter_reads_errors_before_old_tail_limit(self):
        self.log.write_bytes(b'{"status":"failed","time":100000}\n' + b'x'*150000 + b'\n')
        self.assertEqual(len(recent_errors(self.directory, days=1, now=100000)['errors']), 1)

    def test_old_stderr_uses_reference_time_for_date_filter(self):
        import os
        path = self.directory / 'service.stderr.1'
        path.write_text('ConnectionAbortedError: [WinError 10053] hidden\n')
        os.utime(path, (100000, 100000))
        self.assertEqual(len(recent_errors(self.directory, days=1, now=100001)['errors']), 1)
        self.assertEqual(len(recent_errors(self.directory, days=1, now=200000)['errors']), 0)

    def test_identical_legacy_errors_are_grouped_without_merging_timestamped_errors(self):
        path = self.directory / 'service.stderr'
        path.write_text('ConnectionAbortedError: [WinError 10053] hidden\n' * 4)
        errors = recent_errors(self.directory)['errors']
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['count'], 4)
        path.write_text('\n'.join(json.dumps({'time': 100000, 'message':
            'ConnectionAbortedError: [WinError 10053] hidden'}) for _ in range(2)))
        errors = recent_errors(self.directory)['errors']
        self.assertEqual(len(errors), 2)
        self.assertTrue(all('count' not in entry for entry in errors))

    def test_missing_and_unreadable_logs_are_explicit(self):
        self.assertEqual(recent_errors(self.directory)['state'], 'missing')
        self.log.mkdir()
        result = recent_errors(self.directory)
        self.assertEqual(result['state'], 'unavailable')
        self.assertTrue(result['coverage']['read_failed'])

    def test_support_metadata_is_allowlisted_and_request_reference_is_anonymous(self):
        record = {'status': 'upstream_connection_failed', 'time': 123,
                  'request_id': 'a'*32, 'protocol': 'openai_responses', 'route_type': 'external',
                  'stream': True, 'proxy_configured': False, 'error_kind': 'timeout',
                  'errno': -2, 'winerror': 10053,
                  'error_type': 'URLError', 'cause_type': 'TimeoutError', 'timeout_seconds': 120,
                  'error_locations': ['gateway/server.py:123', 'C:/private/secret.py:12',
                                      'gateway/../../secret.py:1', 'gateway/server.py:12:secret'],
                  'upstream_error_type': 'rate_limit_error', 'upstream_error_code': 'secret-key',
                  'message': 'private-chat', 'headers': {'Authorization': 'secret-key'}}
        self.log.write_text(json.dumps(record))
        result = recent_errors(self.directory)['errors'][0]
        self.assertEqual(result['error_locations'], ['gateway/server.py:123'])
        self.assertEqual(result['error_kind'], 'timeout')
        self.assertEqual(result['errno'], -2)
        self.assertEqual(result['winerror'], 10053)
        self.assertEqual(result['protocol'], 'openai_responses')
        self.assertEqual(result['upstream_error_type'], 'rate_limit_error')
        self.assertEqual(len(result['request_ref']), 24)
        self.assertEqual(result, recent_errors(self.directory)['errors'][0])
        encoded = json.dumps(result)
        for secret in ('private', 'secret', 'a'*32, 'Authorization'):
            self.assertNotIn(secret, encoded)

    def test_untrusted_metadata_and_wrong_types_are_omitted(self):
        self.log.write_text(json.dumps({'status': 'failed', 'request_id': 'secret',
            'protocol': 'private', 'error_kind': [], 'error_type': 'secret',
            'stream': 'secret', 'errno': True, 'error_locations': ['gateway/nonexistent.py:1']}))
        result = recent_errors(self.directory)['errors'][0]
        self.assertEqual(set(result), {'status', 'time', 'time_source'})

    def test_report_includes_environment_and_retention_limits(self):
        manager = SimpleNamespace(directory=self.directory, gateway=SimpleNamespace(),
            routing_state=lambda: 'project', activity_state=lambda: {})
        result = report(manager)
        self.assertEqual(result['schema_version'], 2)
        self.assertEqual(set(result['environment']),
                         {'app_version', 'os', 'architecture', 'python_version'})
        self.assertTrue(result['log']['coverage']['retained_files_only'])
        self.assertTrue(result['log']['coverage']['rotation_may_remove_history'])
