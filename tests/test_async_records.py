"""Logging backpressure must never stall producers or retain unbounded records."""
import json
from contextlib import closing
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
import unittest

from gateway.runtime_log import AsyncRecords, RuntimeLog


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

    def test_disk_write_and_rotation_failures_are_counted_and_logging_recovers(self):
        with TemporaryDirectory() as directory, closing(RuntimeLog(Path(directory))) as log:
            # Rotation and stream writes both catch errors inside Python logging.
            for target, operation in ((log.events, 'shouldRollover'), (log.events.stream, 'write')):
                with self.subTest(operation=operation):
                    records = AsyncRecords(log.emit)
                    try:
                        with patch.object(target, operation, side_effect=OSError('private disk error')):
                            records.emit({'status': 'failed'})
                            records.close(timeout=1)
                        self.assertEqual(records.dropped, 1)
                    finally:
                        records.close(timeout=1)
            self.assertEqual((Path(directory)/'service.jsonl').read_text(), '')
            records = AsyncRecords(log.emit)
            records.emit({'status': 'recovered'})
            records.close(timeout=1)
            self.assertEqual(records.dropped, 0)
            self.assertEqual(json.loads((Path(directory)/'service.jsonl').read_text())['status'], 'recovered')
