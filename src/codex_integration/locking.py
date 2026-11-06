"""Cross-process, reentrant local locks. Lock files are never unlinked."""


from infrastructure.locking import DirectoryLock


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
