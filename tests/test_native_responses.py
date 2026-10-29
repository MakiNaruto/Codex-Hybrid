import copy
import unittest
from unittest.mock import patch

from adapters.native_responses import NativeResponsesAdapter
from gateway.server import route
from model_catalog.catalog import Catalog, ConfigError
from model_catalog.cc_switch import decode


class NativeResponsesTests(unittest.TestCase):
    def setUp(self):
        self.body = {'model': 'vendor/model', 'stream': True, 'store': False,
            'reasoning': {'effort': 'low'}, 'include': ['reasoning.encrypted_content'],
            'instructions': 'ROOT', 'parallel_tool_calls': True,
            'tools': [{'type': 'namespace', 'name': 'host', 'tools': [
                {'type': 'function', 'name': 'lookup', 'parameters': {}}]}],
            'input': [
                {'type': 'function_call_output', 'id': 'fco_1', 'name': 'delegate',
                 'namespace': 'host', 'output': 'TASK'},
                {'type': 'reasoning', 'id': 'rs_1', 'encrypted_content': 'opaque', 'summary': []},
                {'role': 'developer', 'content': 'LATEST'},
                {'type': 'additional_tools', 'tools': []}]}

    def catalog(self, **options):
        return Catalog('unused.yaml', data={'version': 1, 'providers': {'vendor': {
            'protocol': 'openai_responses', 'base_url': 'https://vendor.invalid/v1',
            'credentials': {'api_key': 'test-only'}, 'models': {'model': {'model_id': 'upstream'}},
            'responses_compatibility': 'native', **options}}})

    def routed(self, catalog):
        settings = {'source': {'type': 'yaml'}, 'models': ['vendor/model'], 'official_models': []}
        with patch('gateway.server.load_source', return_value=catalog):
            return route(self.body, {'Authorization': 'Bearer local-test-token'}, settings)

    def test_native_route_preserves_structure_and_fields_without_mutation(self):
        before = copy.deepcopy(self.body)
        url, payload, headers, adapt = self.routed(self.catalog())
        self.assertEqual(url, 'https://vendor.invalid/v1/responses')
        self.assertEqual(headers['Authorization'], 'Bearer test-only')
        self.assertEqual(payload, dict(before, model='upstream'))
        self.assertEqual(self.body, before)
        self.assertIsInstance(adapt.__self__, NativeResponsesAdapter)

    def test_native_events_preserve_namespaces_argument_deltas_and_spawn_arguments(self):
        _, _, _, adapt = self.routed(self.catalog())
        events = [
            {'type': 'response.function_call_arguments.delta', 'item_id': 'fc1', 'delta': '{}'},
            {'type': 'response.output_item.done', 'item': {'type': 'function_call', 'id': 'fc1',
             'namespace': 'collaboration', 'name': 'spawn_agent',
             'arguments': '{"task_name":"worker","model":"vendor/model"}'}},
            {'type': 'response.completed', 'response': {'output': []}}]
        for event in events:
            self.assertEqual(adapt(event), [event])

    def test_protocol_mismatch_fails_without_chat_fallback(self):
        _, _, _, adapt = self.routed(self.catalog())
        with self.assertRaisesRegex(ValueError, 'UPSTREAM_PROTOCOL_MISMATCH'):
            adapt({'choices': []})

    def test_history_migration_only_removes_replayable_item_ids(self):
        self.body['input'].append({'type': 'item_reference', 'id': 'ref_1'})
        _, payload, _, _ = self.routed(self.catalog(history_migration=True))
        expected = copy.deepcopy(self.body)
        for item in expected['input'][:2]:
            item.pop('id')
        self.assertEqual(payload, dict(expected, model='upstream'))

    def test_portable_mode_explicitly_retains_existing_conversion(self):
        # The old compatibility route needs the configured spawn catalog.
        with patch('gateway.server.expose_spawn_catalog', side_effect=lambda body, settings: body):
            _, payload, _, _ = self.routed(self.catalog(responses_compatibility='portable'))
        self.assertEqual(payload['input'][0]['role'], 'user')
        self.assertIn('host.delegate', payload['input'][0]['content'][0]['text'])
        self.assertFalse(any(i.get('type') == 'reasoning' for i in payload['input']))
        self.assertEqual(payload['tools'][0]['name'], 'host__lookup')

    def test_chat_route_keeps_conversion(self):
        with patch('gateway.server.expose_spawn_catalog', side_effect=lambda body, settings: body):
            url, payload, _, _ = self.routed(self.catalog(protocol='openai_chat_completions'))
        self.assertTrue(url.endswith('/chat/completions'))
        self.assertNotIn('input', payload)
        self.assertEqual(payload['messages'][0]['role'], 'system')
        self.assertIn('TASK', str(payload['messages']))
        self.assertEqual(payload['tools'][0]['function']['name'], 'host__lookup')

    def test_native_applies_explicit_parameters_budget_and_no_storage(self):
        self.body.update(store=True, max_output_tokens=64)
        catalog = self.catalog(parameters={'temperature': 0})
        catalog.models['vendor/model']['max_output_tokens'] = 32
        catalog.models['vendor/model']['output_limit_configured'] = True
        _, payload, _, _ = self.routed(catalog)
        self.assertFalse(payload['store'])
        self.assertEqual(payload['max_output_tokens'], 32)
        self.assertEqual(payload['temperature'], 0)
        self.assertEqual(payload['reasoning'], self.body['reasoning'])
        with self.assertRaisesRegex(ConfigError, 'CONFIG_RESERVED_PARAMETER'):
            self.catalog(parameters={'input': []})

    def test_legacy_responses_also_preserves_native_structure(self):
        settings = {'models': ['vendor/model'], 'deepseek_max_output_tokens': 256}
        legacy = {'DEEPSEEK_MODEL': 'vendor/model', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com',
                  'DEEPSEEK_API_KEY': 'test-only'}
        _, payload, _, adapt = route(self.body, {'Authorization': 'Bearer local-test-token'}, settings, legacy)
        self.assertEqual(payload, dict(self.body, max_output_tokens=256))
        self.assertIsInstance(adapt.__self__, NativeResponsesAdapter)

    def test_invalid_or_chat_only_options_rejected(self):
        for options in ({'responses_compatibility': 'auto'}, {'history_migration': 'true'}):
            with self.assertRaises(ConfigError):
                self.catalog(**options)
        with self.assertRaisesRegex(ConfigError, 'CONFIG_UNSUPPORTED_PROTOCOL_OPTIONS'):
            self.catalog(protocol='openai_chat_completions', history_migration=True)

    def test_cc_switch_defaults_portable_and_reads_explicit_options(self):
        import json
        provider = {'base_url': 'https://vendor.invalid/v1', 'wire_api': 'responses'}
        raw = {'auth': {'OPENAI_API_KEY': 'test-only'}, 'config': {
            'model_provider': 'custom', 'model': 'upstream', 'model_providers': {'custom': provider}}}
        parsed = decode('codex', json.dumps(raw))
        self.assertEqual(parsed['responses_compatibility'], 'portable')
        self.assertFalse(parsed['history_migration'])
        provider.update(responses_compatibility='portable', history_migration=True)
        parsed = decode('codex', json.dumps(raw))
        self.assertEqual(parsed['responses_compatibility'], 'portable')
        self.assertTrue(parsed['history_migration'])
        provider['responses_compatibility'] = 'native'
        self.assertEqual(decode('codex', json.dumps(raw))['responses_compatibility'], 'native')

    def test_cc_switch_catalog_routes_and_reloads_explicit_compatibility(self):
        from contextlib import closing
        import json
        import sqlite3
        import tempfile
        from pathlib import Path
        from model_catalog.cc_switch import make_catalog
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cc.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE providers (id, app_type, name, settings_config, meta, sort_index, created_at)')
                provider = {'base_url': 'https://vendor.invalid/v1', 'wire_api': 'responses'}
                raw = {'auth': {'OPENAI_API_KEY': 'test-only'}, 'config': {'model_provider': 'custom',
                    'model': 'model', 'model_providers': {'custom': provider}}}
                db.execute('INSERT INTO providers VALUES (?, ?, ?, ?, ?, 0, 0)',
                           ('vendor', 'codex', 'Vendor', json.dumps(raw), '{}'))
                db.commit()
            catalog = make_catalog(path)
            settings = {'models': ['vendor/model'], 'official_models': [],
                        'source': {'type': 'cc-switch', 'path': str(path)},
                        'cc_snapshot': {'bindings': catalog.bindings}}
            for mode in ('native', 'portable'):
                provider['responses_compatibility'] = mode
                with closing(sqlite3.connect(path)) as db:
                    db.execute('UPDATE providers SET settings_config=?', (json.dumps(raw),))
                    db.commit()
                with patch('gateway.server.expose_spawn_catalog', side_effect=lambda body, settings: body):
                    _, payload, _, _ = route(self.body, {'Authorization': 'Bearer local-test-token'}, settings)
                if mode == 'native':
                    self.assertEqual(payload, dict(self.body, model='model'))
                else:
                    self.assertEqual(payload['input'][0]['role'], 'user')
