"""Lock-owning public session migration operations."""
import json
from pathlib import Path
import shutil

from codex_integration.locking import DirectoryLock
from codex_integration.sessions import inventory, transaction, recovery
from codex_integration.sessions.inventory import assert_stopped
from codex_integration.sessions.planning import plan, log_warnings
from model_catalog.catalog import ConfigError


def apply(migration, directory, extra_files, *, allow_running=False):
    """Commit under the runtime and Codex-home locks in this fixed order."""
    with DirectoryLock(directory), DirectoryLock(migration['home'], '.codex-hybrid.lock'):
        return transaction._apply_locked(migration, directory, extra_files, allow_running=allow_running)


def cleanup_completed_records(directory):
    with DirectoryLock(directory):
        recovery._cleanup_completed_records_locked(directory)


def reset_baseline(home, directory):
    """Discard an unusable baseline while preserving marker publication order."""
    with DirectoryLock(directory), DirectoryLock(home, '.codex-hybrid.lock'):
        inventory.assert_stopped(home)
        recovery._check_records(directory)
        baseline, marker = transaction._baseline_paths(home, directory)
        if baseline.exists():
            shutil.rmtree(baseline)
        marker.unlink(missing_ok=True)


def recover(backup):
    """Recover an interrupted transaction after rechecking its journal under both locks."""
    backup = Path(backup).resolve()
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'applying':
        raise ConfigError('SESSION_MIGRATION_NOT_INTERRUPTED')
    with DirectoryLock(backup.parent.parent), DirectoryLock(manifest['home'], '.codex-hybrid.lock'):
        # Another caller may have recovered and removed this journal while we waited.
        manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['status'] != 'applying':
            raise ConfigError('SESSION_MIGRATION_NOT_INTERRUPTED')
        return recovery._recover_locked(backup, manifest)
