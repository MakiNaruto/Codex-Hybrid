"""Protocol boundary and forwarding regressions; no external network calls."""
from contextlib import closing
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gateway.server import external_route
from model_catalog.catalog import Catalog, ConfigError
from model_catalog.cc_switch import decode, inventory


class ResponsesOnlyTests(unittest.TestCase):
    def config(self, protocol='openai_responses', **options):
        return {'version': 1, 'providers': {'custom': {
            'protocol': protocol, 'base_url': 'https://provider.invalid/v1',
            'credentials': {'api_key': 'fixture-key'},
            'models': {'model': {'model_id': 'vendor-model', 'max_output_tokens': 256}},
            **options}}}

    def test_yaml_rejects_chat_including_disabled_providers(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled), self.assertRaisesRegex(ConfigError, 'CONFIG_UNSUPPORTED_PROTOCOL'):
                Catalog('unused.yaml', self.config('openai_chat_completions', enabled=enabled))

    def test_default_mode_is_native_and_explicit_portable_is_preserved(self):
        catalog = Catalog('unused.yaml', self.config())
        self.assertEqual(catalog.select('custom/model')[1]['responses_compatibility'], 'native')
        self.assertEqual(decode('codex', self.cc_settings())['responses_compatibility'], 'native')
        catalog = Catalog('unused.yaml', self.config(responses_compatibility='portable'))
        self.assertEqual(catalog.select('custom/model')[1]['responses_compatibility'], 'portable')
        raw = json.loads(self.cc_settings())
        raw['config']['model_providers']['custom']['responses_compatibility'] = 'portable'
        self.assertEqual(decode('codex', json.dumps(raw))['responses_compatibility'], 'portable')

    def test_chat_budget_option_is_removed(self):
        with self.assertRaisesRegex(ConfigError, 'CONFIG_UNKNOWN_FIELD'):
            Catalog('unused.yaml', self.config(token_limit_field='max_tokens'))

    def test_responses_requests_and_events(self):
        for mode in ('native', 'portable'):
            with self.subTest(mode=mode):
                catalog = Catalog('unused.yaml', self.config(responses_compatibility=mode))
                body = {'model': 'custom/model', 'input': [
                    {'role': 'user', 'content': 'hello'}], 'tools': [],
                    'stream': True, 'max_output_tokens': 512}
                original = copy.deepcopy(body)
                settings = {'source': {'type': 'yaml'}, 'models': ['custom/model'], 'official_models': []}
                with patch('gateway.server.load_source', return_value=catalog):
                    url, payload, headers, adapt = external_route(body, settings)
                self.assertEqual(url, 'https://provider.invalid/v1/responses')
                self.assertEqual(payload['model'], 'vendor-model')
                self.assertEqual(payload['max_output_tokens'], 256)
                self.assertFalse(payload['store'])
                self.assertNotIn('messages', payload)
                self.assertNotIn('max_tokens', payload)
                self.assertEqual(headers['Authorization'], 'Bearer fixture-key')
                self.assertEqual(body, original)
                events = adapt({'type': 'response.completed', 'response': {
                    'id': 'fixture-response', 'status': 'completed', 'output': []}})
                self.assertTrue(any(e['type'] == 'response.completed' for e in events))

    def cc_settings(self, wire='responses'):
        return json.dumps({'config': {'model_provider': 'custom', 'model': 'vendor-model',
            'model_providers': {'custom': {'wire_api': wire, 'base_url': 'https://provider.invalid/v1'}}},
            'auth': {'OPENAI_API_KEY': 'fixture-key'}})

    def test_cc_switch_only_accepts_responses(self):
        self.assertEqual(decode('codex', self.cc_settings())['protocol'], 'openai_responses')
        for wire, meta in [('chat', {}), ('responses', {'apiFormat': 'openai_chat'}),
                           ('chat', {'apiFormat': 'openai_responses'})]:
            with self.subTest(wire=wire, meta=meta), self.assertRaisesRegex(ConfigError, 'CC_PROTOCOL_NOT_SUPPORTED'):
                decode('codex', self.cc_settings(wire), meta)

    def test_cc_inventory_excludes_chat(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cc.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE providers (id, app_type, name, settings_config, meta, sort_index, created_at)')
                for name, wire in [('chat', 'chat'), ('responses', 'responses')]:
                    db.execute('INSERT INTO providers VALUES (?, ?, ?, ?, ?, 0, 0)',
                               (name, 'codex', name, self.cc_settings(wire), '{}'))
                db.commit()
            entries = {item['name']: item for item in inventory(path)}
            self.assertNotIn('chat', entries)
            self.assertTrue(entries['responses']['supported'])


if __name__ == '__main__':
    unittest.main()
