"""Size-limited local runtime logs shared by foreground and background starts."""
from datetime import datetime, timezone
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import threading
import time


LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 3


def bounded_record(observation):
    observation = dict(observation)
    if len(json.dumps(observation).encode('utf-8')) <= 16384:
        return observation
    compact = {'record_truncated': True}
    for key in ('time', 'timestamp', 'status', 'phase', 'request_id', 'http_status',
                'elapsed_ms', 'error_kind', 'error_reason', 'exit_code', 'retry_attempt'):
        value = observation.get(key)
        if type(value) in (int, float, bool) or value is None:
            compact[key] = value
        elif isinstance(value, str):
            compact[key] = value[:128]
    return compact


class AsyncRecords:
    """Best-effort records: bounded backlog, no sink I/O on producer threads."""
    def __init__(self, output, capacity=256, dropped_counter=None):
        self.output = output
        self.queue = queue.Queue(maxsize=capacity)
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.dropped = 0
        self.dropped_counter = dropped_counter
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def _drop(self):
        # Called under the local lock; only this process writes its shared counter.
        self.dropped += 1
        if self.dropped_counter is not None:
            self.dropped_counter.value += 1

    def emit(self, observation):
        try:
            observation = bounded_record(observation)
        except (TypeError, ValueError, RecursionError):
            with self.lock:
                self._drop()
            return
        with self.lock:
            if self.closed.is_set():
                self._drop()
                return
            try:
                self.queue.put_nowait(observation)
            except queue.Full:
                self._drop()

    def _write(self):
        while not self.closed.is_set() or not self.queue.empty():
            try:
                observation = self.queue.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                self.output(observation)
            except Exception:
                # Disk and IPC failures must not disable subsequent logging or callers.
                with self.lock:
                    self._drop()

    def close(self, timeout=.2):
        with self.lock:
            self.closed.set()
        self.thread.join(timeout)


class PrivateRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        # Do not recursively log a disk/rotation failure through redirected stderr.
        try:
            os.write(2, b'Codex Hybrid: unable to write runtime log.\n')
        except OSError:
            pass

    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        return io.open(fd, 'a', encoding='utf-8')


def handler(path, max_bytes=LOG_BYTES, backups=LOG_BACKUPS):
    result = PrivateRotatingHandler(path, maxBytes=max_bytes, backupCount=backups, encoding='utf-8')
    result.setFormatter(logging.Formatter('%(message)s'))
    return result


class ErrorStream:
    """Line-buffer traceback writes, bounding even a single unterminated line."""
    encoding = 'utf-8'

    def __init__(self, output):
        self.output = output
        self.buffer = ''
        self.lock = threading.RLock()

    def emit_line(self, line):
        now = time.time()
        record = {'time': now, 'timestamp': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  'message': line}
        self.output.handle(logging.makeLogRecord({'msg': json.dumps(record), 'levelno': logging.ERROR}))

    def write(self, value):
        with self.lock:
            self.buffer += value
            while '\n' in self.buffer or len(self.buffer) >= 8192:
                end = self.buffer.find('\n')
                end = min(end, 8192) if end >= 0 else 8192
                line, self.buffer = self.buffer[:end], self.buffer[end + (self.buffer[end:end+1] == '\n'):]
                self.emit_line(line)
        return len(value)

    def flush(self):
        with self.lock:
            if self.buffer:
                self.emit_line(self.buffer)
                self.buffer = ''
            self.output.flush()

    def isatty(self):
        return False


class RuntimeLog:
    def __init__(self, directory):
        self.events = handler(directory / 'service.jsonl')
        self.errors = handler(directory / 'service.stderr')
        self.stderr = ErrorStream(self.errors)

    def emit(self, observation):
        observation = dict(observation)
        observation.setdefault('time', time.time())
        observation['timestamp'] = datetime.fromtimestamp(observation['time'], timezone.utc).isoformat()
        encoded = json.dumps(bounded_record(observation))
        self.events.handle(logging.makeLogRecord({'msg': encoded, 'levelno': logging.INFO}))

    def close(self):
        self.stderr.flush()
        self.events.close()
        self.errors.close()
