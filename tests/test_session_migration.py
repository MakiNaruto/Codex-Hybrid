import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from desktop.session_migration import apply, assert_stopped, plan, recover
from model_catalog.catalog import ConfigError


class SessionMigrationTests(unittest.TestCase):
    def setUp(self):
        processes = patch('psutil.process_iter', return_value=[])
        processes.start()
        self.addCleanup(processes.stop)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'codex 中文 space'
        self.home.mkdir()
        self.runtime = Path(self.temp.name) / 'runtime'
        self.settings = {'catalog': str(self.home / 'catalog.json'),
                         'official_models': ['gpt-6.1-sol', 'gpt-6-astra'],
                         'models': ['gpt-6.1-sol', 'vendor/model', 'gpt-6-astra']}
        (self.home / 'catalog.json').write_text(json.dumps({'models': [
            {'slug': 'hidden', 'visibility': 'hide'}, {'slug': 'gpt-6.1-sol'},
            {'slug': 'vendor/model'}, {'slug': 'gpt-6-astra'}]}))
        self.database = self.home / 'state_5.sqlite'
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, model_provider TEXT, model TEXT)')
        self.stopped = patch('desktop.session_migration.assert_stopped')
        self.stopped.start()
        self.addCleanup(self.stopped.stop)

    def session(self, name, provider='old', archived=False, base=None, model='vendor/model'):
        folder = 'archived_sessions' if archived else 'sessions/2026/10/27'
        path = self.home / folder / (name + '.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'id': name, 'model_provider': provider, 'history_mode': 'paginated'}
        if base:
            payload['history_base'] = base
        header = {'type': 'session_meta', 'payload': payload}
        context = {'type': 'turn_context', 'payload': {'model': 'vendor/model', 'effort': 'low'}}
        # User/tool content must never be rewritten, even when it mentions routing fields.
        user = {'type': 'response_item', 'payload': {'role': 'user', 'content': 'model_provider old vendor/model 中文'}}
        path.write_bytes(b''.join(json.dumps(r, ensure_ascii=False).encode() + b'\r\n' for r in [header, context, user]))
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO threads VALUES (?,?,?,?)', (name, str(path), provider, model))
        return path

    def rows(self):
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            return db.execute('SELECT id,model_provider,model FROM threads ORDER BY id').fetchall()

    def management(self, native='model_provider = "openai"\nmodel = "gpt-6.1-sol"\n'):
        from desktop.service import candidate_config, digest
        from management.service import Management
        self.runtime.mkdir(exist_ok=True)
        self.settings.update(port=18891, local_token='test-token')
        config = self.home/'config.toml'
        candidate = candidate_config(native, self.settings)
        config.write_bytes(native.encode('utf-8'))
        (self.runtime/'original-config.toml').write_bytes(native.encode('utf-8'))
        (self.runtime/'desktop-config.toml').write_bytes(candidate.encode('utf-8'))
        (self.runtime/'settings.json').write_text(json.dumps(self.settings))
        state = {'config_path': str(config), 'original_sha256': digest(native.encode()),
                 'candidate_sha256': digest(candidate.encode()), 'activated': False}
        (self.runtime/'state.json').write_text(json.dumps(state))
        return Management(SimpleNamespace(settings=self.settings), self.runtime/'settings.json', None, None)

    def test_enable_preserves_every_model_and_all_history_bytes(self):
        for name, model in [('official', 'gpt-6-astra'), ('third-party', 'vendor/model'),
                            ('retired', 'retired-model'), ('unset', None)]:
            self.session(name, model=model)
        histories = {p: p.read_bytes() for p in self.home.rglob('*.jsonl')}
        before = self.rows()
        migration = plan(self.home, self.settings, 'codex-hybrid')
        apply(migration, self.runtime, {})
        self.assertEqual(self.rows(), [(r[0], 'codex-hybrid', r[2]) for r in before])
        self.assertEqual(histories, {p: p.read_bytes() for p in histories})
        self.assertEqual(migration['model_change_count'], 0)

    def test_disable_only_replaces_nonofficial_current_models(self):
        for name, model in [('official', 'gpt-6-astra'), ('third-party', 'vendor/model'),
                            ('misleading', 'gpt-third-party'), ('unset', None)]:
            self.session(name, model=model)
        migration = plan(self.home, self.settings, 'openai')
        apply(migration, self.runtime, {})
        self.assertEqual(self.rows(), [('misleading', 'openai', 'gpt-6.1-sol'),
                                      ('official', 'openai', 'gpt-6-astra'),
                                      ('third-party', 'openai', 'gpt-6.1-sol'), ('unset', 'openai', None)])
        self.assertEqual(migration['model_change_count'], 2)

    def test_fallback_uses_official_catalog_order_and_ignores_old_presets(self):
        self.session('one')
        self.settings['official_models'].reverse()
        self.settings['session_default_models'] = {'openai': 'gpt-6-astra'}
        migration = plan(self.home, self.settings, 'openai')
        self.assertEqual(migration['fallback_model'], 'gpt-6.1-sol')

    def test_hidden_official_model_is_retained(self):
        self.session('one', model='gpt-6-astra')
        (self.home/'catalog.json').write_bytes(b'{"models":[]}')
        apply(plan(self.home, self.settings, 'openai'), self.runtime, {})
        self.assertEqual(self.rows(), [('one', 'openai', 'gpt-6-astra')])

    def test_no_available_official_fallback_blocks_before_writes(self):
        path = self.session('one')
        before = path.read_bytes(), self.database.read_bytes()
        (self.home/'catalog.json').write_bytes(b'{"models":[]}')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MODEL_LIST_EMPTY'):
            plan(self.home, self.settings, 'openai', best_effort=True)
        self.assertEqual(before, (path.read_bytes(), self.database.read_bytes()))
        # Enabling does not need an available model or a default model.
        apply(plan(self.home, self.settings, 'codex-hybrid'), self.runtime, {})

    def test_unknown_official_list_is_not_treated_as_a_mixed_list(self):
        self.session('one')
        self.settings.pop('official_models')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MODEL_LIST_EMPTY'):
            plan(self.home, self.settings, 'openai')

    def test_preview_is_read_only_even_when_indexes_are_missing(self):
        path = self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM threads')
        before = path.read_bytes(), self.database.read_bytes()
        with patch('desktop.codex_index.repair_index') as repair:
            migration = plan(self.home, self.settings, 'openai')
        repair.assert_not_called()
        self.assertEqual(migration['unindexed'], ['one'])
        self.assertEqual(before, (path.read_bytes(), self.database.read_bytes()))

    def test_codex_repairs_missing_index_before_index_only_migration(self):
        path = self.session('one')
        before = path.read_bytes()
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM threads')
        migration = plan(self.home, self.settings, 'openai')
        def repair(home, ids, executable):
            self.assertEqual(ids, ['one'])
            with contextlib.closing(sqlite3.connect(self.database)) as db, db:
                db.execute('INSERT INTO threads VALUES (?,?,?,?)', ('one', str(path), 'old', 'vendor/model'))
        with patch('desktop.codex_index.repair_index', side_effect=repair):
            backup = Path(apply(migration, self.runtime, {}))
        self.assertEqual(self.rows(), [('one', 'openai', 'gpt-6.1-sol')])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(migration['index_repair_count'], 1)
        saved = json.loads((backup/'manifest.json').read_bytes())
        self.assertEqual(saved['rows_before'][0][2:], ['old', 'vendor/model'])
        self.assertTrue(saved['index_only'])
        self.assertEqual(saved['files'], [])

    def test_incomplete_index_repair_does_not_switch_config(self):
        self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM threads')
        manager = self.management()
        preview = manager.preview_routing('project')
        with patch('desktop.codex_index.repair_index'):
            with self.assertRaisesRegex(ConfigError, 'SESSION_INDEX_REPAIR_INCOMPLETE'):
                manager.set_routing('project', preview['revision'])
        self.assertEqual(manager.routing_state(), 'openai')
        self.assertEqual(self.rows(), [])

    def test_failed_index_repair_does_not_switch_config(self):
        self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM threads')
        migration = plan(self.home, self.settings, 'openai')
        with patch('desktop.codex_index.repair_index', side_effect=ConfigError('SESSION_INDEX_REPAIR_FAILED')):
            with self.assertRaisesRegex(ConfigError, 'SESSION_INDEX_REPAIR_FAILED'):
                apply(migration, self.runtime, {})
        self.assertFalse(self.runtime.exists())

    def test_stale_index_or_history_blocks_changes(self):
        path = self.session('one')
        migration = plan(self.home, self.settings, 'openai')
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            apply(migration, self.runtime, {})
        migration = plan(self.home, self.settings, 'openai')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE threads SET model="new-user-choice"')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            apply(migration, self.runtime, {})
        self.assertEqual(self.rows()[0][2], 'new-user-choice')

    def test_catalog_change_invalidates_preview(self):
        self.session('one')
        migration = plan(self.home, self.settings, 'openai')
        (self.home/'catalog.json').write_bytes(b'{"models":[{"slug":"gpt-6-astra"}]}')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            apply(migration, self.runtime, {})
        self.assertEqual(self.rows()[0][1], 'old')

    def test_missing_history_sources_and_invalid_offsets_are_not_rewritten(self):
        path = self.session('child', base={'thread_id': 'missing', 'end_byte_offset': -1})
        before = path.read_bytes()
        migration = plan(self.home, self.settings, 'openai', best_effort=True)
        self.assertEqual(migration['warnings'], [])
        apply(migration, self.runtime, {})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.rows()[0][1:], ('openai', 'gpt-6.1-sol'))

    def test_compressed_archived_and_segmented_history_remains_opaque(self):
        root_id = '00000000-0000-0000-0000-000000000001'
        path = self.session(root_id, archived=True)
        compressed = path.with_suffix('.jsonl.zst')
        # Indexed history is opaque to the migration, including compression and
        # content validity. Codex owns reading and validating it.
        compressed.write_bytes(b'opaque compressed history')
        path.unlink()
        segment = compressed.with_name('rollout-'+root_id+'_00000000-0000-0000-0000-000000000002.jsonl')
        segment.write_bytes(b'opaque immutable segment')
        histories = {p: p.read_bytes() for p in (compressed, segment)}
        migration = plan(self.home, self.settings, 'openai')
        self.assertEqual(migration['unindexed'], [])
        self.assertEqual(migration['count'], 1)
        self.assertEqual(migration['missing_rollouts'], 0)
        with patch('desktop.codex_index.repair_index') as repair:
            apply(migration, self.runtime, {})
        repair.assert_not_called()
        self.assertEqual(histories, {p: p.read_bytes() for p in histories})

    def test_cloud_and_other_home_rows_are_not_migrated(self):
        self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.executemany('INSERT INTO threads VALUES (?,?,?,?)', [
                ('cloud', '', 'remote', 'cloud-model'),
                ('other', str(self.home.parent/'elsewhere.jsonl'), 'remote', 'other-model')])
        apply(plan(self.home, self.settings, 'openai'), self.runtime, {})
        self.assertEqual(self.rows(), [('cloud', 'remote', 'cloud-model'), ('one', 'openai', 'gpt-6.1-sol'),
                                      ('other', 'remote', 'other-model')])

    def test_index_with_missing_history_is_updated_without_creating_history(self):
        missing = self.home/'sessions/gone.jsonl'
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO threads VALUES (?,?,?,?)', ('gone', str(missing), 'old', 'vendor/model'))
        migration = plan(self.home, self.settings, 'openai')
        self.assertEqual(migration['missing_rollouts'], 1)
        apply(migration, self.runtime, {})
        self.assertFalse(missing.exists())
        self.assertEqual(self.rows(), [('gone', 'openai', 'gpt-6.1-sol')])

    def test_confirmation_does_not_bypass_running_or_changed_checks(self):
        path = self.session('one')
        migration = plan(self.home, self.settings, 'openai')
        with patch('desktop.session_migration.assert_stopped', side_effect=ConfigError('SESSION_MIGRATION_CODEX_RUNNING')):
            with self.assertRaises(ConfigError):
                apply(migration, self.runtime, {})
            apply(migration, self.runtime, {}, allow_running=True)
        migration = plan(self.home, self.settings, 'codex-hybrid')
        path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            apply(migration, self.runtime, {}, allow_running=True)

    def test_commit_marker_failure_restores_index_and_config(self):
        path = self.session('one')
        history = path.read_bytes()
        config = self.home/'config.toml'
        config.write_bytes(b'model = "user-selected"\n')
        before = config.read_bytes()
        migration = plan(self.home, self.settings, 'openai')
        from desktop.session_migration import write
        def fail_marker(p, data):
            if p.name == 'manifest.json' and json.loads(data)['status'] == 'complete':
                raise OSError('commit marker failed')
            write(p, data)
        with patch('desktop.session_migration.write', side_effect=fail_marker):
            with self.assertRaises(OSError):
                apply(migration, self.runtime, {config: (before, before+b'model_provider = "openai"\n')})
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(path.read_bytes(), history)
        self.assertEqual(self.rows()[0][1:], ('old', 'vendor/model'))

    def test_interrupted_index_only_migration_can_be_recovered(self):
        path = self.session('one')
        before = path.read_bytes()
        backup = Path(apply(plan(self.home, self.settings, 'openai'), self.runtime, {}))
        manifest = json.loads((backup/'manifest.json').read_bytes())
        manifest['status'] = 'applying'
        (backup/'manifest.json').write_bytes(json.dumps(manifest).encode())
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_RECOVERY_REQUIRED'):
            apply(plan(self.home, self.settings, 'codex-hybrid'), self.runtime, {})
        recover(backup)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.rows()[0][1:], ('old', 'vendor/model'))

    def test_recovery_preserves_titles_and_rejects_new_history(self):
        path = self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('ALTER TABLE threads ADD COLUMN title TEXT')
            db.execute('UPDATE threads SET title="before"')
        backup = Path(apply(plan(self.home, self.settings, 'openai'), self.runtime, {}))
        manifest = json.loads((backup/'manifest.json').read_bytes())
        manifest['status'] = 'applying'
        (backup/'manifest.json').write_bytes(json.dumps(manifest).encode())
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE threads SET title="after"')
        recover(backup)
        with contextlib.closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT title FROM threads').fetchone()[0], 'after')
        manifest['status'] = 'applying'
        (backup/'manifest.json').write_bytes(json.dumps(manifest).encode())
        path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            recover(backup)

    def test_legacy_interrupted_backup_remains_recoverable(self):
        path = self.session('one')
        original = path.read_bytes()
        backup = Path(apply(plan(self.home, self.settings, 'openai'), self.runtime, {}))
        manifest = json.loads((backup/'manifest.json').read_bytes())
        manifest.pop('index_only')
        manifest.pop('rollout_inventory')
        manifest['status'] = 'applying'
        (backup/'history.backup').write_bytes(original)
        path.write_bytes(original + b'\n')
        from desktop.session_migration import sha
        manifest['files'].append({'path': str(path), 'backup': 'history.backup',
                                  'after_sha256': sha(path.read_bytes())})
        (backup/'manifest.json').write_bytes(json.dumps(manifest).encode())
        recover(backup)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.rows()[0][1], 'old')

    def test_management_roundtrip_preserves_model_configuration_and_history(self):
        path = self.session('one')
        before = path.read_bytes()
        manager = self.management('model = "my-config-model"\r\n[profiles.work]\r\nmodel = "profile-model"\r\n')
        import tomllib
        for mode, expected in [('project', 'vendor/model'), ('openai', 'gpt-6.1-sol')]:
            preview = manager.preview_routing(mode)
            result = manager.set_routing(mode, preview['revision'])
            self.assertEqual(self.rows()[0][2], expected)
            config = tomllib.loads((self.home/'config.toml').read_text(encoding='utf-8'))
            self.assertEqual(config['model'], 'my-config-model')
            self.assertEqual(config['profiles']['work']['model'], 'profile-model')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result['session_count'], 1)

    def test_empty_home_does_not_insert_default_model(self):
        manager = self.management('[features]\nexample = true\n')
        for mode in ('project', 'openai'):
            preview = manager.preview_routing(mode)
            manager.set_routing(mode, preview['revision'])
            import tomllib
            self.assertNotIn('model', tomllib.loads((self.home/'config.toml').read_text(encoding='utf-8')))

    def test_cli_activate_rollback_uninstall_preserve_model_and_history(self):
        from desktop import service
        path = self.session('one')
        before = path.read_bytes()
        self.management('# 用户配置\r\nmodel = "my-config-model"\r\n')
        for action, provider, model in [('activate', 'codex-hybrid', 'vendor/model'),
                                        ('rollback', 'openai', 'gpt-6.1-sol'),
                                        ('uninstall', 'openai', 'gpt-6.1-sol')]:
            with patch('sys.argv', ['codex-hybrid', action, '--data-dir', str(self.runtime)]), \
                    patch.object(service, 'RUNTIME', self.runtime), patch.object(service, 'health'), \
                    patch.object(service, 'stop_service'), contextlib.redirect_stdout(io.StringIO()):
                service.main()
            self.assertEqual(self.rows(), [('one', provider, model)])
            self.assertIn('model = "my-config-model"', (self.home/'config.toml').read_text(encoding='utf-8'))
            self.assertEqual(path.read_bytes(), before)

    def test_process_detection_blocks_matching_home_only(self):
        process = SimpleNamespace(pid=-1, info={'name': 'codex', 'cmdline': ['codex', 'app-server']},
                                  environ=lambda: {'CODEX_HOME': str(self.home)})
        with patch('psutil.process_iter', return_value=[process]):
            with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CODEX_RUNNING'):
                assert_stopped(self.home)
            assert_stopped(self.home/'different')

    def test_cli_old_snapshot_does_not_restore_a_previous_default_model(self):
        from desktop.service import retain_config_model
        import tomllib
        for current in (b'model = "new-user-choice"\n', b'# no default model\n'):
            target = b'model = "old-default"\nmodel_provider = "openai"\n'
            result = tomllib.loads(retain_config_model(target, current).decode())
            self.assertEqual(result.get('model'), tomllib.loads(current.decode()).get('model'))
            self.assertEqual(result['model_provider'], 'openai')

    @unittest.skipUnless(os.name == 'nt', 'Windows extended-length paths')
    def test_windows_extended_paths_are_local_without_rewriting_the_path(self):
        path = self.session('one')
        extended = '\\\\?\\' + str(path.resolve())
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE threads SET rollout_path=?', (extended,))
        migration = plan(self.home, self.settings, 'openai')
        self.assertEqual(migration['count'], 1)
        self.assertEqual(migration['unindexed'], [])
        apply(migration, self.runtime, {})
        with contextlib.closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT rollout_path FROM threads').fetchone()[0], extended)
        self.assertEqual(self.rows()[0][1:], ('openai', 'gpt-6.1-sol'))
