import copy
import io
import json
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch

from adapters.chat import ChatAdapter
from adapters.responses import ResponsesAdapter, UnregisteredToolError
from adapters.native_responses import NativeResponsesAdapter
from gateway.server import adapted_stream, sse_events
from gateway.transport import records
from management.service import Management
from model_catalog.catalog import ConfigError


class PortableHistoryTests(unittest.TestCase):
    """The explicit portable Responses bridge and Chat conversion share these rules."""
    def test_host_delivered_outputs_without_call_identity_become_context_for_both_protocols(self):
        body = {'model': 'test', 'tools': [], 'input': [
            {'type': 'function_call_output', 'namespace': 'host', 'name': 'delegate',
             'output': 'Remember HOST_71'},
            {'role': 'assistant', 'content': 'HOST_71'},
            {'type': 'custom_tool_call_output', 'name': 'notification', 'output': {'text': 'Repeat the code'}}]}
        before = copy.deepcopy(body)
        responses = ResponsesAdapter().request(body)
        self.assertEqual([i.get('role') for i in responses['input']], ['user', 'assistant', 'user'])
        self.assertIn('host.delegate', responses['input'][0]['content'][0]['text'])
        self.assertIn('Remember HOST_71', responses['input'][0]['content'][0]['text'])
        chat = ChatAdapter('test').request(body)
        self.assertEqual([i['role'] for i in chat['messages']], ['user', 'assistant', 'user'])
        self.assertIn('Repeat the code', chat['messages'][2]['content'])
        self.assertEqual(body, before)

    def test_developer_tool_metadata_is_not_treated_as_system_text(self):
        body = {'tools': [], 'input': [
            {'type': 'additional_tools', 'role': 'developer', 'tools': [
                {'type': 'function', 'name': 'lookup', 'parameters': {}}]},
            {'role': 'developer', 'content': 'Instruction'},
            {'role': 'user', 'content': 'Hello'}]}
        before = copy.deepcopy(body)
        result = ResponsesAdapter().request(body)
        self.assertEqual(result['instructions'], 'Instruction')
        self.assertEqual(result['tools'][0]['name'], 'lookup')
        self.assertEqual(result['input'], [{'role': 'user', 'content': 'Hello'}])
        self.assertEqual(body, before)

    def test_system_instructions_are_consolidated_before_conversation_for_both_protocols(self):
        body = {'model': 'test', 'instructions': 'ROOT', 'tools': [], 'input': [
            {'role': 'system', 'content': 'SYSTEM'},
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hello'},
            {'role': 'developer', 'content': [{'type': 'input_text', 'text': 'LATEST_CONTEXT'}]},
            {'role': 'user', 'content': 'Continue'}]}
        before = copy.deepcopy(body)
        responses = ResponsesAdapter().request(body)
        self.assertEqual(responses['instructions'], 'ROOT\n\nSYSTEM\n\nLATEST_CONTEXT')
        self.assertEqual([i['role'] for i in responses['input']], ['user', 'assistant', 'user'])
        chat = ChatAdapter('test').request(body)
        self.assertEqual([i['role'] for i in chat['messages']], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(chat['messages'][0]['content'], responses['instructions'])
        self.assertEqual(body, before)

    def test_both_protocols_preserve_plaintext_without_foreign_reasoning_objects(self):
        body = {'model': 'test', 'tools': [], 'input': [
            {'type': 'reasoning', 'encrypted_content': 'opaque-private-state',
             'summary': [{'type': 'summary_text', 'text': 'Historical summary'}]},
            {'type': 'reasoning', 'content': [{'type': 'reasoning_text', 'text': 'Historical text'}]},
            {'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text', 'text': 'ANSWER'}]},
        ]}
        before = copy.deepcopy(body)
        responses = ResponsesAdapter().request(body)
        self.assertFalse(any(i.get('type') == 'reasoning' for i in responses['input']))
        self.assertIn('Historical summary', json.dumps(responses))
        self.assertIn('Historical text', json.dumps(responses))
        self.assertNotIn('opaque-private-state', json.dumps(responses))
        chat = ChatAdapter('test').request(body)
        self.assertIn('Historical summary', json.dumps(chat))
        self.assertIn('Historical text', json.dumps(chat))
        self.assertEqual(body, before)

    def test_opaque_only_state_is_not_transferred_but_answer_remains(self):
        body = {'tools': [], 'input': [
            {'type': 'reasoning', 'encrypted_content': 'gAAAA-private', 'summary': []},
            {'role': 'assistant', 'content': 'ANSWER'}]}
        self.assertEqual(ResponsesAdapter().request(body)['input'], [body['input'][1]])

    def test_reasoning_normalization_keeps_tool_call_pairs_and_ids(self):
        body = {'model': 'test', 'tools': [{'type': 'function', 'name': 'lookup', 'parameters': {}}],
                'input': [{'type': 'reasoning', 'encrypted_content': 'opaque', 'summary': []},
                          {'type': 'function_call', 'call_id': 'c1', 'name': 'lookup', 'arguments': '{}'},
                          {'type': 'function_call_output', 'call_id': 'c1', 'output': 'result'}]}
        responses = ResponsesAdapter().request(body)
        self.assertEqual([i['call_id'] for i in responses['input']], ['c1', 'c1'])
        chat = ChatAdapter('test').request(body)
        self.assertEqual(chat['messages'][0]['tool_calls'][0]['id'], 'c1')
        self.assertEqual(chat['messages'][1], {'role': 'tool', 'tool_call_id': 'c1', 'content': 'result'})


