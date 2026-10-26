"""In-memory request counts, without retaining request content or history."""
import threading
import time


class Activity:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0

    def begin(self):
        with self.lock:
            self.active += 1

    def end(self):
        with self.lock:
            self.active -= 1

    def snapshot(self):
        with self.lock:
            return {'active_requests': self.active, 'observed_at': time.time(),
                    'gateway_status': 'busy' if self.active else 'no_activity',
                    'codex_status': 'unknown'}
