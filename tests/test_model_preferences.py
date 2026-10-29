"""Model membership and compatibility are enforced by routing, not only the UI."""
import copy
import unittest
from model_catalog.catalog import Catalog, ConfigError
from model_catalog.sources import apply_preferences, source_key


class ModelPreferencesTests(unittest.TestCase):
    def catalog(self):
        return Catalog('/tmp/models.yaml', data={'version': 1, 'providers': {'vendor': {
            'protocol': 'openai_responses', 'base_url': 'https://example.invalid/v1',
            'credentials': {'api_key': 'fixture'}, 'models': {
                'a': {'model_id': 'a'}, 'b': {'model_id': 'b', 'responses_compatibility': 'native'}}}}})

    def settings(self, **preferences):
        source = {'type': 'cc-switch', 'path': '/tmp/cc.db'}
        return {'source': source, 'model_preferences': {source_key(source): preferences}}

    def test_new_responses_models_default_portable_and_explicit_native_wins(self):
        catalog = self.catalog()
        self.assertEqual(catalog.select('vendor/a')[1]['responses_compatibility'], 'portable')
        self.assertEqual(catalog.select('vendor/b')[1]['responses_compatibility'], 'native')
        self.assertEqual(catalog.providers['vendor']['responses_compatibility'], 'portable')

    def test_membership_blocks_select_and_listing_but_retains_inventory(self):
        catalog = apply_preferences(self.catalog(), self.settings(added=['vendor/a'], compatibility={}))
        self.assertEqual([m['key'] for m in catalog.listing()], ['vendor/a'])
        self.assertEqual(len(catalog.listing(True)), 2)
        with self.assertRaisesRegex(ConfigError, 'MODEL_DISABLED'):
            catalog.select('vendor/b')

    def test_independent_per_model_override_does_not_mutate_provider(self):
        settings = self.settings(added=['vendor/a','vendor/b'], compatibility={'vendor/a':'native','vendor/b':'portable'})
        original = copy.deepcopy(settings)
        catalog = apply_preferences(self.catalog(), settings)
        self.assertEqual(catalog.select('vendor/a')[1]['responses_compatibility'], 'native')
        self.assertEqual(catalog.select('vendor/b')[1]['responses_compatibility'], 'portable')
        self.assertEqual(settings, original)

    def test_newly_discovered_models_and_other_sources_are_not_implicitly_added(self):
        catalog = apply_preferences(self.catalog(), self.settings(added=[], compatibility={}))
        self.assertEqual(catalog.listing(), [])
        settings = self.settings(added=[], compatibility={})
        settings['source']['path']='/tmp/other.db'
        self.assertEqual(len(apply_preferences(self.catalog(), settings).listing()),2)

    def test_invalid_preference_fails_closed(self):
        for prefs in ({'added':'vendor/a'}, {'added':[1]}, {'added':[], 'compatibility':{'vendor/a':'unknown'}}):
            with self.subTest(prefs=prefs), self.assertRaises(ConfigError):
                apply_preferences(self.catalog(), self.settings(**prefs))

    def test_chat_keeps_dormant_responses_override_when_protocol_changes(self):
        catalog = Catalog('/tmp/models.yaml', data={'version': 1, 'providers': {'vendor': {
            'protocol': 'openai_chat_completions', 'base_url': 'https://example.invalid/v1',
            'credentials': {'api_key': 'fixture'}, 'models': {'a': {'model_id': 'a'}}}}})
        catalog = apply_preferences(catalog, self.settings(added=['vendor/a'], compatibility={'vendor/a':'portable'}))
        self.assertEqual(catalog.select('vendor/a')[1]['responses_compatibility'], 'native')

    def test_effective_model_override_selects_the_real_routing_adapter(self):
        from unittest.mock import patch
        from gateway.server import route
        from adapters.native_responses import NativeResponsesAdapter
        settings = self.settings(added=['vendor/a','vendor/b'], compatibility={'vendor/a':'native','vendor/b':'portable'})
        settings.update(models=['vendor/a','vendor/b'], official_models=[])
        catalog = apply_preferences(self.catalog(),settings)
        catalog.bindings={'vendor/a': {'model_id':'a'}, 'vendor/b': {'model_id':'b'}}
        settings['cc_snapshot']={'bindings':catalog.bindings}
        with patch('gateway.server.load_source',return_value=catalog):
            adapt = route({'model':'vendor/a','stream':True,'input':[]},
                          {'Authorization':'Bearer fixture-test-only'},settings)[3]
        self.assertIsInstance(adapt.__self__,NativeResponsesAdapter)
