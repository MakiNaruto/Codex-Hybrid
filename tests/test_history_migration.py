import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from desktop.session_migration import _official_history_repairs, apply, recover, sha
import test_session_migration as migration_tests


class HistoryMigrationTests(migration_tests.SessionMigrationTests):
    def greeting(self):
        p = self.session('greeting')
        record = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
                  'id': 'msg_' + 'a' * 32, 'content': [{'type': 'output_text', 'text': '你好'}]}}
        with p.open('ab') as stream:
            stream.write(json.dumps(record, ensure_ascii=False).encode() + b'\r\n')
        return p

    def test_disable_backs_up_and_records_rule(self):
        from desktop.session_migration import plan
        p = self.greeting()
        before = p.read_bytes()
        migration = plan(self.home, self.settings, 'openai')
        backup = Path(self.saved_apply(migration, self.runtime, {}))
        after = p.read_bytes()
        self.assertNotEqual(after, before)
        old, new = [json.loads(x) for x in before.splitlines()], [json.loads(x) for x in after.splitlines()]
        old[-1]['payload'].pop('id')
        self.assertEqual(old, new)
        manifest = json.loads((backup / 'manifest.json').read_text())
        self.assertFalse(manifest['index_only'])
        self.assertEqual(manifest['history_compatibility'][0]['rule'], 'greeting-message-id-v1')
        self.assertEqual((backup / manifest['files'][0]['backup']).read_bytes(), before)
        with patch('desktop.session_migration._cleanup_record'):
            self.assertEqual(apply(plan(self.home, self.settings, 'openai'), self.runtime, {}), None)
        manifest['status'] = 'applying'
        (backup / 'manifest.json').write_text(json.dumps(manifest))
        recover(backup)
        self.assertEqual(p.read_bytes(), before)

    def test_enable_preserves_external_message_id(self):
        from desktop.session_migration import plan
        p = self.greeting()
        before = p.read_bytes()
        apply(plan(self.home, self.settings, 'codex-hybrid'), self.runtime, {})
        self.assertEqual(p.read_bytes(), before)

    def test_history_write_requires_stopped_even_with_allow_running(self):
        from desktop.session_migration import plan
        p = self.greeting()
        before = p.read_bytes()
        from model_catalog.catalog import ConfigError
        with patch('desktop.session_migration.assert_stopped', side_effect=ConfigError('SESSION_MIGRATION_CODEX_RUNNING')):
            with self.assertRaises(ConfigError):
                apply(plan(self.home, self.settings, 'openai'), self.runtime, {}, allow_running=True)
        self.assertEqual(p.read_bytes(), before)

