"""Durable baseline capture and atomic migration commit with rollback."""
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import time

from model_catalog.catalog import ConfigError

from infrastructure.files import sync_directory as _sync_directory
from infrastructure.files import write_durable_bytes as write
from codex_integration.sessions import inventory, recovery
from codex_integration.sessions.inventory import _row_path, _rows, sha
from codex_integration.sessions.planning import plan, _complete_indexes

BACKUP_TIMEOUT = 5


def _backup_database(source, destination):
    # sqlite3's connection timeout does not bound backup()'s SQLITE_BUSY retries.
    deadline = time.monotonic() + BACKUP_TIMEOUT
    previous_timeout = source.execute('PRAGMA busy_timeout').fetchone()[0]
    source.execute('PRAGMA busy_timeout=50')
    def progress(status, remaining, total):
        if time.monotonic() >= deadline:
            raise ConfigError('SESSION_BACKUP_TIMEOUT')
    try:
        source.backup(destination, pages=128, progress=progress, sleep=.05)
    finally:
        source.execute(f'PRAGMA busy_timeout={previous_timeout}')


def _official_history_repairs(migration):
    """Rule greeting-message-id-v1: strip local text-message IDs when restoring OpenAI history."""
    originals, changes, repairs = {}, {}, []
    if migration['provider'] != 'openai' or migration.get('skip_sessions'):
        return originals, changes, repairs
    for row in migration['local_rows']:
        path = _row_path(row)
        if not path.is_file() or path.name.endswith('.zst'):
            continue
        before = path.read_bytes()
        lines = before.splitlines(keepends=True)
        count = 0
        for index, line in enumerate(lines):
            try:
                record = json.loads(line)
                item = record.get('payload', {})
                # Only the ChatAdapter-generated identity shape verified in the
                # greeting incident. Native UUID message IDs remain untouched.
                if (record.get('type') != 'response_item' or item.get('type') != 'message'
                        or item.get('role') != 'assistant'
                        or not re.fullmatch(r'msg_[0-9a-f]{32}', item.get('id') or '')
                        or not item.get('content')
                        or not all(p.get('type') == 'output_text' and isinstance(p.get('text'), str)
                                   for p in item['content'])):
                    continue
                del item['id']
                ending = b'\r\n' if line.endswith(b'\r\n') else b'\n' if line.endswith(b'\n') else b''
                lines[index] = json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode() + ending
                count += 1
            except (ValueError, AttributeError, TypeError):
                raise ConfigError('SESSION_HISTORY_INVALID') from None
        if count:
            originals[path] = before
            changes[path] = b''.join(lines)
            repairs.append({'rule': 'greeting-message-id-v1', 'thread_id': row[0],
                            'path': str(path), 'items': count,
                            'before_sha256': sha(before), 'after_sha256': sha(changes[path])})
    return originals, changes, repairs


def _baseline_paths(home, directory):
    key = sha(str(Path(home).resolve()).encode())[:24]
    root = Path(directory) / 'session-baselines'
    return root / key, root / (key + '.json')


