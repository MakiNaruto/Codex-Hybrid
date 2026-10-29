import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gateway.runtime_log import ErrorStream, RuntimeLog, handler


class RuntimeLogTests(unittest.TestCase):
    def test_rotation_bounds_files_and_preserves_latest_record(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'service.jsonl'
            output = handler(path, max_bytes=100, backups=2)
            try:
                for index in range(30):
                    output.handle(logging.makeLogRecord({'msg': json.dumps({'index': index, 'padding': 'x'*30})}))
                self.assertEqual(json.loads(path.read_text().splitlines()[-1])['index'], 29)
                self.assertEqual(len(list(Path(temp).iterdir())), 3)
                self.assertTrue(all(file.stat().st_size <= 100 for file in Path(temp).iterdir()))
            finally:
                output.close()

    def test_stderr_fragments_and_long_lines_remain_bounded(self):
        with TemporaryDirectory() as temp:
            output = handler(Path(temp) / 'service.stderr', max_bytes=20000, backups=1)
            try:
                stream = ErrorStream(output)
                stream.write('one');stream.write(' two\nthree')
                stream.flush()
                self.assertEqual([json.loads(line)['message'] for line in (Path(temp) / 'service.stderr').read_text().splitlines()], ['one two', 'three'])
                stream.write('x'*30000)
                self.assertLess(len(stream.buffer), 8192)
                stream.flush()
                self.assertLessEqual(len(list(Path(temp).iterdir())), 2)
            finally:
                output.close()

    def test_runtime_events_are_json_lines(self):
        with TemporaryDirectory() as temp:
            log = RuntimeLog(Path(temp))
            log.emit({'status': 'listening'})
            log.stderr.write('test error\n')
            log.close()
            event = json.loads((Path(temp)/'service.jsonl').read_text())
            self.assertEqual(event['status'], 'listening')
            self.assertGreater(event['time'], 0)
            self.assertIn('+00:00', event['timestamp'])
            error = json.loads((Path(temp)/'service.stderr').read_text())
            self.assertEqual(error['message'], 'test error')
            self.assertGreater(error['time'], 0)
            self.assertIn('+00:00', error['timestamp'])

    def test_large_tool_metadata_cannot_exceed_log_size_limit(self):
        with TemporaryDirectory() as temp:
            log = RuntimeLog(Path(temp))
            log.emit({'status': 'failed', 'time': 123, 'tool_types': ['x'*20000]})
            log.close()
            path = Path(temp)/'service.jsonl'
            self.assertLess(path.stat().st_size, 16384)
            self.assertTrue(json.loads(path.read_text())['record_truncated'])

    def test_process_exit_is_bounded_even_with_a_stuck_event_or_stderr_writer(self):
        script = """import sys, threading
from pathlib import Path
from gateway.runtime_log import RuntimeLog
log = RuntimeLog(Path(sys.argv[1]))
entered = threading.Event()
def blocked(record):
    entered.set()
    threading.Event().wait(30)
    return False
output = log.events if sys.argv[2] == 'events' else log.errors
output.shouldRollover = blocked
def write():
    if sys.argv[2] == 'events':
        log.emit({'status': 'probe'})
    else:
        log.stderr.write('probe\\n')
threading.Thread(target=write, daemon=True).start()
assert entered.wait(1)
log.close()
print('closed', flush=True)
"""
        for kind in ('events', 'stderr'):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                result = subprocess.run([sys.executable, '-c', script, directory, kind],
                    env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src')),
                    capture_output=True, text=True, timeout=2)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('closed', result.stdout)

    def test_close_flushes_a_final_unterminated_stderr_line(self):
        with TemporaryDirectory() as directory:
            log = RuntimeLog(Path(directory))
            log.stderr.write('last fragment')
            log.close()
            self.assertEqual(json.loads((Path(directory)/'service.stderr').read_text())['message'], 'last fragment')
