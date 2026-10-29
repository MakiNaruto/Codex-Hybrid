"""Exclusive database locks must not leave baseline or transaction backups waiting forever."""
import contextlib
import sqlite3
import threading
import unittest
from unittest.mock import patch

from desktop import session_migration as migration
import test_session_migration as fixtures


class BackupDeadlineTests(unittest.TestCase):
    setUp = fixtures.SessionMigrationTests.setUp
    session = fixtures.SessionMigrationTests.session
    rows = fixtures.SessionMigrationTests.rows

    def test_baseline_backup_times_out_without_publishing_and_can_retry(self):
        self.session('one')
        state = migration.plan(self.home, self.settings, 'openai')
        done, errors = threading.Event(), []
        with contextlib.closing(sqlite3.connect(self.database)) as blocker:
            blocker.execute('BEGIN EXCLUSIVE')
            def backup():
                try:
                    migration._ensure_baseline(state, self.runtime, {})
                except Exception as error:
                    errors.append(error)
                finally:
                    done.set()
            with patch.object(migration, 'BACKUP_TIMEOUT', .15, create=True):
                thread = threading.Thread(target=backup, daemon=True)
                thread.start()
                try:
                    self.assertTrue(done.wait(1), 'Baseline backup ignored its deadline')
                    self.assertEqual([error.code for error in errors], ['SESSION_BACKUP_TIMEOUT'])
                    baseline, marker = migration._baseline_paths(self.home, self.runtime)
                    self.assertFalse(baseline.exists())
                    self.assertFalse(marker.exists())
                finally:
                    blocker.rollback()
                    thread.join(3)
        baseline = migration._ensure_baseline(state, self.runtime, {})
        self.assertTrue((baseline/'state.sqlite').is_file())

    def test_transaction_backup_times_out_before_changing_indexes(self):
        self.session('one')
        state = migration.plan(self.home, self.settings, 'openai')
        before = self.rows()
        done, entered = threading.Event(), threading.Event()
        blockers, errors = [], []
        complete = migration._complete_indexes
        def hold_after_index_completion(*args):
            result = complete(*args)
            blocker = sqlite3.connect(self.database, check_same_thread=False)
            blocker.execute('BEGIN EXCLUSIVE')
            blockers.append(blocker)
            entered.set()
            return result
        def apply():
            try:
                migration.apply(state, self.runtime, {})
            except Exception as error:
                errors.append(error)
            finally:
                done.set()
        with patch.object(migration, 'BACKUP_TIMEOUT', .15, create=True), \
                patch.object(migration, '_complete_indexes', side_effect=hold_after_index_completion):
            thread = threading.Thread(target=apply, daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(done.wait(1), 'Transaction backup ignored its deadline')
                self.assertEqual([error.code for error in errors], ['SESSION_BACKUP_TIMEOUT'])
            finally:
                for blocker in blockers:
                    blocker.rollback()
                    blocker.close()
                thread.join(3)
        self.assertEqual(self.rows(), before)
        self.assertEqual(list((self.runtime/'session-migrations').iterdir()), [])

    def test_short_lock_can_clear_before_deadline(self):
        self.session('one')
        state = migration.plan(self.home, self.settings, 'openai')
        done, errors = threading.Event(), []
        with contextlib.closing(sqlite3.connect(self.database)) as blocker:
            blocker.execute('BEGIN EXCLUSIVE')
            def backup():
                try:
                    migration._ensure_baseline(state, self.runtime, {})
                except Exception as error:
                    errors.append(error)
                finally:
                    done.set()
            with patch.object(migration, 'BACKUP_TIMEOUT', 2):
                thread = threading.Thread(target=backup, daemon=True)
                thread.start()
                try:
                    self.assertFalse(done.wait(.1))
                finally:
                    blocker.rollback()
                    thread.join(3)
        self.assertTrue(done.is_set())
        self.assertEqual(errors, [])
        _, marker = migration._baseline_paths(self.home, self.runtime)
        self.assertTrue(marker.exists())

    def test_wal_backup_includes_committed_uncheckpointed_rows(self):
        self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute("UPDATE threads SET model='wal-committed'")
            writer.commit()
            state = migration.plan(self.home, self.settings, 'openai')
            baseline = migration._ensure_baseline(state, self.runtime, {})
            with contextlib.closing(sqlite3.connect(baseline/'state.sqlite')) as saved:
                self.assertEqual(saved.execute('SELECT model FROM threads').fetchone()[0], 'wal-committed')
