"""Cross-process, reentrant local locks. Lock files are never unlinked."""
import errno
import os
from pathlib import Path
import threading

from model_catalog.catalog import ConfigError

_registry = {}
_registry_guard = threading.Lock()


class DirectoryLock:
    def __init__(self, directory, name='operation.lock', code='INSTANCE_BUSY'):
        self.path = Path(directory).resolve() / name
        self.code = code
        with _registry_guard:
            self.state = _registry.setdefault(str(self.path), {
                'lock': threading.RLock(), 'depth': 0, 'fd': None})

    def __enter__(self):
        state = self.state
        state['lock'].acquire()
        try:
            if not state['depth']:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
                fd = os.open(self.path, flags, 0o600)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        if os.fstat(fd).st_size == 0:
                            os.write(fd, b'\0')
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    os.close(fd)
                    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise ConfigError(self.code) from None
                    raise
                state['fd'] = fd
            state['depth'] += 1
            return self
        except BaseException:
            state['lock'].release()
            raise

    def __exit__(self, *exc):
        state = self.state
        try:
            state['depth'] -= 1
            if not state['depth']:
                fd, state['fd'] = state['fd'], None
                try:
                    if os.name == 'nt':
                        import msvcrt
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
        finally:
            state['lock'].release()


class ConfigurationLock:
    """Serialize managers and CLI; refresh a snapshot changed by another process."""
    def __init__(self, manager):
        self.manager = manager
        self.directory_lock = DirectoryLock(manager.directory)
        # Create the stable inode up front, not during an otherwise read-only preview.
        with self.directory_lock:
            self.last = self._read()
        self.depth = 0

    def _read(self):
        try:
            return self.manager.settings_path.read_bytes()
        except FileNotFoundError:
            return None

    def __enter__(self):
        self.directory_lock.__enter__()
        try:
            if not self.depth:
                raw = self._read()
                if raw is not None and raw != self.last:
                    import json
                    self.manager.gateway.settings = json.loads(raw)
                self.last = raw
            self.depth += 1
            return self
        except BaseException:
            self.directory_lock.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        try:
            self.depth -= 1
            if not self.depth:
                self.last = self._read()
        finally:
            self.directory_lock.__exit__(*exc)
