import copy
import unittest

from adapters.chat import ChatAdapter
from adapters.request_compat import inline_history, normalize_history
from adapters.responses import ResponsesAdapter


class HistoryIDTests(unittest.TestCase):
    def test_external_greeting_can_be_replayed_as_inline_official_history(self):
        adapter = ChatAdapter('vendor/model')
        history = {'input': [
            {'type': 'message', 'role': 'user', 'content': '你好'},
            {'type': 'message', 'id': adapter.text_id, 'role': 'assistant',
             'content': [{'type': 'output_text', 'text': '你好！', 'annotations': []}]},
            {'type': 'message', 'role': 'user', 'content': '你是什么模型'},
        ]}
        before = copy.deepcopy(history)
        converted = normalize_history(history)
        self.assertNotIn('id', converted['input'][1])
        self.assertEqual(converted['input'][1]['content'], history['input'][1]['content'])
        self.assertEqual(history, before)

    def test_tool_pairs_and_nested_resource_ids_survive_responses_conversion(self):
        request = {'tools': [{'type': 'function', 'name': 'lookup', 'parameters': {}}], 'input': [
            {'type': 'function_call', 'id': 'fc_foreign', 'call_id': 'call_1',
             'name': 'lookup', 'arguments': '{"id":"business-id"}'},
            {'type': 'function_call_output', 'id': 'out_foreign', 'call_id': 'call_1',
             'output': '{"id":"result-id"}'},
            {'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_image', 'file_id': 'file_1'}]},
        ]}
        converted = ResponsesAdapter().request(request)
        for item in converted['input'][:2]:
            self.assertNotIn('id', item)
            self.assertEqual(item['call_id'], 'call_1')
        self.assertEqual(converted['input'][0]['arguments'], request['input'][0]['arguments'])
        self.assertEqual(converted['input'][2], request['input'][2])

    def test_encrypted_reasoning_payload_survives(self):
        request = {'input': [{'type': 'reasoning', 'id': 'rs_foreign',
                             'encrypted_content': 'gAAAAencrypted', 'summary': []}]}
        self.assertEqual(normalize_history(request)['input'], [
            {'type': 'reasoning', 'encrypted_content': 'gAAAAencrypted', 'summary': []}])

    def test_references_are_not_silently_discarded(self):
        request = {'input': [{'type': 'item_reference', 'id': 'msg_ref'}, {'id': 'msg_ref2'}]}
        self.assertEqual(inline_history(request), request)
        self.assertEqual(inline_history({'input': 'hello'}), {'input': 'hello'})


if __name__ == '__main__':
    unittest.main()
