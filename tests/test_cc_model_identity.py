"""Published CC selections stay bound to a provider record and exact model ID."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from gateway.server import route
from model_catalog.catalog import ConfigError
from model_catalog.cc_switch import inventory, make_catalog, match_current_record
from model_catalog.sources import merged_catalog, update_cc_snapshot


class CCModelIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.database = self.root / 'cc.db'
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('CREATE TABLE providers (id, app_type, name, settings_config, meta, sort_index, created_at)')
        self.write_provider()
        self.publish()

    def write_provider(self, identifier='record-a', name='Vendor', default='model-a',
                       models=('model-a', 'model-b'), base='https://a.invalid/v1', key='key-a'):
        raw = {'auth': {'OPENAI_API_KEY': key}, 'config': {
            'model_provider': 'custom', 'model': default,
            'model_providers': {'custom': {'base_url': base, 'wire_api': 'responses'}}},
            'modelCatalog': {'models': [{'model': model, 'displayName': 'Label ' + model} for model in models]}}
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('DELETE FROM providers WHERE id=?', (identifier,))
            db.execute('INSERT INTO providers VALUES (?, ?, ?, ?, ?, 0, 0)',
                       (identifier, 'codex', name, json.dumps(raw), '{}'))
            db.commit()

    def publish(self):
        self.catalog = make_catalog(self.database)
        published = merged_catalog([{'slug': 'official'}], self.catalog)
        path = self.root / 'catalog.json'
        path.write_text(json.dumps(published), encoding='utf-8')
        self.settings = {'catalog': str(path), 'source': {'type': 'cc-switch', 'path': str(self.database)},
                         'models': [model['slug'] for model in published['models']],
                         'official_models': ['official']}
        update_cc_snapshot(self.settings, published, self.catalog)
        return published

    def key_for(self, model_id, name='Vendor'):
        return next(key for key, model in self.catalog.models.items()
                    if model['model_id'] == model_id and model['display_name'].startswith(name + ' · '))

    def route(self, key):
        return route({'model': key, 'stream': True, 'input': []},
                     {'Authorization': 'Bearer subscription-test-only'}, self.settings)

    def test_default_change_keeps_every_published_selection_bound_to_its_model(self):
        published = json.loads(Path(self.settings['catalog']).read_text())
        selections = {model['slug']: self.catalog.models[model['slug']]['model_id']
                      for model in published['models'] if model['slug'] != 'official'}
        self.write_provider(default='model-b')
        for key, expected in selections.items():
            with self.subTest(key=key):
                self.assertEqual(self.route(key)[1]['model'], expected)
        self.publish()
        self.assertEqual(set(self.catalog.models), set(selections))

    def test_published_external_models_expose_selectable_reasoning_levels(self):
        published = self.publish()
        external = [model for model in published['models'] if model['slug'] != 'official']

        self.assertTrue(external)
        for model in external:
            self.assertEqual(
                [level['effort'] for level in model['supported_reasoning_levels']],
                ['low', 'medium', 'high'],
            )
            self.assertIn(model['default_reasoning_level'], {'low', 'medium', 'high'})

    def test_names_order_address_and_credentials_change_without_changing_identity(self):
        key = self.key_for('model-a')
        self.write_provider(name='Renamed', models=('model-b', 'model-a'),
                            base='https://updated.invalid/v1', key='updated-key')
        endpoint, payload, headers, _ = self.route(key)
        self.assertEqual(endpoint, 'https://updated.invalid/v1/responses')
        self.assertEqual(payload['model'], 'model-a')
        self.assertEqual(headers['Authorization'], 'Bearer updated-key')
        self.publish()
        self.assertEqual(self.key_for('model-a', 'Renamed'), key)

    def test_same_model_and_display_name_in_different_records_route_to_correct_provider(self):
        self.write_provider(identifier='record-b', base='https://b.invalid/v1', key='key-b')
        self.publish()
        keys = [key for key, model in self.catalog.models.items() if model['model_id'] == 'model-a']
        self.assertEqual(len(set(keys)), 2)
        routed = {(self.route(key)[0], self.route(key)[2]['Authorization']) for key in keys}
        self.assertEqual(routed, {('https://a.invalid/v1/responses', 'Bearer key-a'),
                                  ('https://b.invalid/v1/responses', 'Bearer key-b')})

    def test_removed_model_fails_instead_of_falling_back_to_new_default(self):
        key = self.key_for('model-a')
        self.write_provider(default='model-b', models=('model-b',))
        with self.assertRaisesRegex(ConfigError, '^MODEL_NOT_CONFIGURED$'):
            self.route(key)

    def test_deleted_record_does_not_fall_back_to_same_named_provider(self):
        key = self.key_for('model-a')
        self.write_provider(identifier='record-b')
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('DELETE FROM providers WHERE id=?', ('record-a',))
            db.commit()
        with self.assertRaisesRegex(ConfigError, '^MODEL_NOT_CONFIGURED$'):
            self.route(key)

    def test_legacy_default_is_rejected_even_when_still_in_client_allowlist(self):
        legacy = self.key_for('model-a').split('/')[0] + '/default'
        self.settings['models'].append(legacy)
        self.write_provider(default='model-b')
        with self.assertRaisesRegex(ConfigError, '^MODEL_NOT_CONFIGURED$'):
            self.route(legacy)

    def test_slug_contains_original_record_and_model_ids(self):
        expected = 'record-a/model-b'
        self.assertEqual(self.key_for('model-b'), expected)
        self.assertEqual(self.route(expected)[1]['model'], 'model-b')

    def test_model_id_with_slashes_and_unicode_is_not_split_or_encoded(self):
        model_id = 'vendor/模型-v1:latest'
        self.write_provider(default=None, models=(model_id,))
        self.publish()
        key = self.key_for(model_id)
        self.assertEqual(key, 'record-a/' + model_id)
        self.assertEqual(self.settings['cc_snapshot']['bindings'][key], {
            'provider_record_id': 'record-a', 'app_type': 'codex', 'model_id': model_id})
        self.assertEqual(self.route(key)[1]['model'], model_id)

    def test_binding_mismatch_is_rejected(self):
        key = self.key_for('model-a')
        self.settings['cc_snapshot']['bindings'][key]['model_id'] = 'model-b'
        with self.assertRaisesRegex(ConfigError, '^MODEL_NOT_CONFIGURED$'):
            self.route(key)

    def test_selection_requires_an_explicit_model(self):
        self.assertIsNone(self.catalog.default_model)
        with self.assertRaisesRegex(ConfigError, '^MODEL_SELECTION_REQUIRED$'):
            self.catalog.select()

    def test_model_catalog_does_not_require_a_configured_default_model(self):
        keys = set(self.catalog.models)
        self.write_provider(default=None)
        self.publish()
        self.assertEqual(set(self.catalog.models), keys)
        for model_id in ('model-a', 'model-b'):
            self.assertEqual(self.route(self.key_for(model_id))[1]['model'], model_id)

    def test_configured_model_without_a_model_catalog_is_an_exact_model_entry(self):
        self.write_provider(default='only-model', models=())
        self.publish()
        self.assertEqual(len(self.catalog.models), 1)
        key = self.key_for('only-model')
        self.assertNotIn('/default', key)
        self.assertEqual(self.route(key)[1]['model'], 'only-model')


class CCCurrentRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.database = self.root / 'cc.db'

    def create_database(self, *, is_current=True):
        columns = ('id, app_type, name, settings_config, meta, sort_index, created_at'
                   + (', is_current' if is_current else ''))
        with closing(sqlite3.connect(self.database)) as db:
            db.execute(f'CREATE TABLE providers ({columns})')
        return columns

    def write_provider(self, identifier, *, name='Vendor', provider=None,
                       is_current=0, schema_current=True, models=('model-a',)):
        provider = provider or {'base_url': 'https://vendor.invalid/v1', 'wire_api': 'responses'}
        raw = {'auth': {'OPENAI_API_KEY': 'not-exported-key'}, 'config': {
            'model_provider': 'custom', 'model': models[0],
            'model_providers': {'custom': provider}},
            'modelCatalog': {'models': [{'model': model} for model in models]}}
        values = [identifier, 'codex', name, json.dumps(raw), '{}', 0, 0]
        with closing(sqlite3.connect(self.database)) as db:
            if schema_current:
                values.append(is_current)
            db.execute(f'INSERT INTO providers VALUES ({",".join("?" for _ in values)})', values)
            db.commit()

    def current_config(self, provider=None):
        provider = provider or {'base_url': 'https://vendor.invalid/v1', 'wire_api': 'responses'}
        return {'model_provider': 'custom',
                'model_providers': {'custom': provider}}

    def test_inventory_supports_legacy_schema_without_is_current(self):
        self.create_database(is_current=False)
        self.write_provider('legacy', schema_current=False)
        entries = inventory(self.database)
        self.assertEqual(entries[0]['provider_record_id'], 'legacy')
        self.assertFalse(entries[0]['is_current'])

    def test_inventory_reads_is_current_without_exposing_credentials(self):
        self.create_database()
        self.write_provider('current', is_current=1)
        serialized = json.dumps(inventory(self.database))
        self.assertNotIn('not-exported-key', serialized)
        self.assertTrue(inventory(self.database)[0]['is_current'])

    def test_unique_provider_configuration_selects_the_current_record(self):
        self.create_database()
        self.write_provider('record-a')
        entry = match_current_record(inventory(self.database), self.current_config())
        self.assertEqual(entry['provider_record_id'], 'record-a')

    def test_codex_auth_fields_do_not_change_provider_record_identity(self):
        self.create_database()
        self.write_provider('record-a', provider={
            'base_url': 'https://vendor.invalid/v1',
            'wire_api': 'responses',
            'requires_openai_auth': True,
        })
        entry = match_current_record(inventory(self.database), self.current_config({
            'base_url': 'https://vendor.invalid/v1',
            'wire_api': 'responses',
            'requires_openai_auth': False,
            'experimental_bearer_token': 'runtime-only-token',
            'responses_compatibility': 'portable',
        }))
        self.assertEqual(entry['provider_record_id'], 'record-a')

    def test_configuration_wins_over_conflicting_is_current(self):
        self.create_database()
        self.write_provider('record-a', is_current=1)
        self.write_provider('record-b', is_current=0, provider={
            'base_url': 'https://other.invalid/v1', 'wire_api': 'chat'})
        entry = match_current_record(inventory(self.database), self.current_config({
            'base_url': 'https://other.invalid/v1', 'wire_api': 'chat'}))
        self.assertEqual(entry['provider_record_id'], 'record-b')

    def test_identical_provider_configurations_remain_ambiguous(self):
        self.create_database()
        self.write_provider('record-a', name='First', is_current=1)
        self.write_provider('record-b', name='Second', is_current=0)
        with self.assertRaisesRegex(ConfigError, '^CC_ROUTING_PROVIDER_AMBIGUOUS$'):
            match_current_record(inventory(self.database), self.current_config())

    def test_missing_provider_configuration_is_unmatched(self):
        self.create_database()
        self.write_provider('record-a')
        config = self.current_config({'base_url': 'https://unknown.invalid/v1', 'wire_api': 'responses'})
        with self.assertRaisesRegex(ConfigError, '^CC_ROUTING_PROVIDER_UNMATCHED$'):
            match_current_record(inventory(self.database), config)

    def test_profiles_are_rejected_before_record_matching(self):
        self.create_database()
        self.write_provider('record-a')
        with self.assertRaisesRegex(ConfigError, '^CLIENT_ROUTING_UNAVAILABLE$'):
            match_current_record(inventory(self.database), dict(self.current_config(), profile='work'))
