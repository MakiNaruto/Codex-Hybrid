import copy
import json
from pathlib import Path
import tempfile
import unittest

from model_catalog.agent_catalog import expose_spawn_catalog


class SpawnCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        catalog = Path(self.temp.name) / 'catalog.json'
        catalog.write_text(json.dumps({'models': [
            {'slug': 'gpt-test', 'visibility': 'list'},
            {'slug': 'external-key', 'display_name': 'External model', 'visibility': 'list',
             'supported_reasoning_levels': [{'effort': 'low'}]},
            {'slug': 'hidden', 'visibility': 'hide'},
            {'slug': 'disabled', 'visibility': 'list'},
        ]}))
        self.settings = {'catalog': str(catalog),
                         'models': ['gpt-test', 'external-key', 'hidden']}
        self.preview = ('Available model overrides (optional; inherited parent model is preferred):\n'
                        '- `native-only`: Native metadata.\n'
                        '- `gpt-test`: Original metadata.\n')

    def test_preserves_native_entries_and_appends_enabled_models_once(self):
        tool = {'name': 'spawn_agent', 'description': self.preview,
                'parameters': {'properties': {'model': {'type': 'string'}}}}
        original = {'tools': [{'type': 'namespace', 'name': 'collaboration', 'tools': [tool]}]}
        before = copy.deepcopy(original)
        result = expose_spawn_catalog(original, self.settings)
        description = result['tools'][0]['tools'][0]['description']
        self.assertTrue(description.startswith(self.preview))
        self.assertEqual(description.count('- `gpt-test`:'), 1)
        self.assertEqual(description.count('- `external-key`:'), 1)
        self.assertIn('- `gpt-test`: Original metadata.\n', description)
        self.assertIn('- `native-only`: Native metadata.\n', description)
        self.assertIn('- `external-key`: External model. Reasoning efforts: low.', description)
        self.assertNotIn('`hidden`', description)
        self.assertNotIn('`disabled`', description)
        self.assertEqual(original, before)
        self.assertEqual(expose_spawn_catalog(result, self.settings), result)

    def test_updates_instruction_previews_without_tool_definitions(self):
        original = {'instructions': self.preview, 'input': [
            {'role': 'developer', 'content': self.preview},
            {'role': 'system', 'content': [{'type': 'input_text', 'text': self.preview}]},
            {'role': 'user', 'content': self.preview}]}
        result = expose_spawn_catalog(original, self.settings)
        self.assertIn('`external-key`', result['instructions'])
        self.assertIn('`external-key`', result['input'][0]['content'])
        self.assertIn('`external-key`', result['input'][1]['content'][0]['text'])
        self.assertEqual(result['input'][2], original['input'][2])

    def test_deferred_bridge_tool_gets_listing_without_existing_preview(self):
        for kind in ('additional_tools', 'tool_search_output'):
            with self.subTest(kind=kind):
                original = {'input': [{'type': kind, 'tools': [
                    {'type': 'namespace', 'name': 'connected_agent_bridge', 'tools': [
                        {'name': 'spawn_agent', 'description': 'Create a child.'}]}]}]}
                result = expose_spawn_catalog(original, self.settings)
                description = result['input'][0]['tools'][0]['tools'][0]['description']
                self.assertIn('`external-key`', description)
                self.assertEqual(expose_spawn_catalog(result, self.settings), result)


if __name__ == '__main__':
    unittest.main()
