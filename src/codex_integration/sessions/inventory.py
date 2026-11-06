"""Read-only session metadata and process checks."""
import hashlib
import json
import os
from pathlib import Path

from model_catalog.catalog import ConfigError


def _zstd():
    # Python 3.14 includes Zstandard; older supported Python versions use the
    # dependency, only when a nonstandard compressed filename needs metadata.
    try:
        from compression import zstd
        return zstd
    except ImportError:
        import zstandard
        return zstandard


def _session_id(path):
    """Read only metadata for unindexed nonstandard filenames, never history."""
    try:
        if path.name.endswith('.zst'):
            codec = _zstd()
            try:
                with codec.open(path, 'rb') as stream:
                    line = stream.readline(8 * 1024 * 1024)
            except codec.ZstdError:
                raise ConfigError('SESSION_HISTORY_INVALID') from None
        else:
            with path.open('rb') as stream:
                line = stream.readline(8 * 1024 * 1024)
        header = json.loads(line)
        identifier = header['payload']['id']
        if header['type'] != 'session_meta' or not isinstance(identifier, str) or not identifier:
            raise ValueError()
        return identifier
    except (OSError, ValueError, KeyError, EOFError):
        raise ConfigError('SESSION_HISTORY_INVALID') from None


def _inventory(paths):
    result = []
    for path in sorted(paths):
        status = path.stat()
        result.append((str(path), status.st_size, status.st_mtime_ns))
    return result


def _resolved(path):
    """Compare Windows extended-length and ordinary paths as the same location."""
    def strip_prefix(value):
        if os.name == 'nt':
            if value[:8].lower() == '\\\\?\\unc\\':
                return '\\\\' + value[8:]
            if value.startswith('\\\\?\\'):
                return value[4:]
        return value
    return Path(strip_prefix(str(Path(strip_prefix(str(path))).resolve())))


def _row_path(row):
    path = Path(row[1])
    compressed = path.with_name(path.name + '.zst')
    # Codex can keep the original .jsonl name in its index after compression.
    if not path.is_file() and path.suffix == '.jsonl' and compressed.is_file():
        return compressed
    return path


def _rollout_paths(home, rows=()):
    paths = {_resolved(p) for folder in ('sessions', 'archived_sessions')
             for p in (home / folder).rglob('*.jsonl*')
             if p.name.endswith(('.jsonl', '.jsonl.zst'))}
    paths |= {_resolved(_row_path(row)) for row in rows
              if row[1] and _resolved(row[1]).is_relative_to(home) and _row_path(row).is_file()}
    if any(not p.is_relative_to(home) for p in paths):
        raise ConfigError('SESSION_PATH_UNSAFE')
    return paths


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _assert_stopped(home):
    from codex_integration.process_state import codex_process_state
    status = codex_process_state(home)['status']
    if status == 'running':
        raise ConfigError('SESSION_MIGRATION_CODEX_RUNNING')
    if status == 'unknown':
        raise ConfigError('SESSION_MIGRATION_PROCESS_CHECK_FAILED')


def assert_stopped(home):
    import psutil
    try:
        _assert_stopped(home)
    except (OSError, psutil.Error):
        raise ConfigError('SESSION_MIGRATION_PROCESS_CHECK_FAILED') from None


def _database(home):
    databases = list(Path(home).glob('state_*.sqlite'))
    if len(databases) > 1:
        raise ConfigError('SESSION_DATABASE_AMBIGUOUS')
    if databases and databases[0].is_symlink():
        raise ConfigError('SESSION_PATH_UNSAFE')
    return databases[0] if databases else None


def _rows(connection):
    columns = {row[1] for row in connection.execute('PRAGMA table_info(threads)')}
    if not {'id', 'rollout_path', 'model_provider', 'model'} <= columns:
        raise ConfigError('SESSION_DATABASE_UNSUPPORTED')
    return list(connection.execute('SELECT id, rollout_path, model_provider, model FROM threads ORDER BY id'))
