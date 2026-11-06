"""Lifecycle of CC Switch notifications and periodic reconciliation."""
import threading
import time

from infrastructure.errors import ConfigError


class CCSyncWatcher:
    def __init__(self, context, lock, reconcile):
        self.context = context
        self.lock = lock
        self.reconcile = reconcile
        self.stop_event = threading.Event()
        self.thread = None
        self.mode = 'periodic'

    def start(self, interval):
        self.thread = threading.Thread(target=self.watch, args=(interval,), name='cc-switch-sync', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def watch(self, interval):
        from management.cc_watch import CCWatch
        watcher = None
        watched_path = None
        next_check = time.monotonic() + interval
        try:
            while not self.stop_event.wait(min(0.1, interval)):
                try:
                    with self.lock:
                        source = self.context.settings['source']
                        path = source['path'] if source['type'] == 'cc-switch' else None
                    due = time.monotonic() >= next_check
                    if path != watched_path or (path and watcher is None and due):
                        if watcher is not None:
                            watcher.stop()
                        watcher = None
                        watched_path = path
                        self.mode = 'periodic'
                        if path:
                            candidate = CCWatch(path)
                            try:
                                candidate.start()
                            except (ImportError, OSError, RuntimeError):
                                pass  # Keep the periodic safety net if notifications are unavailable.
                            else:
                                watcher = candidate
                                self.mode = 'watch'
                        due = True  # Reconcile changes between startup/source switch and registration.
                    if due or (watcher is not None and watcher.ready()):
                        self.reconcile()
                        next_check = time.monotonic() + interval
                except ConfigError as error:
                    if error.code != 'INSTANCE_BUSY':
                        raise
                    # A CLI transaction owns the data briefly; keep watching after it ends.
                    continue
        finally:
            if watcher is not None:
                watcher.stop()
            self.mode = 'periodic'
