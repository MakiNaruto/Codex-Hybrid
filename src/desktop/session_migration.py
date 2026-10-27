"""Recoverable index-only migration, preserving rollout bytes and config models."""
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

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


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out:
            out.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _assert_stopped(home):
    from desktop.process_state import codex_process_state
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


def _official_models(home, settings):
    official = settings.get('official_models')
    if not isinstance(official, list) or not official:
        raise ConfigError('SESSION_MODEL_LIST_EMPTY')
    catalog = Path(settings.get('catalog', Path(home) / 'models_cache.json'))
    if catalog.is_file():
        entries = json.loads(catalog.read_text(encoding='utf-8'))['models']
        visible = [m['slug'] for m in entries if m['slug'] in official and m.get('visibility') != 'hide']
    else:
        visible = list(official)
    return set(official), visible


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


def plan(home, settings, provider, *, best_effort=False):
    """Preview index changes only. Codex repairs missing indexes after confirmation."""
    try:
        migration = _plan(home, settings, provider)
        migration['warnings'] = []
        return migration
    except ConfigError as error:
        if not best_effort or error.code not in {
            'SESSION_HISTORY_INVALID',
            'SESSION_ID_AMBIGUOUS', 'SESSION_DATABASE_AMBIGUOUS',
            'SESSION_DATABASE_UNSUPPORTED', 'SESSION_PATH_UNSAFE',
        }:
            raise
        reason = error.code
        details = getattr(error, 'details', {})
    home = _resolved(home)
    warning = {'code': reason, 'action': 'sessions_unchanged', **details,
               'message': '会话迁移预检失败，已跳过全部旧会话迁移；接入配置仍可切换。旧会话保留原线路和模型。'}
    revision = sha(json.dumps([str(home), provider, warning], sort_keys=True).encode())
    return {'home': home, 'provider': provider, 'fallback_model': None, 'database': None,
            'rows': [], 'local_rows': [], 'originals': {}, 'changes': {},
            'revision': revision, 'count': 0, 'missing_rollouts': 0, 'unindexed': [],
            'model_change_count': 0, 'index_repair_count': 0, 'settings': dict(settings),
            'skip_sessions': True, 'warnings': [warning]}


def log_warnings(migration, directory):
    """Use the runtime log's bounded private handler; never include chat content."""
    if not migration.get('warnings'):
        return None
    from gateway.runtime_log import handler
    path = Path(directory) / 'session-migration-warnings.jsonl'
    try:
        output = handler(path)
        failures = []
        output.handleError = lambda record: failures.append(True)
        try:
            for warning in migration['warnings']:
                record = dict(warning, time=int(time.time()), home=str(migration['home']),
                              provider=migration['provider'])
                output.handle(logging.makeLogRecord({
                    'msg': json.dumps(record, ensure_ascii=False), 'levelno': logging.WARNING}))
        finally:
            output.close()
        if failures:
            return None
    except OSError:
        # The warning still reaches the caller when the log directory is unwritable.
        return None
    return str(path)


