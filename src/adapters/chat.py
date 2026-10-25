"""Translate native Responses events/tools to streaming Chat Completions and back."""
import copy
import json
import time
import uuid

from adapters.responses import ResponsesAdapter


class ChatAdapter:
    def __init__(self, client_model):
        self.native = ResponsesAdapter()
        self.client_model = client_model
        self.response_id = 'resp_' + uuid.uuid4().hex
        self.text_id = 'msg_' + uuid.uuid4().hex
        self.created = False
        self.text_started = False
        self.text = ''
        self.calls = {}
        self.done = False
        self.usage = {}
        self.returned_model = None

    def request(self, original):
        converted = self.native.request(original)
        messages = []
        if converted.get('instructions'):
            messages.append({'role': 'system', 'content': converted['instructions']})
        for item in converted.get('input', []):
            kind = item.get('type')
            if kind in {'message', None} and item.get('role'):
                content = item.get('content', '')
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if part.get('type') not in {'input_text', 'output_text', 'text'}:
                            raise ValueError('Unsupported Chat Completions message modality')
                        parts.append(part['text'])
                    content = '\n'.join(parts)
                messages.append({'role': 'system' if item['role'] == 'developer' else item['role'],
                                 'content': content})
            elif kind == 'function_call':
                call = {'id': item['call_id'], 'type': 'function', 'function': {
                    'name': item['name'], 'arguments': item['arguments']}}
                if not messages or messages[-1]['role'] != 'assistant' or 'tool_calls' not in messages[-1]:
                    messages.append({'role': 'assistant', 'content': None, 'tool_calls': []})
                messages[-1]['tool_calls'].append(call)
            elif kind == 'function_call_output':
                output = item.get('output', '')
                messages.append({'role': 'tool', 'tool_call_id': item['call_id'],
                                 'content': output if isinstance(output, str) else json.dumps(output)})
            elif kind == 'reasoning':
                continue  # OpenAI reasoning is not transferable to other providers.
            else:
                raise ValueError('Unsupported native history item')
        result = {'model': converted['model'], 'messages': messages, 'stream': True}
        if converted['tools']:
            result['tools'] = [{'type': 'function', 'function': {k: v for k, v in tool.items() if k != 'type'}}
                               for tool in converted['tools']]
        return result

    def response(self, status='in_progress', output=None):
        value = {'id': self.response_id, 'object': 'response', 'created_at': int(time.time()),
                 'status': status, 'model': self.client_model, 'output': output or []}
        if self.returned_model:
            value['metadata'] = {'connected_upstream_model': self.returned_model}
        return value

    def event(self, chunk):
        if self.done:
            return []
        if chunk.get('error'):
            raise ValueError('Upstream Chat Completions error')
        self.returned_model = chunk.get('model', self.returned_model)
        self.usage = chunk.get('usage') or self.usage
        events = []
        if not self.created:
            self.created = True
            events.append({'type': 'response.created', 'response': self.response()})
        for choice in chunk.get('choices', []):
            if choice.get('index', 0) != 0:
                raise ValueError('Multiple choices are unsupported')
            delta = choice.get('delta') or {}
            text = delta.get('content')
            if text:
                if not self.text_started:
                    self.text_started = True
                    events.extend([
                        {'type': 'response.output_item.added', 'output_index': 0,
                         'item': {'id': self.text_id, 'type': 'message', 'role': 'assistant',
                                  'status': 'in_progress', 'content': []}},
                        {'type': 'response.content_part.added', 'item_id': self.text_id,
                         'output_index': 0, 'content_index': 0,
                         'part': {'type': 'output_text', 'text': '', 'annotations': []}}])
                self.text += text
                events.append({'type': 'response.output_text.delta', 'item_id': self.text_id,
                    'output_index': 0, 'content_index': 0, 'delta': text})
            for call in delta.get('tool_calls', []):
                current = self.calls.setdefault(call['index'], {'id': '', 'type': 'function_call',
                    'call_id': '', 'name': '', 'arguments': ''})
                if call.get('id'):
                    current['call_id'] = call['id']
                    current['id'] = 'fc_' + call['id']
                for key in ['name', 'arguments']:
                    current[key] += call.get('function', {}).get(key, '')
            reason = choice.get('finish_reason')
            if reason is not None:
                events.extend(self.finish(reason))
        return events

    def finish(self, reason):
        if reason not in {'stop', 'tool_calls', 'length'}:
            raise ValueError('Chat Completions output truncated or refused')
        truncated = reason == 'length'
        if not truncated and bool(self.calls) != (reason == 'tool_calls'):
            raise ValueError('Inconsistent tool completion')
        output, events = [], []
        if self.text_started:
            part = {'type': 'output_text', 'text': self.text, 'annotations': []}
            item = {'id': self.text_id, 'type': 'message', 'role': 'assistant',
                    'status': 'incomplete' if truncated else 'completed', 'content': [part]}
            output.append(item)
            events.extend([
                {'type': 'response.output_text.done', 'item_id': self.text_id,
                 'output_index': 0, 'content_index': 0, 'text': self.text},
                {'type': 'response.content_part.done', 'item_id': self.text_id,
                 'output_index': 0, 'content_index': 0, 'part': part},
                {'type': 'response.output_item.done', 'output_index': 0, 'item': item}])
        # Validate all calls before emitting any executable tool item.
        translated = []
        for index in ([] if truncated else sorted(self.calls)):
            call = copy.deepcopy(self.calls[index])
            if not call['call_id'] or not isinstance(json.loads(call['arguments']), dict):
                raise ValueError('Invalid tool call')
            call['status'] = 'completed'
            translated.append(self.native.item(call))
        for item in translated:
            index = len(output)
            empty = copy.deepcopy(item)
            empty['status'] = 'in_progress'
            if empty['type'] == 'custom_tool_call':
                empty['input'] = ''
            elif empty['type'] == 'tool_search_call':
                empty['arguments'] = {}
            else:
                empty['arguments'] = ''
            events.extend([{'type': 'response.output_item.added', 'output_index': index, 'item': empty},
                           {'type': 'response.output_item.done', 'output_index': index, 'item': item}])
            output.append(item)
        final = self.response('incomplete' if truncated else 'completed', output)
        if truncated:
            final['incomplete_details'] = {'reason': 'max_output_tokens'}
        final['usage'] = {'input_tokens': self.usage.get('prompt_tokens', 0),
                          'output_tokens': self.usage.get('completion_tokens', 0),
                          'total_tokens': self.usage.get('total_tokens', 0)}
        events.append({'type': 'response.incomplete' if truncated else 'response.completed', 'response': final})
        self.done = True
        return events
