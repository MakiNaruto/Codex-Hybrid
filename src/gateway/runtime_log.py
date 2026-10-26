"""Size-limited local runtime logs shared by foreground and background starts."""
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import threading


LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 3


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

    def write(self, value):
        with self.lock:
            self.buffer += value
            while '\n' in self.buffer or len(self.buffer) >= 8192:
                end = self.buffer.find('\n')
                end = min(end, 8192) if end >= 0 else 8192
                line, self.buffer = self.buffer[:end], self.buffer[end + (self.buffer[end:end+1] == '\n'):]
                self.output.handle(logging.makeLogRecord({'msg': line, 'levelno': logging.ERROR}))
        return len(value)

    def flush(self):
        with self.lock:
            if self.buffer:
                self.output.handle(logging.makeLogRecord({'msg': self.buffer, 'levelno': logging.ERROR}))
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
        encoded = json.dumps(observation)
        if len(encoded.encode('utf-8')) > 16384:
            # An unusually large tool list must not defeat the per-file limit.
            compact = {'record_truncated': True}
            for key in ('time', 'status', 'phase', 'request_id', 'http_status', 'elapsed_ms', 'error_kind'):
                value = observation.get(key)
                if type(value) in (int, float, bool) or value is None:
                    compact[key] = value
                elif isinstance(value, str):
                    compact[key] = value[:128]
            encoded = json.dumps(compact)
        self.events.handle(logging.makeLogRecord({'msg': encoded, 'levelno': logging.INFO}))

    def close(self):
        self.stderr.flush()
        self.events.close()
        self.errors.close()
