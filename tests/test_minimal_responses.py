import copy
import json
import unittest
import threading
import urllib.request
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from adapters.minimal_responses import MinimalResponsesAdapter, validate_adaptations
from model_catalog.sources import apply_preferences, source_key
from model_catalog.catalog import Catalog, ConfigError


class MinimalResponsesTests(unittest.TestCase):
    def body(self):
        return {'model':'vendor/model', 'stream':True, 'reasoning':{'effort':'low'},
            'input':[], 'tools':[{'type':'namespace','name':'host','tools':[
                {'type':'custom','name':'exec','format':{'type':'text'}},
                {'type':'function','name':'lookup','parameters':{'type':'object'}}]}]}

    def test_custom_conversion_preserves_other_native_structures_and_restores_calls(self):
        body = self.body()
        body['input'] = [{'type':'custom_tool_call','name':'exec','namespace':'host',
            'call_id':'c1','input':'raw()'}, {'type':'custom_tool_call_output','call_id':'c1','output':'ok'},
            {'type':'reasoning','encrypted_content':'opaque'},
            {'type':'message','role':'assistant','phase':'commentary','content':[]}]
        before = copy.deepcopy(body)
        adapter = MinimalResponsesAdapter(['custom_tools'])
        payload = adapter.request(body)
        self.assertEqual(body, before)
        self.assertEqual(payload['input'][2:], body['input'][2:])
        self.assertEqual(payload['reasoning'], body['reasoning'])
        self.assertEqual(payload['tools'][0]['tools'][1], body['tools'][0]['tools'][1])
        self.assertEqual(json.loads(payload['input'][0]['arguments']), {'input':'raw()'})
        self.assertEqual(payload['input'][1]['type'], 'function_call_output')
        item = {'type':'function_call','id':'f1','call_id':'c2','name':'exec','namespace':'host','arguments':''}
        added = adapter.stream_events({'type':'response.output_item.added','item':item})[0]
        self.assertEqual(added['item']['type'], 'custom_tool_call')
        self.assertEqual(adapter.stream_events({'type':'response.function_call_arguments.delta','item_id':'f1','delta':'bad wrapper'}), [])
        native_delta = {'type':'response.function_call_arguments.delta','item_id':'lookup','delta':'{}'}
        self.assertEqual(adapter.stream_events(native_delta), [native_delta])
        item['arguments'] = json.dumps({'input':'raw()'})
        done = adapter.stream_events({'type':'response.output_item.done','item':item})[0]
        final = adapter.stream_events({'type':'response.completed','response':{'output':[item]}})[0]
        self.assertEqual(done['item']['input'], 'raw()')
        self.assertEqual(final['response']['output'][0], done['item'])
        item['arguments'] = '{"input":123}'
        with self.assertRaises(ValueError):
            adapter.stream_events({'type':'response.output_item.done','item':item})

    def test_message_adaptations_do_not_normalize_unrelated_history(self):
        body = self.body()
        body['input'] = [{'type':'agent_message','content':[{'type':'input_text','text':'NEW_TASK'}]},
            {'type':'function_call_output','name':'deliver','namespace':'host','output':'task'},
            {'type':'function_call_output','call_id':'paired','output':'result'},
            {'type':'reasoning','id':'rs1','encrypted_content':'opaque'}]
        adapter = MinimalResponsesAdapter(['agent_messages','standalone_outputs'])
        payload = adapter.request(body)
        self.assertEqual(payload['input'][0]['role'], 'user')
        self.assertIn('host.deliver', payload['input'][1]['content'][0]['text'])
        self.assertEqual(payload['input'][2:], body['input'][2:])
        self.assertEqual(payload['tools'], body['tools'])
        body['input'][0]['content'] = [{'type':'encrypted_content','encrypted_content':'opaque'}]
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_AGENT_MESSAGE_CONTENT'):
            adapter.request(body)

    def test_text_and_phase_are_forwarded_before_completion(self):
        adapter = MinimalResponsesAdapter(['custom_tools'])
        adapter.request(self.body())
        events = [{'type':'response.output_item.added','item':{'type':'message','phase':'commentary'}},
            {'type':'response.output_text.delta','delta':'working'}]
        for event in events:
            self.assertEqual(adapter.stream_events(event), [event])

    def test_discovered_tools_are_promoted_with_native_namespaces_and_conflict_checks(self):
        body = self.body()
        discovered = {'type':'namespace','name':'collaboration','tools':[
            {'type':'function','name':'spawn_agent','parameters':{'type':'object'}}]}
        body['input'] = [{'type':'additional_tools','tools':[discovered]},
            {'type':'tool_search_output','call_id':'search1','status':'completed','tools':[discovered]}]
        before = copy.deepcopy(body)
        payload = MinimalResponsesAdapter(['discovered_tools']).request(body)
        self.assertEqual(body,before)
        self.assertEqual(payload['tools'][-1],discovered)
        self.assertEqual(len(payload['tools'][-1]['tools']),1)
        self.assertEqual(payload['input'][0]['type'],'tool_search_output')
        self.assertEqual(payload['input'][0]['call_id'],'search1')
        body['input'][1]['tools'] = [copy.deepcopy(discovered)]
        body['input'][1]['tools'][0]['tools'][0]['parameters'] = {'type':'string'}
        with self.assertRaisesRegex(ValueError,'CONFLICTING_DISCOVERED_TOOLS'):
            MinimalResponsesAdapter(['discovered_tools']).request(body)

    def test_real_host_mixed_agent_spans_keep_task_and_report_opaque_content(self):
        body = self.body()
        body['input'] = [{'type':'agent_message','content':[
            {'type':'input_text','text':'Message Type: NEW_TASK'},
            {'type':'encrypted_content','encrypted_content':'Reply with REAL_TASK_OK.'}]}]
        before = copy.deepcopy(body)
        adapter = MinimalResponsesAdapter(['agent_messages'])
        payload = adapter.request(body)
        self.assertEqual(body,before)
        self.assertIn('Reply with REAL_TASK_OK.',payload['input'][0]['content'][0]['text'])
        self.assertIn('task delegated by a parent',payload['instructions'])
        body['input'][0]['content'][1]['encrypted_content'] = 'gAAAAsecret'
        with self.assertRaises(ValueError) as caught:
            adapter.request(body)
        self.assertEqual(caught.exception.code,'UNSUPPORTED_AGENT_MESSAGE_CONTENT')
        self.assertEqual(caught.exception.agent_content_shapes,['encrypted_content:ciphertext','input_text'])
        from management.diagnostics import safe_details
        details = safe_details({'error_code':caught.exception.code,'agent_content_shapes':[
            *caught.exception.agent_content_shapes, 'secret task body']})
        self.assertNotIn('secret',json.dumps(details))

    def test_preferences_are_explicit_and_validated(self):
        catalog = Catalog('unused', data={'version':1,'providers':{'vendor':{
            'protocol':'openai_responses','base_url':'https://test.invalid',
            'credentials':{'api_key':'dummy'},'models':{'model':{'model_id':'test'}}}}})
        source = {'type':'yaml','path':'unused'}
        settings = {'source':source,'model_preferences':{source_key(source):{
            'added':['vendor/model'], 'compatibility':{'vendor/model':'native'},
            'adaptations':{'vendor/model':['custom_tools']}}}}
        apply_preferences(catalog, settings)
        _, provider = catalog.select('vendor/model')
        self.assertEqual(provider['responses_adaptations'], ['custom_tools'])
        self.assertEqual(provider['responses_compatibility'], 'native')
        settings['model_preferences'][source_key(source)]['adaptations']['vendor/model'] = ['guess']
        with self.assertRaises(ConfigError):
            apply_preferences(catalog, settings)
        for value in (None, 'custom_tools', ['custom_tools','custom_tools'], [{}]):
            with self.assertRaises(ValueError):
                validate_adaptations(value)

    def test_gateway_delivers_text_while_upstream_is_still_running(self):
        from gateway.server import Gateway, Server
        gateway = Gateway({'source':{}, 'models':[], 'max_concurrent_requests':1,'local_token':'test-token'})
        gateway.record = lambda _: None
        gateway.opener = SimpleNamespace(open=lambda *args, **kwargs: nullcontext(object()))
        adapter = MinimalResponsesAdapter(['custom_tools'])
        adapter.request(self.body())
        release = threading.Event()
        def stream(*args):
            yield None, {'type':'response.output_text.delta','delta':'working'}
            if not release.wait(3):
                raise TimeoutError('Client did not receive text before completion')
            yield None, {'type':'response.completed','response':{'status':'completed'}}
        server = Server(('127.0.0.1',0), gateway.handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with patch('gateway.server.route', return_value=('https://test.invalid/responses',{}, {},adapter.stream_events)), \
                    patch('gateway.server.adapted_stream', side_effect=stream):
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/responses',
                    data=b'{"model":"test","stream":true,"input":[]}', headers={'X-Connected-Token':'test-token'})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=5) as response:
                    frame = b''.join(response.readline() for _ in range(3))
                    self.assertIn(b'working', frame)
                    self.assertFalse(release.is_set())
                    release.set()
                    self.assertIn(b'response.completed', response.read())
        finally:
            release.set()
            server.shutdown()
            server.server_close()
