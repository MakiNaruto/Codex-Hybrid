"""Native collaboration wire mapping, independent of portable conversion."""
import copy
import json
import unittest

from adapters.coordination import NativeCoordinationAdapter, plaintext_collaboration_schema


class CoordinationTests(unittest.TestCase):
    def spawn(self, model='vendor/model', **arguments):
        return {'type': 'function_call', 'id': 'fc1', 'call_id': 'call1',
                'namespace': 'connected_agent_bridge', 'name': 'spawn_agent',
                'arguments': json.dumps({'task_name': 'worker', 'model': model, **arguments})}

    def test_schema_mapping_preserves_original_and_native_ciphertext(self):
        tool = {'type': 'namespace', 'name': 'collaboration', 'tools': [
            {'type': 'function', 'name': 'send_message', 'parameters': {
                'properties': {'message': {'type': 'string', 'encrypted': True}}}}]}
        original = {'tools': [tool], 'input': [
            {'type': 'additional_tools', 'tools': [copy.deepcopy(tool)]},
            {'type': 'function_call', 'namespace': 'collaboration', 'name': 'send_message'},
            {'type': 'agent_message', 'content': [
                {'type': 'encrypted_content', 'encrypted_content': 'Readable task'},
                {'type': 'encrypted_content', 'encrypted_content': 'gAAAAciphertext'}]}]}
        before = copy.deepcopy(original)
        result = plaintext_collaboration_schema(original)
        for mapped in (result['tools'][0], result['input'][0]['tools'][0]):
            self.assertEqual(mapped['name'], 'connected_agent_bridge')
            self.assertNotIn('encrypted', mapped['tools'][0]['parameters']['properties']['message'])
        self.assertEqual(result['input'][1]['namespace'], 'connected_agent_bridge')
        self.assertEqual(result['input'][2]['content'], [
            {'type': 'input_text', 'text': 'Readable task'},
            {'type': 'encrypted_content', 'encrypted_content': 'gAAAAciphertext'}])
        self.assertEqual(original, before)

    def test_external_spawn_identity_is_stable_across_terminal_events(self):
        adapter = NativeCoordinationAdapter({'vendor/model'})
        item = self.spawn()
        original = {'type': 'response.output_item.done', 'item': item}
        before = copy.deepcopy(original)
        mapped = adapter.event(original)['item']
        name = json.loads(mapped['arguments'])['task_name']
        self.assertTrue(name.startswith('worker_run_'))
        completed = adapter.event({'type': 'response.completed', 'response': {'output': [item]}})
        self.assertEqual(json.loads(completed['response']['output'][0]['arguments'])['task_name'], name)
        self.assertEqual(mapped['namespace'], 'collaboration')
        self.assertEqual(original, before)
        other = NativeCoordinationAdapter({'vendor/model'}).event(original)['item']
        self.assertNotEqual(json.loads(other['arguments'])['task_name'], name)

    def test_only_tracked_spawn_argument_deltas_are_suppressed(self):
        adapter = NativeCoordinationAdapter('vendor/model')
        item = self.spawn()
        item['arguments'] = ''
        adapter.event({'type': 'response.output_item.added', 'item': item})
        delta = {'type': 'response.function_call_arguments.delta', 'item_id': 'fc1', 'delta': '{}'}
        self.assertIsNone(adapter.event(delta))
        unrelated = dict(delta, item_id='fc2')
        self.assertEqual(adapter.event(unrelated), unrelated)

    def test_official_spawns_and_existing_target_arguments_remain_unchanged(self):
        adapter = NativeCoordinationAdapter('vendor/model')
        for item in (self.spawn('gpt-official'), dict(self.spawn(), name='send_message'),
                     self.spawn(task_name='invalid-name')):
            with self.subTest(item=item):
                result = adapter.event({'type': 'response.output_item.done', 'item': item})['item']
                self.assertEqual(result['arguments'], item['arguments'])
                self.assertEqual(result['namespace'], 'collaboration')