def _ensure_baseline(migration, directory, originals):
    baseline, marker = _baseline_paths(migration['home'], directory)
    if marker.exists():
        try:
            hashes = json.loads(marker.read_text())['hashes']
            if (not isinstance(hashes, dict) or 'manifest.json' not in hashes
                    or any(not isinstance(name, str) or Path(name).name != name
                           or sha((baseline / name).read_bytes()) != digest
                           for name, digest in hashes.items())):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise ConfigError('SESSION_BASELINE_UNAVAILABLE') from None
        return baseline
    # An orphaned directory may be a partially published first backup. Never
    # silently bless it or replace a previously established baseline.
    if baseline.exists():
        raise ConfigError('SESSION_BASELINE_UNAVAILABLE')
    staging = baseline.with_name(baseline.name + '.preparing')
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, mode=0o700)
    info = {'status': 'baseline', 'home': str(migration['home']),
            'database': str(migration['database']) if migration['database'] else None,
            'history_compatibility': migration.get('baseline_history_repairs', []), 'files': []}
    database = migration['database']
    if database:
        with contextlib.closing(sqlite3.connect(database)) as db:
            with contextlib.closing(sqlite3.connect(staging / 'state.sqlite')) as saved:
                _backup_database(db, saved)
        os.chmod(staging / 'state.sqlite', 0o600)
    for i, (path, before) in enumerate(originals.items()):
        name = str(i) + '.backup' if before is not None else None
        if name:
            write(staging / name, before)
        info['files'].append({'path': str(path), 'backup': name})
    write(staging / 'manifest.json', json.dumps(info).encode())
    hashes = {p.name: sha(p.read_bytes()) for p in staging.iterdir()}
    for path in staging.iterdir():
        # Windows _commit (os.fsync) requires a writable descriptor. Reopen
        # without truncation so SQLite backups and manifests remain intact.
        with path.open('r+b') as stream:
            os.fsync(stream.fileno())
    _sync_directory(staging)
    staging.rename(baseline)
    _sync_directory(baseline.parent)
    write(marker, json.dumps({'home': str(migration['home']), 'hashes': hashes}).encode())
    return baseline


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
        inventory.assert_stopped(home)
    root = Path(directory) / 'session-migrations'
    recovery._check_records(directory)
    if plan(migration['home'], migration['settings'], migration['provider'],
            best_effort=migration.get('skip_sessions', False))['revision'] != migration['revision']:
        raise ConfigError('SESSION_MIGRATION_CHANGED')
    history_originals, history_changes, history_repairs = _official_history_repairs(migration)
    if history_changes and allow_running:
        # Index-only operations may opt out of stopping Codex; history cannot.
        inventory.assert_stopped(home)
    originals.update(history_originals)
    changes.update(history_changes)
    # Capture before app-server index completion, which itself mutates SQLite.
    initial_rows = any(before != after for before, after in
                       zip(migration['rows'], migration.get('rows_after', [])))
    if not changes and not initial_rows and not migration.get('unindexed'):
        return None
    for path, before in originals.items():
        if (path.read_bytes() if path.exists() else None) != before:
            raise ConfigError('SESSION_MIGRATION_CHANGED')
    if migration['database'] and not migration.get('skip_sessions'):
        with contextlib.closing(sqlite3.connect(migration['database'])) as check:
            if _rows(check) != migration['rows']:
                raise ConfigError('SESSION_MIGRATION_CHANGED')
    migration['baseline_history_repairs'] = history_repairs
    baseline = _ensure_baseline(migration, directory, originals)
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
                'index_only': not bool(history_changes), 'provider': migration['provider'], 'files': [],
                'history_compatibility': history_repairs,
                'rollout_paths': [entry[0] for entry in migration.get('inventory', [])],
                'rollout_inventory': migration.get('inventory', []),
                'rows_before': migration['rows'],
                'rows_after': migration.get('rows_after', [])}
    write(backup / 'manifest.json', json.dumps(manifest).encode())
    try:
        if database:
            db = sqlite3.connect(database, timeout=2)
            # A coherent backup must precede the write transaction (backup on a
            # connection holding BEGIN IMMEDIATE would block).
            with contextlib.closing(sqlite3.connect(backup / 'state.sqlite')) as saved:
                _backup_database(db, saved)
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
            inventory.assert_stopped(home)
        if history_changes and allow_running:
            inventory.assert_stopped(home)
        for p, after in changes.items():
            if (p.read_bytes() if p.exists() else None) != originals[p]:
                raise ConfigError('SESSION_MIGRATION_CHANGED')
            written.append(p)
            write(p, after)
        if db:
            db.executemany('UPDATE threads SET model_provider=?, model=? WHERE id=?',
                           [(row[2], row[3], row[0]) for row in row_changes])
            db.commit()
            committed = True
        manifest['status'] = 'complete'
        write(backup / 'manifest.json', json.dumps(manifest).encode())
    except BaseException:
        if manifest['status'] == 'complete':
            manifest['status'] = 'applying'
            write(backup / 'manifest.json', json.dumps(manifest).encode())
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
            manifest['status'] = 'rolled_back'
            write(backup / 'manifest.json', json.dumps(manifest).encode())
        if db:
            db.close()
            db = None
        recovery._cleanup_record(backup)
        raise
    finally:
        if db:
            db.close()
    recovery._cleanup_record(backup)
    return str(baseline)
