"""Offline, recoverable migration of local Codex session routing metadata."""
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tomllib
import time

from model_catalog.catalog import ConfigError


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


def select_model(home, settings, provider, requested=None):
    """Preserve catalog order; explicit defaults must belong to the target list."""
    requested = requested if requested is not None else settings.get('session_default_models', {}).get(provider)
    if requested is not None and (not isinstance(requested, str) or not requested.strip()):
        raise ConfigError('SESSION_DEFAULT_MODEL_INVALID')
    models = []
    catalog_path = Path(settings.get('catalog', Path(home) / 'models_cache.json'))
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding='utf-8'))['models']
        allowed = settings.get('official_models') if provider == 'openai' else settings.get('models')
        models = [m['slug'] for m in catalog if m.get('visibility') != 'hide'
                  and (allowed is None or m['slug'] in allowed)]
    if not catalog_path.is_file():
        models = list(settings.get('official_models' if provider == 'openai' else 'models', []))
    if not models:
        raise ConfigError('SESSION_MODEL_LIST_EMPTY')
    if requested is not None and requested not in models:
        raise ConfigError('SESSION_DEFAULT_MODEL_INVALID')
    return requested if requested is not None else models[0]


def config_model(text, model):
    if model is None:
        return text
    boundary = re.search(r'^\s*\[', text, re.MULTILINE)
    root, tables = (text[:boundary.start()], text[boundary.start():]) if boundary else (text, '')
    root = re.sub(r'^model\s*=.*(?:\n|$)', '', root, flags=re.MULTILINE)
    result = 'model = ' + json.dumps(model) + '\n' + root + tables
    before, after = tomllib.loads(text), tomllib.loads(result)
    before['model'] = model
    if before != after:
        raise ConfigError('CLIENT_CONFIG_REWRITE_UNSAFE')
    return result


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


