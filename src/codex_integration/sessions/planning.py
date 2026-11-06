"""Read-only migration plans and confirmed index completion."""
import contextlib
import json
import logging
from pathlib import Path
import re
import sqlite3
import time

from model_catalog.catalog import ConfigError

from codex_integration.sessions.inventory import (
    _resolved, _database, _rows, _rollout_paths, _row_path, _session_id, _inventory, sha,
)


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
    from infrastructure.runtime_log import handler
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
    from codex_integration.sessions.index import repair_index
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
