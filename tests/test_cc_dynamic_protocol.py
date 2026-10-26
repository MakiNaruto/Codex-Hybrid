from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest

from gateway.server import route, sse_events
from management.service import Management
from model_catalog.cc_switch import make_catalog, selected_key, inventory
from model_catalog.catalog import ConfigError


class DynamicProtocolTests(unittest.TestCase):
    def test_test_connection_follows_metadata_switches_without_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'cc.db'
            with closing(sqlite3.connect(db_path)) as db:
                db.execute('CREATE TABLE providers (id, app_type, name, settings_config, meta, sort_index, created_at)')
                raw = json.dumps({'auth': {'OPENAI_API_KEY': 'test-only'}, 'config': {
                    'model_provider': 'custom', 'model': 'glm-5.3', 'model_providers': {
                        'custom': {'base_url': 'https://open.bigmodel.cn/api/coding/paas/v4',
                                   'wire_api': 'responses'}}}})
                db.execute('INSERT INTO providers VALUES (?, ?, ?, ?, ?, 0, 0)',
                           ('glm', 'codex', 'GLM', raw, '{}'))
                db.commit()
            catalog = make_catalog(db_path)
            key = next(iter(catalog.models))
            catalog_path = Path(directory) / 'catalog.json'
            catalog_path.write_text(json.dumps({'models': []}))
            settings = {'catalog': str(catalog_path), 'source': {'type': 'cc-switch', 'path': str(db_path)},
                        'models': [key], 'official_models': []}
            seen = []

            self_outer = self

            class Opener:
                def open(self, request, timeout):
                    import io
                    seen.append(request.full_url)
                    payload = json.loads(request.data)
                    budget = payload.get('max_tokens', payload.get('max_output_tokens'))
                    self_outer.assertEqual(budget, 8192)
                    self_outer.assertIn('hello', json.dumps(payload))
                    if request.full_url.endswith('/responses'):
                        # A failed upstream request must not poison the next test.
                        from urllib.error import HTTPError
                        raise HTTPError(request.full_url, 404, 'Not Found', {}, None)
                    chunk = {'choices': [{'index': 0, 'delta': {'content': 'OK'},
                                          'finish_reason': 'stop'}]}
                    return io.BytesIO(('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n').encode())

            gateway = SimpleNamespace(settings=settings, slots=threading.Semaphore(1), opener=Opener())
            manager = Management(gateway, Path(directory) / 'settings.json', route, sse_events)
            for fmt in ['openai_chat', 'openai_responses', 'openai_chat']:
                old = inventory(db_path)[0]
                with closing(sqlite3.connect(db_path)) as db:
                    db.execute('UPDATE providers SET meta=?', (json.dumps({'apiFormat': fmt}),))
                    db.commit()
                with self.assertRaises(ConfigError):
                    selected_key(db_path, old)
                if fmt == 'openai_responses':
                    from urllib.error import HTTPError
                    with self.assertRaises(HTTPError):
                        manager.test_connection(key)
                else:
                    self.assertEqual(manager.test_connection(key)['status'], 'completed')
            base = 'https://open.bigmodel.cn/api/coding/paas/v4'
            self.assertEqual(seen, [base + '/chat/completions', base + '/responses',
                                    base + '/chat/completions'])
