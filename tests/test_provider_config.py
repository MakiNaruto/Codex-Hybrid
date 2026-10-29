import tomllib
import unittest

from desktop.service import PROVIDER, candidate_config, is_bridge_provider, remove_bridge_provider_table


class ProviderConfigTests(unittest.TestCase):
    settings = {'port': 18891, 'catalog': 'models.json', 'local_token': 'test-token'}

    def test_generated_config_uses_codex_retry_and_idle_defaults(self):
        result = candidate_config('model = "gpt-6.1-sol"\n', self.settings)
        parsed = tomllib.loads(result)
        provider = parsed['model_providers'][PROVIDER]
        self.assertEqual(provider['request_max_retries'], 4)
        self.assertEqual(provider['stream_max_retries'], 5)
        self.assertEqual(provider['stream_idle_timeout_ms'], 300000)
        self.assertTrue(is_bridge_provider(provider))
        self.assertEqual(parsed['model'], 'gpt-6.1-sol')
        # Updating a generated config must not duplicate provider tables.
        self.assertEqual(tomllib.loads(candidate_config(result, self.settings)), parsed)
        self.assertEqual(candidate_config(result, self.settings), result)

    def test_legacy_config_upgrades_and_both_formats_can_be_removed(self):
        current = candidate_config('model = "gpt-6.1-sol"\n', self.settings)
        legacy = current.replace('request_max_retries = 4', 'request_max_retries = 0')
        legacy = legacy.replace('stream_max_retries = 5', 'stream_max_retries = 0')
        legacy = legacy.replace('stream_idle_timeout_ms = 300000\n', '')
        self.assertTrue(is_bridge_provider(tomllib.loads(legacy)['model_providers'][PROVIDER]))
        self.assertEqual(tomllib.loads(candidate_config(legacy, self.settings)), tomllib.loads(current))
        for config in (legacy, current):
            cleaned, removed = remove_bridge_provider_table(config)
            self.assertTrue(removed)
            self.assertNotIn(PROVIDER, tomllib.loads(cleaned).get('model_providers', {}))

    def test_unrecognized_provider_fields_are_not_overwritten(self):
        current = candidate_config('', self.settings) + 'unknown_setting = true\n'
        with self.assertRaises(ValueError):
            candidate_config(current, self.settings)


if __name__ == '__main__':
    unittest.main()