def plan(home, settings, provider, requested=None, *, best_effort=False):
    """Optionally leave all history untouched when its preflight is unsafe.

    Never suppress model selection, config validation or commit failures. History
    segments share byte offsets, so a failed plan must be skipped as a whole.
    """
    try:
        migration = _plan(home, settings, provider, requested)
        migration['warnings'] = []
        return migration
    except ConfigError as error:
        if not best_effort or error.code not in {
            'SESSION_HISTORY_SOURCE_MISSING', 'SESSION_HISTORY_INVALID',
            'SESSION_HISTORY_CYCLE', 'SESSION_HISTORY_OFFSET_INVALID',
            'SESSION_ID_AMBIGUOUS', 'SESSION_DATABASE_AMBIGUOUS',
            'SESSION_DATABASE_UNSUPPORTED', 'SESSION_PATH_UNSAFE',
        }:
            raise
        reason = error.code
        details = getattr(error, 'details', {})
    home = Path(home).resolve()
    model = select_model(home, settings, provider, requested)
    warning = {'code': reason, 'action': 'sessions_unchanged', **details,
               'message': '会话迁移预检失败，已跳过全部旧会话迁移；接入配置仍可切换。旧会话保留原线路和模型。'}
    revision = sha(json.dumps([str(home), provider, model, warning], sort_keys=True).encode())
    return {'home': home, 'provider': provider, 'model': model, 'database': None,
            'rows': [], 'local_rows': [], 'originals': {}, 'changes': {},
            'revision': revision, 'count': 0, 'missing_rollouts': 0,
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


def _plan(home, settings, provider, requested=None):
    home = Path(home).resolve()
    paths = sorted({p.resolve() for folder in ('sessions', 'archived_sessions')
                    for p in (home / folder).rglob('*.jsonl')})
    if any(not p.is_relative_to(home) for p in paths):
        raise ConfigError('SESSION_PATH_UNSAFE')
    database = _database(home)
    rows = []
    if database:
        with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            rows = _rows(db)
    # Cloud sessions have no local rollout and are deliberately outside this migration.
    local_rows = [row for row in rows if row[1] and Path(row[1]).resolve().is_relative_to(home)]
    missing = [r for r in local_rows if not Path(r[1]).is_file()]
    paths = sorted(set(paths) | {Path(row[1]).resolve() for row in local_rows if Path(row[1]).is_file()})
    needs_model = paths or local_rows or requested is not None or settings.get('models') or settings.get('official_models')
    model = select_model(home, settings, provider, requested) if needs_model else None
    originals = {p: p.read_bytes() for p in paths}
    records, ids = {}, {}
    for p, data in originals.items():
        try:
            lines = data.splitlines(keepends=True)
            header = json.loads(lines[0])
            if header['type'] != 'session_meta':
                raise ValueError()
            # Newer Codex stores multiple immutable rollout segments for one
            # logical thread. history_base refers to the filename's segment ID,
            # not necessarily session_meta.id or threads.id.
            segment = re.search(r'([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\.jsonl$', p.name)
            segment_id = segment[1] if segment else header['payload']['id']
            if segment_id in ids and ids[segment_id] != p:
                raise ConfigError('SESSION_ID_AMBIGUOUS')
            ids[segment_id] = p
            records[p] = [(line, json.loads(line)) for line in lines]
        except ConfigError:
            raise
        except (ValueError, KeyError, IndexError):
            raise ConfigError('SESSION_HISTORY_INVALID') from None
    rendered, boundaries, visiting = {}, {}, set()

    def render(p):
        if p in rendered:
            return
        if p in visiting:
            raise ConfigError('SESSION_HISTORY_CYCLE')
        visiting.add(p)
        old_offset = new_offset = 0
        offsets = {0: 0}
        output = []
        for raw, record in records[p]:
            changed = False
            payload = record.get('payload', {})
            if record.get('type') == 'session_meta':
                if payload.get('model_provider') != provider:
                    payload['model_provider'] = provider
                    changed = True
                base = payload.get('history_base')
                if base is not None:
                    source = ids.get(base.get('thread_id'))
                    if source is None:
                        error = ConfigError('SESSION_HISTORY_SOURCE_MISSING')
                        error.details = {'file': str(p), 'source_id': base.get('thread_id')}
                        raise error
                    render(source)
                    old_end = base['end_byte_offset']
                    if old_end not in boundaries[source]:
                        raise ConfigError('SESSION_HISTORY_OFFSET_INVALID')
                    end = boundaries[source][old_end]
                    if end != old_end:
                        base['end_byte_offset'] = end
                        changed = True
            elif record.get('type') == 'turn_context' and payload.get('model') != model:
                payload['model'] = model
                changed = True
            if changed:
                ending = b'\r\n' if raw.endswith(b'\r\n') else b'\n' if raw.endswith(b'\n') else b''
                raw_new = json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode() + ending
            else:
                raw_new = raw
            output.append(raw_new)
            old_offset += len(raw)
            new_offset += len(raw_new)
            offsets[old_offset] = new_offset
        rendered[p] = b''.join(output)
        boundaries[p] = offsets
        visiting.remove(p)

    for p in paths:
        render(p)
    changes = {p: data for p, data in rendered.items() if data != originals[p]}
    fingerprint = sha(json.dumps([provider, model, rows, [(str(p), sha(originals[p])) for p in paths]],
                                sort_keys=True).encode())
    return {'home': home, 'provider': provider, 'model': model, 'database': database,
            'rows': rows, 'local_rows': local_rows, 'originals': originals,
            'changes': changes, 'revision': fingerprint, 'count': len(paths) + len(missing),
            'missing_rollouts': len(missing)}


def apply(migration, directory, extra_files, *, allow_running=False):
    """Back up first; leave an explicit recovery journal if interrupted mid-write."""
    home = migration['home']
    originals = dict(migration['originals'])
    changes = dict(migration['changes'])
    for path, (before, after) in extra_files.items():
        path = Path(path)
        originals[path] = before
        if before != after:
            changes[path] = after
    if not changes and not migration['local_rows']:
        return None
    if migration['count'] and not allow_running:
        assert_stopped(home)
    root = Path(directory) / 'session-migrations'
    if root.exists():
        for manifest in root.glob('*/manifest.json'):
            if json.loads(manifest.read_text()).get('status') == 'applying':
                raise ConfigError('SESSION_MIGRATION_RECOVERY_REQUIRED')
    if not migration.get('skip_sessions'):
        current_paths = {p.resolve() for folder in ('sessions', 'archived_sessions')
                         for p in (home / folder).rglob('*.jsonl')}
        current_paths |= {Path(r[1]).resolve() for r in migration['local_rows'] if Path(r[1]).is_file()}
        if current_paths != set(migration['originals']) or _database(home) != migration['database']:
            raise ConfigError('SESSION_MIGRATION_CHANGED')
    backup = root / secrets.token_hex(12)
    backup.mkdir(parents=True, mode=0o700)
    db = None
    committed = False
    written = []
    database = migration['database']
    manifest = {'status': 'preparing', 'home': str(home), 'database': str(database) if database else None,
                'skip_sessions': migration.get('skip_sessions', False),
                'warnings': migration.get('warnings', []),
                'provider': migration['provider'], 'model': migration['model'], 'files': [],
                'rollout_paths': sorted(str(p) for p in migration['originals']),
                'rows_before': migration['rows'],
                'rows_after': [(r[0], r[1], migration['provider'], migration['model'])
                               if r in migration['local_rows'] else r for r in migration['rows']]}
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
                           [(migration['provider'], migration['model'], row[0]) for row in migration['local_rows']])
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
    manifest = json.loads((backup / 'manifest.json').read_text())
    if manifest['status'] != 'applying':
        raise ConfigError('SESSION_MIGRATION_NOT_INTERRUPTED')
    assert_stopped(Path(manifest['home']))
    home = Path(manifest['home'])
    paths = {p.resolve() for folder in ('sessions', 'archived_sessions')
             for p in (home / folder).rglob('*.jsonl')}
    paths |= {Path(r[1]).resolve() for r in manifest['rows_before']
              if r[1] and Path(r[1]).is_file() and Path(r[1]).resolve().is_relative_to(home)}
    if not manifest.get('skip_sessions') and sorted(str(p) for p in paths) != manifest['rollout_paths']:
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