def _plan(home, settings, provider):
    home = _resolved(home)
    database = _database(home)
    rows = []
    if database:
        with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            rows = _rows(db)
    # Cloud/other-home entries do not participate in this local migration.
    local_rows = [row for row in rows if row[1] and _resolved(row[1]).is_relative_to(home)]
    paths = _rollout_paths(home, local_rows)
    indexed_paths = {_resolved(_row_path(row)): row[0] for row in local_rows}
    identifiers = set()
    for path in paths:
        identifier = indexed_paths.get(path)
        if identifier is None:
            match = re.search(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', path.name)
            identifier = match[0] if match else _session_id(path)
        identifiers.add(identifier)
    local_ids = {row[0] for row in local_rows}
    if (identifiers - local_ids) & {row[0] for row in rows}:
        raise ConfigError('SESSION_ID_AMBIGUOUS')
    unindexed = sorted(identifiers - local_ids)
    fallback = None
    official, visible = set(), []
    if provider == 'openai' and (unindexed or any(row[3] for row in local_rows)):
        official, visible = _official_models(home, settings)
    needs_fallback = provider == 'openai' and any(row[3] and row[3] not in official for row in local_rows)
    if needs_fallback or (provider == 'openai' and unindexed):
        if not visible:
            raise ConfigError('SESSION_MODEL_LIST_EMPTY')
        fallback = visible[0]
    after = []
    for row in rows:
        if row[0] in local_ids:
            model = fallback if provider == 'openai' and row[3] and row[3] not in official else row[3]
            after.append((row[0], row[1], provider, model))
        else:
            after.append(row)
    inventory = _inventory(paths)
    revision = sha(json.dumps([provider, rows, after, unindexed, inventory, sorted(official), visible],
                              sort_keys=True).encode())
    return {'home': home, 'provider': provider, 'fallback_model': fallback, 'database': database,
            'rows': rows, 'rows_after': after, 'local_rows': local_rows, 'unindexed': unindexed,
            'originals': {}, 'changes': {}, 'inventory': inventory, 'settings': dict(settings),
            'revision': revision, 'count': len(local_rows) + len(unindexed),
            'model_change_count': sum(a[3] != b[3] for a, b in zip(rows, after)),
            'index_repair_count': 0,
            'missing_rollouts': sum(not _row_path(row).is_file() for row in local_rows)}


def _complete_indexes(migration):
    if migration.get('skip_sessions'):
        return
    current = _plan(migration['home'], migration['settings'], migration['provider'])
    if current['revision'] != migration['revision']:
        raise ConfigError('SESSION_MIGRATION_CHANGED')
    if not migration['unindexed']:
        return
    from desktop.codex_index import repair_index
    repair_index(migration['home'], migration['unindexed'], migration['settings'].get('codex_executable'))
    complete = _plan(migration['home'], migration['settings'], migration['provider'])
    before = {row[0]: row for row in migration['rows']}
    after = {row[0]: row for row in complete['rows']}
    if (complete['unindexed'] or not set(migration['unindexed']) <= {row[0] for row in complete['local_rows']}):
        raise ConfigError('SESSION_INDEX_REPAIR_INCOMPLETE')
    if (complete['inventory'] != migration['inventory'] or any(after.get(key) != row for key, row in before.items())
            or set(after) - set(before) != set(migration['unindexed'])):
        raise ConfigError('SESSION_MIGRATION_CHANGED')
    complete['warnings'] = migration['warnings']
    complete['index_repair_count'] = len(migration['unindexed'])
    migration.update(complete)


def apply(migration, directory, extra_files, *, allow_running=False):
    """Back up first; leave an explicit recovery journal if interrupted mid-write."""
    from desktop.locking import DirectoryLock
    with DirectoryLock(migration['home'], '.codex-hybrid.lock'):
        return _apply_locked(migration, directory, extra_files, allow_running=allow_running)


def _apply_locked(migration, directory, extra_files, *, allow_running=False):
    home = migration['home']
    originals = dict(migration['originals'])
    changes = dict(migration['changes'])
    for path, (before, after) in extra_files.items():
        path = Path(path)
        originals[path] = before
        if before != after:
            changes[path] = after
    if migration['count'] and not allow_running:
        assert_stopped(home)
    root = Path(directory) / 'session-migrations'
    if root.exists():
        for manifest in root.glob('*/manifest.json'):
            if json.loads(manifest.read_text(encoding='utf-8')).get('status') == 'applying':
                raise ConfigError('SESSION_MIGRATION_RECOVERY_REQUIRED')
    _complete_indexes(migration)
    row_changes = [after for before, after in zip(migration['rows'], migration.get('rows_after', [])) if before != after]
    if not changes and not row_changes:
        return None
    backup = root / secrets.token_hex(12)
    backup.mkdir(parents=True, mode=0o700)
    db = None
    committed = False
    written = []
    database = migration['database']
    manifest = {'status': 'preparing', 'home': str(home), 'database': str(database) if database else None,
                'skip_sessions': migration.get('skip_sessions', False),
                'warnings': migration.get('warnings', []),
                'index_only': True, 'provider': migration['provider'], 'files': [],
                'rollout_paths': [entry[0] for entry in migration.get('inventory', [])],
                'rollout_inventory': migration.get('inventory', []),
                'rows_before': migration['rows'],
                'rows_after': migration.get('rows_after', [])}
    try:
        if database:
            db = sqlite3.connect(database, timeout=2)
            # A coherent backup must precede the write transaction (backup on a
            # connection holding BEGIN IMMEDIATE would block).
            with contextlib.closing(sqlite3.connect(backup / 'state.sqlite')) as saved:
                db.backup(saved)
            os.chmod(backup / 'state.sqlite', 0o600)
            db.execute('BEGIN IMMEDIATE')
            if _rows(db) != migration['rows']:
                raise ConfigError('SESSION_MIGRATION_CHANGED')
        for p, before in originals.items():
            if (p.read_bytes() if p.exists() else None) != before:
                raise ConfigError('SESSION_MIGRATION_CHANGED')
        for i, (p, after) in enumerate(changes.items()):
            before = originals[p]
            name = str(i) + '.backup'
            if before is not None:
                write(backup / name, before)
            manifest['files'].append({'path': str(p), 'backup': name if before is not None else None,
                                      'after_sha256': sha(after)})
        manifest['status'] = 'applying'
        write(backup / 'manifest.json', json.dumps(manifest).encode())
        if migration['count'] and not allow_running:
            assert_stopped(home)
        for p, after in changes.items():
            if (p.read_bytes() if p.exists() else None) != originals[p]:
                raise ConfigError('SESSION_MIGRATION_CHANGED')
            write(p, after)
            written.append(p)
        if db:
            db.executemany('UPDATE threads SET model_provider=?, model=? WHERE id=?',
                           [(row[2], row[3], row[0]) for row in row_changes])
            db.commit()
            committed = True
        manifest['status'] = 'complete'
        write(backup / 'manifest.json', json.dumps(manifest).encode())
    except BaseException:
        if db:
            db.rollback()
        if committed:
            db.executemany('UPDATE threads SET model_provider=?, model=? WHERE id=?',
                           [(r[2], r[3], r[0]) for r in migration['local_rows']])
            db.commit()
        for item in manifest['files']:
            p = Path(item['path'])
            if p not in written:
                continue
            if item['backup']:
                write(p, (backup / item['backup']).read_bytes())
            else:
                p.unlink(missing_ok=True)
        if (backup / 'manifest.json').exists():
            manifest['status'] = 'failed'
            write(backup / 'manifest.json', json.dumps(manifest).encode())
        raise
    finally:
        if db:
            db.close()
    return str(backup)


def recover(backup):
    """Recover an interrupted transaction, before opening Codex again."""
    backup = Path(backup).resolve()
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'applying':
        raise ConfigError('SESSION_MIGRATION_NOT_INTERRUPTED')
    from desktop.locking import DirectoryLock
    with DirectoryLock(manifest['home'], '.codex-hybrid.lock'):
        return _recover_locked(backup, manifest)


def _recover_locked(backup, manifest):
    assert_stopped(Path(manifest['home']))
    home = Path(manifest['home'])
    paths = _rollout_paths(home, manifest['rows_before'])
    if not manifest.get('skip_sessions') and sorted(str(p) for p in paths) != manifest['rollout_paths']:
        raise ConfigError('SESSION_MIGRATION_CHANGED')
    if manifest.get('index_only') and not manifest.get('skip_sessions'):
        if [list(entry) for entry in _inventory(paths)] != manifest['rollout_inventory']:
            raise ConfigError('SESSION_MIGRATION_CHANGED')
    if manifest['database']:
        with contextlib.closing(sqlite3.connect(Path(manifest['database']).as_uri() + '?mode=ro', uri=True)) as db:
            rows = [list(r) for r in _rows(db)]
            if rows not in [manifest['rows_before'], manifest['rows_after']]:
                raise ConfigError('SESSION_MIGRATION_CHANGED')
    for item in manifest['files']:
        p = Path(item['path'])
        before = (backup / item['backup']).read_bytes() if item['backup'] else None
        current = p.read_bytes() if p.exists() else None
        if current != before and (current is None or sha(current) != item['after_sha256']):
            raise ConfigError('SESSION_MIGRATION_CHANGED')
    if manifest['database']:
        with contextlib.closing(sqlite3.connect(manifest['database'])) as db:
            db.execute('BEGIN IMMEDIATE')
            rows = [list(r) for r in _rows(db)]
            if rows not in [manifest['rows_before'], manifest['rows_after']]:
                raise ConfigError('SESSION_MIGRATION_CHANGED')
            # Restore only fields owned by this migration; keep unrelated DB
            # tables, titles, timestamps and other metadata intact.
            db.executemany('UPDATE threads SET model_provider=?, model=? WHERE id=?',
                           [(r[2], r[3], r[0]) for r in manifest['rows_before']])
            db.commit()
    for item in manifest['files']:
        p = Path(item['path'])
        if item['backup']:
            write(p, (backup / item['backup']).read_bytes())
        else:
            p.unlink(missing_ok=True)
    manifest['status'] = 'recovered'
    write(backup / 'manifest.json', json.dumps(manifest).encode())