class HistoricalToolBindingTests(unittest.TestCase):
    def body(self, kind='custom', namespaces=('functions',), call_namespace=None):
        call = {'type': kind + '_tool_call' if kind == 'custom' else 'function_call',
                'name': 'exec', 'call_id': 'history_1'}
        call.update({'input': 'print(137*29)'} if kind == 'custom' else {'arguments': '{"n":137}'})
        if call_namespace is not None:
            call['namespace'] = call_namespace
        return {'model': 'test', 'tools': [], 'input': [
            {'type': 'additional_tools', 'tools': [
                {'type': 'namespace', 'name': ns, 'tools': [
                    {'type': kind, 'name': 'exec', 'parameters': {'type': 'object'}}]}
                for ns in namespaces]}, call,
            {'type': 'custom_tool_call_output' if kind == 'custom' else 'function_call_output',
             'call_id': 'history_1', 'output': '3973'}]}

    def test_missing_namespace_preserves_call_result_pairs_in_both_protocols(self):
        for kind in ('custom', 'function'):
            with self.subTest(kind=kind):
                body = self.body(kind)
                before = copy.deepcopy(body)
                adapter = ResponsesAdapter()
                result = adapter.request(body)
                call, output = result['input']
                self.assertEqual(call['name'], 'functions__exec')
                self.assertEqual(call['type'], 'function_call')
                self.assertEqual((call['call_id'], output['call_id']), ('history_1', 'history_1'))
                self.assertEqual(output['output'], '3973')
                expected = {'input': 'print(137*29)'} if kind == 'custom' else {'n': 137}
                self.assertEqual(json.loads(call['arguments']), expected)
                self.assertEqual(adapter.call_bindings['history_1']['namespace'], 'functions')
                chat = ChatAdapter('test').request(body)
                self.assertEqual(chat['messages'][0]['tool_calls'][0]['function']['name'], 'functions__exec')
                self.assertEqual(chat['messages'][1]['tool_call_id'], 'history_1')
                self.assertEqual(body, before)
                self.assertEqual(NativeResponsesAdapter().request(body), before)

    def test_ambiguous_missing_namespace_is_rejected(self):
        for kind in ('custom', 'function'):
            for adapter in (ResponsesAdapter(), ChatAdapter('test')):
                with self.subTest(kind=kind, protocol=type(adapter).__name__):
                    with self.assertRaises(UnregisteredToolError):
                        adapter.request(self.body(kind, namespaces=('one', 'two')))

    def test_explicit_namespace_selects_exact_binding_and_never_falls_back(self):
        result = ResponsesAdapter().request(self.body(namespaces=('one', 'two'), call_namespace='two'))
        self.assertEqual(result['input'][0]['name'], 'two__exec')
        with self.assertRaises(UnregisteredToolError):
            ResponsesAdapter().request(self.body(call_namespace='unknown'))

    def test_unknown_name_or_mismatched_tool_kind_is_rejected(self):
        unknown = self.body()
        unknown['input'][1]['name'] = 'unregistered'
        wrong_kind = self.body()
        wrong_kind['input'][0]['tools'][0]['tools'][0]['type'] = 'function'
        exact_wrong_kind = self.body(call_namespace='functions')
        exact_wrong_kind['input'][0]['tools'][0]['tools'][0]['type'] = 'function'
        for body in (unknown, wrong_kind, exact_wrong_kind):
            with self.subTest(body=body):
                with self.assertRaises(UnregisteredToolError):
                    ResponsesAdapter().request(body)


