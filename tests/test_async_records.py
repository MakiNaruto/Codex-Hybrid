"""Logging backpressure must never stall producers or retain unbounded records."""
import json
import threading
from types import SimpleNamespace
import unittest

from gateway.runtime_log import AsyncRecords


class AsyncRecordsTests(unittest.TestCase):
    def test_full_queue_drops_new_records_and_close_has_a_deadline(self):
        entered, release = threading.Event(), threading.Event()
        written = []
        dropped = SimpleNamespace(value=0)

        def blocked(value):
            entered.set()
            release.wait(5)
            written.append(value)

        records = AsyncRecords(blocked, capacity=2, dropped_counter=dropped)
        try:
            records.emit({'status': 'first'})
            self.assertTrue(entered.wait(1))
            for index in range(10):
                records.emit({'index': index})
            self.assertEqual(records.dropped, 8)
            self.assertEqual(dropped.value, 8)
            records.close(timeout=.01)
            self.assertTrue(records.thread.is_alive())
        finally:
            release.set()
            records.close(timeout=2)
        self.assertFalse(records.thread.is_alive())
        self.assertEqual([entry.get('index') for entry in written], [None, 0, 1])

    def test_sink_failure_does_not_disable_following_records(self):
        written = []

        def output(value):
            if value.get('fail'):
                raise OSError('disk unavailable')
            written.append(value)

        records = AsyncRecords(output)
        records.emit({'fail': True})
        records.emit({'status': 'next'})
        records.close(timeout=2)
        self.assertEqual(records.dropped, 1)
        self.assertEqual(written, [{'status': 'next'}])

    def test_large_observation_is_bounded_before_queueing_and_transport(self):
        written = []
        records = AsyncRecords(written.append)
        records.emit({'status': 'failed', 'tool_types': ['x'*20000], 'time': 123})
        records.close(timeout=2)
        self.assertLess(len(json.dumps(written[0]).encode()), 16384)
        self.assertTrue(written[0]['record_truncated'])
        self.assertEqual(written[0]['status'], 'failed')
