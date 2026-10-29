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
    """Bounded background records; a sink exception or explicit False counts as a drop."""
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
                if self.output(observation) is False:
                    with self.lock:
                        self._drop()
            except Exception:
                # Disk and IPC failures must not disable subsequent logging or callers.
                with self.lock:
                    self._drop()

    def close(self, timeout=.2):
        with self.lock:
            self.closed.set()
        self.thread.join(timeout)


class PrivateRotatingHandler(RotatingFileHandler):
    def __init__(self, *args, **kwargs):
        # Keep disk I/O off Handler.lock: logging.shutdown() acquires that lock
        # at interpreter exit even after RuntimeLog.close() has returned.
        self.io_lock = threading.RLock()
        self.close_guard = threading.Lock()
        self.closing = threading.Event()
        self.close_thread = None
        super().__init__(*args, **kwargs)

    def handle(self, record):
        accepted = self.filter(record)
        if isinstance(accepted, logging.LogRecord):
            record = accepted
        if accepted:
            with self.io_lock:
                if self.closing.is_set():
                    record.runtime_write_failed = True
                    return False
                self.emit(record)
        return accepted

    def flush(self):
        # Once close starts, only the cleanup thread may flush or close files.
        if not self.closing.is_set():
            with self.io_lock:
                if self.stream and not self.closing.is_set():
                    self.stream.flush()

    def _close_file(self, final_record):
        try:
            with self.io_lock:
                try:
                    if final_record is not None and self.stream:
                        self.emit(final_record)
                finally:
                    stream, self.stream = self.stream, None
                    if stream:
                        stream.close()
        except OSError:
            pass  # Shutdown is best effort; never log recursively during cleanup.
        finally:
            logging.Handler.close(self)

    def close(self, timeout=.2, final_record=None):
        with self.close_guard:
            if self.close_thread is None:
                self.closing.set()
                self.close_thread = threading.Thread(target=self._close_file,
                    args=(final_record,), daemon=True)
                self.close_thread.start()
            thread = self.close_thread
        thread.join(timeout)

    def handleError(self, record):
        # Python logging swallows stream/rotation failures. Mark this record so
        # callers can count the failure without throwing into business code.
        record.runtime_write_failed = True
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

    def _record(self, line):
        now = time.time()
        record = {'time': now, 'timestamp': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  'message': line}
        return logging.makeLogRecord({'msg': json.dumps(record), 'levelno': logging.ERROR})

    def emit_line(self, line):
        self.output.handle(self._record(line))

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

    def close(self, timeout=.2):
        # A blocked stderr write can own this lock. Trailing data is best effort.
        final_record = None
        if self.lock.acquire(blocking=False):
            try:
                if self.buffer:
                    final_record = self._record(self.buffer)
                    self.buffer = ''
            finally:
                self.lock.release()
        self.output.close(timeout=timeout, final_record=final_record)

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
        record = logging.makeLogRecord({'msg': encoded, 'levelno': logging.INFO})
        self.events.handle(record)
        return not getattr(record, 'runtime_write_failed', False)

    def close(self, timeout=.2):
        deadline = time.monotonic() + timeout
        self.events.close(timeout=0)
        self.stderr.close(timeout=max(0, deadline - time.monotonic()))
        self.events.close(timeout=max(0, deadline - time.monotonic()))