class ToolRegistryTests(unittest.TestCase):
    def test_history_description_updates_keep_latest_text_without_changing_schema(self):
        first = {'type': 'function', 'name': 'lookup', 'description': 'Earlier guidance',
                 'parameters': {'type': 'object', 'properties': {'n': {'type': 'integer'}}}}
        latest = dict(first, description='Current guidance')
        body = {'model': 'test', 'tools': [], 'input': [
            {'type': 'additional_tools', 'tools': [first]},
            {'type': 'additional_tools', 'tools': [latest]},
            {'type': 'function_call', 'name': 'lookup', 'call_id': 'c1', 'arguments': '{"n":7}'},
            {'type': 'function_call_output', 'call_id': 'c1', 'output': '49'}]}
        before = copy.deepcopy(body)
        responses = ResponsesAdapter().request(body)
        self.assertEqual(responses['tools'], [latest])
        self.assertEqual(responses['input'][0]['call_id'], 'c1')
        chat = ChatAdapter('test').request(body)
        self.assertEqual(chat['tools'][0]['function']['description'], 'Current guidance')
        self.assertEqual(body, before)

    def test_duplicate_tool_schemas_still_must_agree(self):
        body = {'model': 'test', 'tools': [{'type': 'function', 'name': 'lookup', 'parameters': {
            'type': 'object', 'properties': {'n': {'type': 'integer'}}}}], 'input': [
            {'type': 'additional_tools', 'tools': [{'type': 'function', 'name': 'lookup',
                'parameters': {'type': 'object', 'properties': {'n': {'type': 'string'}}}}]}]}
        for adapter in (ResponsesAdapter(), ChatAdapter('test')):
            with self.subTest(protocol=type(adapter).__name__):
                with self.assertRaisesRegex(ValueError, 'Conflicting tool definitions'):
                    adapter.request(body)

    def test_process_wait_is_not_advertised_as_agent_coordination(self):
        body = {'input': [], 'tools': [{'type': 'namespace', 'name': 'functions', 'tools': [
            {'type': 'function', 'name': 'wait', 'parameters': {
                'type': 'object', 'properties': {'cell_id': {'type': 'string'}}}}]},
            {'type': 'namespace', 'name': 'collaboration', 'tools': [
                {'type': 'function', 'name': 'wait_agent', 'parameters': {
                    'type': 'object', 'properties': {'timeout_ms': {'type': 'integer'}}}}]}]}
        result = ResponsesAdapter().request(body)
        self.assertIn('collaboration__wait_agent', result['instructions'])
        self.assertNotIn('functions__wait', result['instructions'])

    def test_guidance_and_calls_use_the_same_registered_alias(self):
        adapter = ResponsesAdapter()
        body = {'instructions': 'Keep this instruction.', 'input': [], 'tools': [
            {'type': 'namespace', 'name': 'worker_tools', 'tools': [
                {'type': 'function', 'name': 'spawn_agent', 'parameters': {'type': 'object'}}]}]}
        result = adapter.request(body)
        self.assertIn('Keep this instruction.', result['instructions'])
        self.assertIn('worker_tools__spawn_agent', result['instructions'])
        self.assertEqual(result['tools'][0]['name'], 'worker_tools__spawn_agent')
        call = adapter.item({'type': 'function_call', 'name': 'worker_tools__spawn_agent',
                             'call_id': 'call_1', 'arguments': '{}'})
        self.assertEqual((call['namespace'], call['name']), ('worker_tools', 'spawn_agent'))

    def test_ambiguous_short_names_are_not_guessed(self):
        adapter = ResponsesAdapter()
        adapter.request({'input': [], 'tools': [
            {'type': 'namespace', 'name': ns, 'tools': [
                {'type': 'function', 'name': 'spawn_agent', 'parameters': {}}]}
            for ns in ('one', 'two')]})
        with self.assertRaises(ValueError):
            adapter.item({'type': 'function_call', 'name': 'spawn_agent',
                          'call_id': 'call_1', 'arguments': '{}'})


