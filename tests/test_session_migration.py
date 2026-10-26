import contextlib
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop.session_migration import apply, assert_stopped, config_model, plan, recover, select_model
from model_catalog.catalog import ConfigError


class SessionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'codex'
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

    def session(self, name, provider='old', archived=False, base=None):
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
            db.execute('INSERT INTO threads VALUES (?,?,?,?)', (name, str(path), provider, 'vendor/model'))
        return path

    def rows(self):
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            return db.execute('SELECT id,model_provider,model FROM threads ORDER BY id').fetchall()

    def test_default_order_and_explicit_target_validation(self):
        self.assertEqual(select_model(self.home, self.settings, 'openai'), 'gpt-6.1-sol')
        self.assertEqual(select_model(self.home, self.settings, 'openai', 'gpt-6-astra'), 'gpt-6-astra')
        self.assertEqual(select_model(self.home, self.settings, 'codex-hybrid', 'vendor/model'), 'vendor/model')
        for invalid in ['vendor/model', '', 42]:
            with self.assertRaises(ConfigError):
                select_model(self.home, self.settings, 'openai', invalid)
        configured = dict(self.settings, session_default_models={'openai': 'gpt-6-astra'})
        self.assertEqual(select_model(self.home, configured, 'openai'), 'gpt-6-astra')

    def test_empty_visible_catalog_does_not_fall_back_to_hidden_models(self):
        (self.home / 'catalog.json').write_text('{"models":[]}')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MODEL_LIST_EMPTY'):
            select_model(self.home, self.settings, 'openai')

    def test_preview_has_no_writes_and_binds_model(self):
        path = self.session('parent')
        before = path.read_bytes(), self.database.read_bytes()
        first = plan(self.home, self.settings, 'openai')
        second = plan(self.home, self.settings, 'openai', 'gpt-6-astra')
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(before, (path.read_bytes(), self.database.read_bytes()))
        self.assertFalse(self.runtime.exists())

    def test_roundtrip_archived_children_model_and_history_offsets(self):
        parent = self.session('parent')
        old_lines = parent.read_bytes().splitlines(keepends=True)
        child = self.session('child', archived=True, base={
            'thread_id': 'parent', 'end_ordinal_exclusive': 2,
            'end_byte_offset': len(old_lines[0]) + len(old_lines[1])})
        original_user = old_lines[-1]
        for provider, model in [('codex-hybrid', 'gpt-6-astra'), ('openai', 'gpt-6.1-sol')]:
            migration = plan(self.home, self.settings, provider, model)
            backup = apply(migration, self.runtime, {})
            self.assertEqual(json.loads((Path(backup) / 'manifest.json').read_text())['status'], 'complete')
            new_lines = parent.read_bytes().splitlines(keepends=True)
            base = json.loads(child.read_bytes().splitlines()[0])['payload']['history_base']
            self.assertEqual(base['end_byte_offset'], len(new_lines[0]) + len(new_lines[1]))
            self.assertEqual(base['end_ordinal_exclusive'], 2)
            self.assertEqual(new_lines[-1], original_user)
            self.assertEqual(json.loads(new_lines[1])['payload']['model'], model)
            self.assertEqual(self.rows(), [('child', provider, model), ('parent', provider, model)])

    def test_stale_session_and_database_refuse_all_writes(self):
        path = self.session('one')
        migration = plan(self.home, self.settings, 'openai')
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            apply(migration, self.runtime, {})
        self.assertEqual(self.rows()[0][1], 'old')

    def test_missing_lineage_source_refuses_before_writes(self):
        self.session('child', base={'thread_id': 'missing', 'end_byte_offset': 0})
        with self.assertRaisesRegex(ConfigError, 'SESSION_HISTORY_SOURCE_MISSING'):
            plan(self.home, self.settings, 'openai')

    def test_midwrite_failure_rolls_back_files_database_and_config(self):
        path = self.session('one')
        config = self.home / 'config.toml'
        config.write_bytes(b'model_provider = "old"\n')
        original = path.read_bytes()
        migration = plan(self.home, self.settings, 'openai')
        from desktop.session_migration import write
        def fail_config(p, data):
            if p == config and data == b'new config':
                raise OSError('injected failure')
            write(p, data)
        with patch('desktop.session_migration.write', side_effect=fail_config):
            with self.assertRaises(OSError):
                apply(migration, self.runtime, {config: (config.read_bytes(), b'new config')})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(config.read_bytes(), b'model_provider = "old"\n')
        self.assertEqual(self.rows()[0][1], 'old')

    def test_running_codex_refuses_before_backup_or_changes(self):
        path = self.session('one')
        before = path.read_bytes()
        migration = plan(self.home, self.settings, 'openai')
        with patch('desktop.session_migration.assert_stopped', side_effect=ConfigError('SESSION_MIGRATION_CODEX_RUNNING')):
            with self.assertRaises(ConfigError):
                apply(migration, self.runtime, {})
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.runtime.exists())

    def test_database_only_cloud_rows_are_not_migrated(self):
        self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO threads VALUES (?,?,?,?)', ('cloud', '', 'remote', 'remote-model'))
        apply(plan(self.home, self.settings, 'openai'), self.runtime, {})
        self.assertEqual(self.rows()[0], ('cloud', 'remote', 'remote-model'))

    def test_config_model_does_not_modify_nested_model(self):
        text = 'model = "old"\n[profiles.test]\nmodel = "nested"\n'
        self.assertEqual(config_model(text, 'gpt-6.1-sol'),
                         'model = "gpt-6.1-sol"\n[profiles.test]\nmodel = "nested"\n')

    def test_new_rollout_after_preview_refuses(self):
        self.session('one')
        migration = plan(self.home, self.settings, 'openai')
        self.session('two')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            apply(migration, self.runtime, {})
        self.assertEqual(self.rows()[0][1], 'old')

    def test_index_without_rollout_is_reported_and_migrated(self):
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO threads VALUES (?,?,?,?)',
                       ('gone', str(self.home/'sessions/gone.jsonl'), 'old', 'vendor/model'))
        migration = plan(self.home, self.settings, 'openai')
        self.assertEqual(migration['missing_rollouts'], 1)
        apply(migration, self.runtime, {})
        self.assertEqual(self.rows(), [('gone', 'openai', 'gpt-6.1-sol')])

    def test_multiple_segments_of_same_logical_thread_keep_lineage(self):
        original = self.session('logical')
        first_id = '00000000-0000-0000-0000-000000000001'
        second_id = '00000000-0000-0000-0000-000000000002'
        first = original.with_name('rollout-'+first_id+'.jsonl')
        original.rename(first)
        child = self.session('child', base={'thread_id': first_id, 'end_ordinal_exclusive': 1,
                                           'end_byte_offset': len(first.read_bytes().splitlines(keepends=True)[0])})
        record = json.loads(child.read_bytes().splitlines()[0]);record['payload']['id'] = 'logical'
        lines = child.read_bytes().splitlines(keepends=True)
        child.write_bytes(json.dumps(record).encode()+b'\n'+b''.join(lines[1:]))
        second = child.with_name('rollout-'+first_id+'_'+second_id+'.jsonl');child.rename(second)
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('DELETE FROM threads WHERE id = ?', ('child',))
            db.execute('UPDATE threads SET rollout_path=? WHERE id=?', (str(second), 'logical'))
        migration = plan(self.home, self.settings, 'openai')
        apply(migration, self.runtime, {})
        base = json.loads(second.read_bytes().splitlines()[0])['payload']['history_base']
        self.assertEqual(base['end_byte_offset'], len(first.read_bytes().splitlines(keepends=True)[0]))

    def test_commit_marker_failure_restores_database_as_well_as_files(self):
        path = self.session('one');before = path.read_bytes()
        migration = plan(self.home, self.settings, 'openai')
        from desktop.session_migration import write
        def fail_marker(p, data):
            if p.name == 'manifest.json' and json.loads(data)['status'] == 'complete':
                raise OSError('commit marker failed')
            write(p, data)
        with patch('desktop.session_migration.write', side_effect=fail_marker):
            with self.assertRaises(OSError):
                apply(migration, self.runtime, {})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.rows()[0][1], 'old')

    def test_interrupted_migration_blocks_and_can_be_recovered(self):
        path = self.session('one');before = path.read_bytes()
        backup = Path(apply(plan(self.home, self.settings, 'openai'), self.runtime, {}))
        manifest = json.loads((backup/'manifest.json').read_text())
        manifest['status'] = 'applying'
        (backup/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_RECOVERY_REQUIRED'):
            apply(plan(self.home, self.settings, 'codex-hybrid'), self.runtime, {})
        recover(backup)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.rows()[0][1], 'old')

    def test_recovery_rejects_new_sessions(self):
        self.session('one')
        backup = Path(apply(plan(self.home, self.settings, 'openai'), self.runtime, {}))
        manifest = json.loads((backup/'manifest.json').read_text());manifest['status'] = 'applying'
        (backup/'manifest.json').write_text(json.dumps(manifest))
        self.session('two')
        with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CHANGED'):
            recover(backup)

    def management(self):
        from desktop.service import candidate_config, digest
        from management.service import Management
        self.runtime.mkdir(exist_ok=True)
        self.settings.update(port=18891, local_token='test-token')
        config = self.home/'config.toml'
        native = 'model_provider = "openai"\nmodel = "gpt-6.1-sol"\n'
        candidate = candidate_config(native, self.settings)
        config.write_text(native)
        (self.runtime/'original-config.toml').write_text(native)
        (self.runtime/'desktop-config.toml').write_text(candidate)
        (self.runtime/'settings.json').write_text(json.dumps(self.settings))
        state = {'config_path': str(config), 'original_sha256': digest(native.encode()),
                 'candidate_sha256': digest(candidate.encode()), 'activated': False}
        (self.runtime/'state.json').write_text(json.dumps(state))
        return Management(SimpleNamespace(settings=self.settings), self.runtime/'settings.json', None, None)

    def test_management_switch_migrates_default_model_both_ways(self):
        self.session('one')
        manager = self.management()
        for mode, requested, expected_provider, expected_model in [
                ('project', 'vendor/model', 'codex-hybrid', 'vendor/model'),
                ('openai', None, 'openai', 'gpt-6.1-sol')]:
            preview = manager.preview_routing(mode, requested)
            self.assertEqual(preview['session_count'], 1)
            result = manager.set_routing(mode, preview['revision'], requested)
            self.assertEqual(result['default_model'], expected_model)
            self.assertEqual(self.rows(), [('one', expected_provider, expected_model)])
            self.assertIn('model = '+json.dumps(expected_model), (self.home/'config.toml').read_text())
            self.assertTrue(Path(result['session_backup']).is_dir())

    def test_management_binds_explicit_model_to_preview(self):
        self.session('one')
        manager = self.management()
        preview = manager.preview_routing('project', 'vendor/model')
        with self.assertRaisesRegex(ConfigError, 'CLIENT_CONFIG_CHANGED'):
            manager.set_routing('project', preview['revision'], 'gpt-6-astra')
        self.assertEqual(self.rows()[0][1], 'old')

    def test_confirmed_switch_proceeds_when_codex_is_running_or_detection_unknown(self):
        self.session('one')
        manager = self.management()
        for error in ('SESSION_MIGRATION_CODEX_RUNNING', 'SESSION_MIGRATION_PROCESS_CHECK_FAILED'):
            for mode, provider in [('project', 'codex-hybrid'), ('openai', 'openai')]:
                preview = manager.preview_routing(mode)
                with patch('desktop.session_migration.assert_stopped', side_effect=ConfigError(error)) as check:
                    with self.assertRaises(ConfigError):
                        manager.set_routing(mode, preview['revision'])
                    check.reset_mock()
                    result = manager.set_routing(mode, preview['revision'], confirm_activity=True)
                    check.assert_not_called()
                self.assertEqual(manager.routing_state(), mode)
                self.assertEqual(self.rows()[0][1], provider)
                self.assertTrue(Path(result['session_backup']).is_dir())

    def test_activity_confirmation_does_not_bypass_stale_preview(self):
        path = self.session('one')
        manager = self.management()
        preview = manager.preview_routing('project')
        manager.set_routing('project', preview['revision'])
        preview = manager.preview_routing('openai')
        path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaises(ConfigError):
            manager.set_routing('openai', preview['revision'], confirm_activity=True)
        self.assertEqual(manager.routing_state(), 'project')

    def test_cli_activate_rollback_and_uninstall_migrate(self):
        from desktop import service
        self.session('one')
        self.management()
        for action, requested, expected_provider, expected_model in [
                ('activate', 'vendor/model', 'codex-hybrid', 'vendor/model'),
                ('rollback', None, 'openai', 'gpt-6.1-sol'),
                ('uninstall', 'gpt-6-astra', 'openai', 'gpt-6-astra')]:
            argv = ['codex-hybrid', action, '--data-dir', str(self.runtime)]
            if requested:
                argv += ['--default-model', requested]
            with patch('sys.argv', argv), patch.object(service, 'RUNTIME', self.runtime), \
                    patch.object(service, 'health'), patch.object(service, 'stop_service'), \
                    contextlib.redirect_stdout(io.StringIO()):
                service.main()
            self.assertEqual(self.rows(), [('one', expected_provider, expected_model)])

    def test_process_detection_blocks_idle_backend_for_matching_home(self):
        process = SimpleNamespace(pid=-1, info={'name': 'codex', 'cmdline': ['codex', 'app-server']},
                                  environ=lambda: {'CODEX_HOME': str(self.home)})
        with patch('psutil.process_iter', return_value=[process]):
            with self.assertRaisesRegex(ConfigError, 'SESSION_MIGRATION_CODEX_RUNNING'):
                assert_stopped(self.home)
            assert_stopped(self.home/'different-instance')

    def test_recovery_preserves_unrelated_database_metadata(self):
        self.session('one')
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('ALTER TABLE threads ADD COLUMN title TEXT')
            db.execute('UPDATE threads SET title="before"')
        backup = Path(apply(plan(self.home, self.settings, 'openai'), self.runtime, {}))
        manifest = json.loads((backup/'manifest.json').read_text());manifest['status'] = 'applying'
        (backup/'manifest.json').write_text(json.dumps(manifest))
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE threads SET title="after"')
        recover(backup)
        with contextlib.closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT title FROM threads').fetchone()[0], 'after')
        self.assertEqual(self.rows()[0][1], 'old')

    def test_empty_home_still_selects_default_for_new_sessions(self):
        manager = self.management()
        preview = manager.preview_routing('project', 'gpt-6-astra')
        result = manager.set_routing('project', preview['revision'], 'gpt-6-astra')
        self.assertEqual(result['session_count'], 0)
        self.assertIn('model = "gpt-6-astra"', (self.home/'config.toml').read_text())
