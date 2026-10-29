"""Full CC snapshot replacement works without an open management page."""
from contextlib import closing
import json
import io
import contextlib
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gateway.server import route, sse_events
from management.service import Management, private_write
from desktop import service
import test_cc_model_identity as identity


class CCSyncTests(unittest.TestCase):
    def setUp(self):
        self.fixture = identity.CCModelIdentityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gateway = SimpleNamespace(settings=self.fixture.settings)
        self.path = self.fixture.root / 'settings.json'
        private_write(self.path, json.dumps(self.gateway.settings))
        self.manager = Management(self.gateway, self.path, route, sse_events)
        self.addCleanup(self.manager.stop_sync)

    def test_changed_model_ids_replace_directory_bindings_and_allowlist(self):
        old_key = self.fixture.key_for('model-a')
        self.fixture.write_provider(default=None, models=('model-b', 'model-c'))
        self.assertTrue(self.manager.sync_cc())
        settings = self.gateway.settings
        self.assertEqual(set(settings['cc_snapshot']['bindings']), {'record-a/model-b', 'record-a/model-c'})
        self.assertEqual(set(settings['models']), {'official', 'record-a/model-b'})
        self.assertIn('record-a/model-c', {model['key'] for model in self.manager.view()['models']})
        self.manager.save_models(self.manager.view()['source_id'], [{'key': 'record-a/model-c', 'added': True}])
        settings = self.gateway.settings
        self.assertNotIn(old_key, settings['models'])
        directory = json.loads(Path(settings['catalog']).read_text(encoding='utf-8'))
        self.assertEqual(settings['cc_snapshot']['models'], directory['models'])
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), settings)
        for model in ('model-b', 'model-c'):
            payload = route({'model': 'record-a/' + model, 'stream': True, 'input': []},
                            {'Authorization': 'Bearer subscription-test-only'}, settings)[1]
            self.assertEqual(payload['model'], model)

    def test_prepare_persists_the_same_explicit_bindings_as_the_published_directory(self):
        home = self.fixture.root / 'codex'
        home.mkdir()
        (home / 'config.toml').write_text('model = "official"\n', encoding='utf-8')
        (home / 'models_cache.json').write_text('{"models": [{"slug": "official"}]}', encoding='utf-8')
        runtime = self.fixture.root / 'prepared'
        with patch.object(service, 'RUNTIME', runtime), contextlib.redirect_stdout(io.StringIO()):
            service.prepare(18891, home, {'type': 'cc-switch', 'path': str(self.fixture.database)})
        settings = json.loads((runtime / 'settings.json').read_text(encoding='utf-8'))
        directory = json.loads((runtime / 'models.json').read_text(encoding='utf-8'))
        self.assertEqual(settings['cc_snapshot']['models'], directory['models'])
        self.assertEqual(set(settings['cc_snapshot']['bindings']), {'record-a/model-a', 'record-a/model-b'})

    def test_switching_to_independent_source_removes_cc_snapshot_and_stops_cc_updates(self):
        standalone = self.fixture.root / 'empty.yaml'
        standalone.write_text('version: 1\nproviders: {}\n', encoding='utf-8')
        self.manager.publish(source={'type': 'yaml', 'path': str(standalone)})
        self.assertNotIn('cc_snapshot', self.gateway.settings)
        self.fixture.write_provider(default=None, models=('new-cc-model',))
        self.assertFalse(self.manager.sync_cc())
        self.assertEqual(self.gateway.settings['models'], ['official'])

    def test_first_switch_to_independent_initializes_empty_config_and_replaces_cc_directory(self):
        standalone = self.fixture.root / 'models.yaml'
        self.gateway.settings['standalone_source'] = {'type': 'yaml', 'path': str(standalone)}
        self.assertFalse(standalone.exists())
        self.assertTrue(self.manager.set_source('independent')['saved'])
        self.assertTrue(standalone.is_file())
        self.assertEqual(self.gateway.settings['source']['path'], str(standalone))
        self.assertEqual(self.gateway.settings['models'], ['official'])
        self.assertNotIn('cc_snapshot', self.gateway.settings)
        self.assertEqual(self.manager.view()['models'], [])
        self.assertIsNone(self.manager.view()['source_error'])
        self.manager.set_source('cc_switch', str(self.fixture.database))
        self.assertEqual(set(self.gateway.settings['models']),
                         {'official', 'record-a/model-a', 'record-a/model-b'})

    def test_repeated_current_source_selection_does_not_publish_or_write_files(self):
        before = self.path.read_bytes()
        with patch.object(self.manager, 'publish', side_effect=AssertionError('unexpected publication')):
            self.assertTrue(self.manager.set_source('cc_switch')['unchanged'])
            self.assertTrue(self.manager.set_source('cc_switch', str(self.fixture.database))['unchanged'])
        self.assertEqual(self.path.read_bytes(), before)
        self.manager.set_source('independent')
        before = self.path.read_bytes()
        with patch.object(self.manager, 'publish', side_effect=AssertionError('unexpected publication')):
            self.assertTrue(self.manager.set_source('independent')['unchanged'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_changing_cc_database_path_while_cc_is_selected_still_replaces_the_source(self):
        database = self.fixture.root / 'other.db'
        with closing(sqlite3.connect(self.fixture.database)) as original, closing(sqlite3.connect(database)) as other:
            original.backup(other)
            other.execute('UPDATE providers SET id=?', ('record-b',))
            other.commit()
        self.assertTrue(self.manager.set_source('cc_switch', str(database))['saved'])
        self.assertEqual(self.gateway.settings['source']['path'], str(database))
        self.assertEqual(set(self.gateway.settings['models']),
                         {'official'})
        self.assertEqual(len(self.manager.view()['models']), 2)
        self.manager.save_models(self.manager.view()['source_id'], [{'key': 'record-b/model-a', 'added': True}])
        self.assertEqual(set(self.gateway.settings['models']), {'official', 'record-b/model-a'})

    def test_placeholder_missing_config_recovers_existing_managed_models(self):
        managed = self.fixture.root / 'managed-models.yaml'
        private_write(managed, json.dumps({'version': 1, 'providers': {'saved': {
            'base_url': 'https://saved.invalid/v1', 'protocol': 'openai_responses',
            'credentials': {'api_key': 'saved-key'}, 'models': {'exact': {'model_id': 'saved-model'}}}}}))
        self.gateway.settings['standalone_source'] = {
            'type': 'yaml', 'path': str(self.fixture.root/'models.yaml')}
        self.manager.set_source('independent')
        self.assertEqual(self.gateway.settings['source']['path'], str(managed))
        self.assertEqual(self.gateway.settings['models'], ['official'])
        self.assertEqual(self.manager.view()['models'][0]['key'], 'saved/exact')
        self.manager.save_models(self.manager.view()['source_id'], [{'key': 'saved/exact', 'added': True}])
        self.assertIn('saved/exact', self.gateway.settings['models'])
        self.assertEqual(self.manager.view()['credential_status'], {'saved': 'available'})

    def test_missing_explicit_independent_file_does_not_get_replaced_with_empty_config(self):
        missing = self.fixture.root / 'custom.yaml'
        self.gateway.settings['standalone_source'] = {'type': 'yaml', 'path': str(missing)}
        previous = self.gateway.settings
        with self.assertRaises(FileNotFoundError):
            self.manager.set_source('independent')
        self.assertIs(self.gateway.settings, previous)
        self.assertFalse(missing.exists())

    def test_deleting_all_records_clears_external_entries_and_keeps_official(self):
        with closing(sqlite3.connect(self.fixture.database)) as db:
            db.execute('DELETE FROM providers')
            db.commit()
        self.assertTrue(self.manager.sync_cc())
        self.assertEqual(self.gateway.settings['models'], ['official'])
        self.assertEqual(self.gateway.settings['cc_snapshot']['bindings'], {})

    def test_removing_all_models_from_a_record_clears_its_bindings(self):
        self.fixture.write_provider(default=None, models=())
        self.assertTrue(self.manager.sync_cc())
        self.assertEqual(self.gateway.settings['models'], ['official'])
        self.assertEqual(self.gateway.settings['cc_snapshot']['bindings'], {})

    def test_invalid_record_preserves_entire_previous_snapshot_and_retries(self):
        previous = self.path.read_bytes()
        directory = Path(self.gateway.settings['catalog']).read_bytes()
        self.fixture.write_provider(identifier='invalid-record')
        with closing(sqlite3.connect(self.fixture.database)) as db:
            db.execute('UPDATE providers SET settings_config=? WHERE id=?', ('{', 'invalid-record'))
            db.commit()
        self.assertFalse(self.manager.sync_cc())
        self.assertEqual(self.manager.sync_error, 'CC_CONFIG_INVALID')
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(Path(self.gateway.settings['catalog']).read_bytes(), directory)
        self.fixture.write_provider(identifier='invalid-record')
        self.assertTrue(self.manager.sync_cc())
        self.assertIsNone(self.manager.sync_error)
        self.assertNotIn('invalid-record/model-a', self.gateway.settings['models'])
        self.assertIn('invalid-record/model-a', {m['key'] for m in self.manager.view()['models']})

    def test_database_read_failure_preserves_snapshot(self):
        previous = self.path.read_bytes()
        with patch('model_catalog.cc_switch.connect', side_effect=sqlite3.OperationalError('locked')):
            self.assertFalse(self.manager.sync_cc())
        self.assertEqual(self.manager.sync_error, 'CC_DATABASE_UNAVAILABLE')
        self.assertEqual(self.path.read_bytes(), previous)

    def test_settings_write_failure_restores_directory_and_preserves_active_snapshot(self):
        previous = self.gateway.settings
        directory = Path(previous['catalog']).read_bytes()
        self.fixture.write_provider(default=None, models=('replacement',))

        def fail_settings(path, value):
            if Path(path) == self.path:
                raise OSError('write failed')
            return private_write(path, value)

        with patch('management.service.private_write', side_effect=fail_settings):
            self.assertFalse(self.manager.sync_cc())
        self.assertIs(self.gateway.settings, previous)
        self.assertEqual(Path(previous['catalog']).read_bytes(), directory)
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8')), previous)
        self.assertTrue(self.manager.sync_cc())

    def test_name_and_credentials_change_sync_without_duplicate_entries(self):
        original = set(self.gateway.settings['models'])
        self.fixture.write_provider(name='新名称', key='new-key')
        self.assertTrue(self.manager.sync_cc())
        self.assertEqual(set(self.gateway.settings['models']), original)
        external = [m for m in self.gateway.settings['cc_snapshot']['models'] if m['slug'] != 'official']
        self.assertTrue(all(m['display_name'].startswith('新名称 · ') for m in external))
        self.assertNotIn('new-key', self.path.read_text(encoding='utf-8'))
        self.assertFalse(self.manager.sync_cc())

    def test_background_sync_does_not_require_management_page_requests(self):
        synced = threading.Event()
        original_sync = self.manager.sync_cc

        def observe_sync():
            changed = original_sync()
            if changed:
                synced.set()
            return changed

        with patch.object(self.manager, 'sync_cc', side_effect=observe_sync):
            self.manager.start_sync(interval=0.02)
            self.fixture.write_provider(default=None, models=('background-model',))
            self.assertTrue(synced.wait(3), 'background sync did not publish the changed record')
            self.manager.stop_sync()
        self.assertEqual(self.gateway.settings['models'], ['official'])
        self.assertEqual(self.manager.view()['models'][0]['key'], 'record-a/background-model')

    def test_startup_repairs_directory_from_the_persisted_snapshot(self):
        path = Path(self.gateway.settings['catalog'])
        for contents in ('{"models": []}', '{', None):
            with self.subTest(contents=contents):
                if contents is None:
                    path.unlink()
                else:
                    path.write_text(contents, encoding='utf-8')
                self.assertTrue(self.manager.sync_cc())
                directory = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(directory['models'], self.gateway.settings['cc_snapshot']['models'])

    def test_sync_repairs_a_missing_binding_even_without_a_source_change(self):
        self.gateway.settings['cc_snapshot']['bindings'].pop('record-a/model-a')
        self.assertTrue(self.manager.sync_cc())
        self.assertEqual(self.gateway.settings['cc_snapshot']['bindings']['record-a/model-a'], {
            'provider_record_id': 'record-a', 'app_type': 'codex', 'model_id': 'model-a'})

    def test_page_uses_cache_without_database_reads_and_keeps_actual_sync_time(self):
        self.manager.sync_cc()
        before = self.manager.view()
        with patch('management.service.load_source', side_effect=AssertionError('page read database')), \
                patch('model_catalog.cc_switch.connect', side_effect=AssertionError('page read credentials')):
            self.assertEqual(self.manager.view(), before)
        self.manager.sync_cc()
        self.assertEqual(self.manager.last_synced_at, before['last_synced_at'])
        self.fixture.write_provider(name='Changed name')
        self.manager.sync_cc()
        self.assertNotEqual(self.manager.view()['sync_revision'], before['sync_revision'])
        self.assertGreaterEqual(self.manager.last_synced_at, before['last_synced_at'])

    def test_wal_notification_syncs_without_periodic_reads(self):
        with closing(sqlite3.connect(self.fixture.database)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            ready = threading.Event()
            changed = threading.Event()
            original = self.manager.sync_cc

            def observe():
                result = original()
                if self.manager.sync_mode == 'watch':
                    ready.set()
                if result:
                    changed.set()
                return result

            with patch.object(self.manager, 'sync_cc', side_effect=observe) as sync:
                self.manager.start_sync(interval=30)
                self.assertTrue(ready.wait(3), 'directory watcher did not start')
                calls = sync.call_count
                self.assertFalse(changed.wait(0.6))
                self.assertEqual(sync.call_count, calls, 'idle watcher polled the database')
                db.execute("UPDATE providers SET name='WAL update'")
                db.commit()
                self.assertTrue(changed.wait(3), 'WAL commit did not trigger synchronization')
                self.manager.stop_sync()
            self.assertTrue(self.manager.view()['inventory'][0]['name'].startswith('WAL update'))

    def test_unavailable_watcher_uses_periodic_fallback(self):
        changed = threading.Event()
        original = self.manager.sync_cc

        def observe():
            if original():
                changed.set()

        with patch('management.cc_watch.CCWatch.start', side_effect=OSError('unavailable')), \
                patch.object(self.manager, 'sync_cc', side_effect=observe):
            self.manager.start_sync(interval=0.05)
            self.fixture.write_provider(name='Fallback update')
            self.assertTrue(changed.wait(3))
            self.assertEqual(self.manager.sync_mode, 'periodic')
            self.manager.stop_sync()