class StreamFramingTests(unittest.TestCase):
    def test_management_reports_explicit_upstream_failure_not_early_eof(self):
        adapter = ResponsesAdapter()
        gateway = SimpleNamespace(settings={'official_models': [], 'models': ['test'],
                                           'source': {'type': 'yaml'}}, slots=threading.Semaphore(1),
                                  opener=SimpleNamespace(open=lambda *a, **kw: io.BytesIO(
                                      b'data: {"code":"invalid_request_error","message":"private"}\n\n')))
        manager = SimpleNamespace(gateway=gateway, sse_events=sse_events,
                                  route=lambda *a: ('https://example.invalid', {}, {}, adapter.event))
        catalog = SimpleNamespace(select=lambda key: ({'max_output_tokens': 128}, {}))
        with patch('management.service.load_source', return_value=catalog):
            with self.assertRaises(ConfigError) as caught:
                Management.test_connection(manager, 'test')
        self.assertEqual(caught.exception.code, 'UPSTREAM_STREAM_ERROR')
        self.assertTrue(gateway.slots.acquire(blocking=False))

    def test_event_field_supplies_type_and_multiline_data_survives(self):
        wire = b'\xef\xbb\xbfevent: response.completed\r\ndata: {"response":\r\ndata: {"status":"completed","output":[]}}\r\n\r\n'
        expected = [{'type': 'response.completed', 'response': {'status': 'completed', 'output': []}}]
        self.assertEqual(list(sse_events(io.BytesIO(wire))), expected)
        self.assertEqual(list(records(io.BytesIO(wire))), expected)

    def test_explicit_error_is_terminal_and_sanitized_for_both_protocols(self):
        for adapter in (ResponsesAdapter(), ChatAdapter('test')):
            with self.subTest(adapter=type(adapter).__name__):
                wire = b'event: error\ndata: {"code":"invalid_request_error","message":"private prompt"}\n\n'
                events = list(adapted_stream(io.BytesIO(wire), adapter.event))
                self.assertEqual(events[-1][1]['type'], 'response.failed')
                self.assertNotIn('private prompt', json.dumps(events[-1][1]))
                self.assertEqual(events[-1][1]['response']['error']['code'], 'invalid_request_error')
                self.assertTrue(events[-1][1]['response']['id'].startswith('resp_'))

    def test_untyped_error_envelope_is_not_silently_ignored(self):
        wire = b'data: {"error":{"code":"invalid_request_error","message":"secret"}}\n\n'
        result = list(adapted_stream(io.BytesIO(wire), ResponsesAdapter().event))
        self.assertEqual(result[-1][1]['type'], 'response.failed')

    def test_eof_and_done_do_not_invent_success(self):
        for ending in (b'', b'data: [DONE]\n\n'):
            wire = b'data: {"type":"response.in_progress"}\n\n' + ending
            result = list(adapted_stream(io.BytesIO(wire), ResponsesAdapter().event))
            self.assertFalse(any(e['type'] == 'response.completed' for _, e in result))

    def test_terminal_does_not_wait_for_eof(self):
        def stream():
            yield b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n'
            yield b'\n'
            raise AssertionError('read after terminal')
        self.assertEqual(len(list(adapted_stream(stream(), ResponsesAdapter().event))), 1)

    def test_protocol_mismatch_is_explicit(self):
        for adapter, event in [(ResponsesAdapter(), {'choices': []}),
                               (ChatAdapter('test'), {'type': 'response.created', 'response': {}})]:
            with self.subTest(adapter=type(adapter).__name__):
                with self.assertRaisesRegex(ValueError, 'UPSTREAM_PROTOCOL_MISMATCH'):
                    adapter.event(event)

    def test_non_object_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'INVALID_STREAM_PAYLOAD'):
            list(sse_events(io.BytesIO(b'data: []\n\n')))

    def test_terminal_failure_preserves_identity_and_sanitizes_error(self):
        original = {'type': 'response.failed', 'response': {
            'id': 'resp_known', 'status': 'failed', 'output': [],
            'error': {'code': 'invalid_request_error', 'message': 'private'}}}
        result = ResponsesAdapter().event(original)
        self.assertEqual(result['response']['id'], 'resp_known')
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(original['response']['error']['message'], 'private')


if __name__ == '__main__':
    unittest.main()
