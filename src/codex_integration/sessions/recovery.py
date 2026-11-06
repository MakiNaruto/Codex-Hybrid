"""Interrupted transaction recovery and retryable journal cleanup."""
import contextlib
import json
import logging
from pathlib import Path
import shutil
import sqlite3

from model_catalog.catalog import ConfigError

from infrastructure.files import write_durable_bytes as write
from codex_integration.sessions import inventory
from codex_integration.sessions.inventory import _rollout_paths, _inventory, _rows, sha


def _cleanup_record(path):
    try:
        # Keep the terminal manifest until all payloads are gone. A partial
        # deletion must remain recognizable and retryable on the next start.
        for child in path.iterdir():
            if child.name == 'manifest.json':
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        (path / 'manifest.json').unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        logging.warning('Migration cleanup deferred: %s', path)


def _cleanup_completed_records_locked(directory):
    from codex_integration.locking import DirectoryLock
    root = Path(directory) / 'session-migrations'
    if not root.exists():
        return
    for record in root.iterdir():
        if not record.is_dir():
            continue
        try:
            if not any(record.iterdir()):
                _cleanup_record(record)
                continue
            manifest = json.loads((record / 'manifest.json').read_text())
            if manifest['status'] not in ('complete', 'rolled_back', 'recovered'):
                continue
            with DirectoryLock(manifest['home'], '.codex-hybrid.lock'):
                current = json.loads((record / 'manifest.json').read_text())
                if current['status'] in ('complete', 'rolled_back', 'recovered'):
                    _cleanup_record(record)
        except (OSError, ValueError, KeyError):
            logging.warning('Migration cleanup deferred: %s', record)


def _check_records(directory):
    root = Path(directory) / 'session-migrations'
    if root.exists():
        for record in root.iterdir():
            if not record.is_dir():
                continue
            if not any(record.iterdir()):
                _cleanup_record(record)
                continue
            try:
                status = json.loads((record / 'manifest.json').read_text())['status']
            except (OSError, ValueError, KeyError):
                raise ConfigError('SESSION_MIGRATION_RECOVERY_REQUIRED') from None
            if status in ('preparing', 'complete', 'rolled_back', 'recovered'):
                _cleanup_record(record)
            else:
                raise ConfigError('SESSION_MIGRATION_RECOVERY_REQUIRED')


def _recoverable_rows(rows, manifest):
    before = {row[0]: row for row in manifest['rows_before']}
    after = {row[0]: row for row in manifest['rows_after']}
    return (len(rows) == len(before) and
            all(row == before.get(row[0]) or row == after.get(row[0]) for row in rows))


def _recover_locked(backup, manifest):
    inventory.assert_stopped(Path(manifest['home']))
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
            if not _recoverable_rows(rows, manifest):
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
            if not _recoverable_rows(rows, manifest):
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
    _cleanup_record(backup)
