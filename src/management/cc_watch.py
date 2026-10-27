"""Directory notifications for SQLite, including WAL commits and atomic replacement."""
import os
from pathlib import Path
import threading
import time


class CCWatch:
    def __init__(self, path, debounce=0.3):
        self.path = Path(path).expanduser().resolve()
        self.targets = {os.path.normcase(str(self.path) + suffix) for suffix in ('', '-wal')}
        self.debounce = debounce
        self.lock = threading.Lock()
        self.changed_at = None
        self.observer = None

    def on_event(self, event):
        if event.is_directory or event.event_type not in {'created', 'modified', 'deleted', 'moved'}:
            return
        paths = (event.src_path, getattr(event, 'dest_path', ''))
        if any(os.path.normcase(os.path.abspath(path)) in self.targets for path in paths if path):
            with self.lock:
                self.changed_at = time.monotonic()

    def ready(self):
        with self.lock:
            if self.changed_at is None or time.monotonic() - self.changed_at < self.debounce:
                return False
            self.changed_at = None
            return True

    def start(self):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
        handler = FileSystemEventHandler()
        handler.on_any_event = self.on_event
        observer = Observer()
        observer.schedule(handler, str(self.path.parent), recursive=False)
        try:
            observer.start()
        except Exception:
            observer.stop()
            if observer.is_alive():
                observer.join(timeout=5)
            raise
        self.observer = observer

    def stop(self):
        if self.observer is not None:
            self.observer.stop()
            self.observer.join(timeout=5)
