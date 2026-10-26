import json
import logging
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
                self.assertEqual((Path(temp) / 'service.stderr').read_text(), 'one two\nthree\n')
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
            self.assertEqual(json.loads((Path(temp)/'service.jsonl').read_text()), {'status': 'listening'})
            self.assertEqual((Path(temp)/'service.stderr').read_text(), 'test error\n')

    def test_large_tool_metadata_cannot_exceed_log_size_limit(self):
        with TemporaryDirectory() as temp:
            log = RuntimeLog(Path(temp))
            log.emit({'status': 'failed', 'time': 123, 'tool_types': ['x'*20000]})
            log.close()
            path = Path(temp)/'service.jsonl'
            self.assertLess(path.stat().st_size, 16384)
            self.assertTrue(json.loads(path.read_text())['record_truncated'])
