"""Explicit feature adaptations on an otherwise native, streaming Responses route."""
import json

from adapters.native_responses import NativeResponsesAdapter
from adapters.request_compat import normalize_history, progress_guidance
from adapters.response_schemas import (AdaptationSettings, AgentMessage, CustomArguments,
                                      CustomCall, CustomTool, StandaloneOutput, host_plaintext)


def validate_adaptations(value):
    try:
        return AdaptationSettings(adaptations=value).adaptations
    except ValueError:
        raise ValueError('INVALID_RESPONSES_ADAPTATIONS') from None


class MinimalResponsesAdapter(NativeResponsesAdapter):
    def __init__(self, adaptations, *, history_migration=False):
        super().__init__(history_migration=history_migration)
        self.adaptations = set(validate_adaptations(adaptations))
        self.custom = set()
        self.custom_ids = set()

    def request(self, original):
        request = super().request(original)
        if 'discovered_tools' in self.adaptations:
            def merge(values):
                result = {}
                for tool in values:
                    key = (tool.get('type'), tool.get('name'))
                    if key in result:
                        previous = result[key]
                        if key[0] == 'namespace':
                            tool['tools'] = merge(previous.get('tools', []) + tool.get('tools', []))
                        elif ({k:v for k,v in previous.items() if k != 'description'} !=
                              {k:v for k,v in tool.items() if k != 'description'}):
                            raise ValueError('CONFLICTING_DISCOVERED_TOOLS')
                    result[key] = tool
                return list(result.values())
            discovered = [tool for item in request.get('input', [])
                          if item.get('type') in {'additional_tools','tool_search_output'}
                          for tool in item.get('tools', [])]
            request['tools'] = merge(request.get('tools', []) + discovered)
            request['input'] = [item for item in request.get('input', []) if item.get('type') != 'additional_tools']
        def tools(values, namespace=None):
            for tool in values:
                if tool.get('type') == 'namespace':
                    tools(tool.get('tools', []), tool['name'])
                elif tool.get('type') == 'custom' and 'custom_tools' in self.adaptations:
                    CustomTool.model_validate(tool)
                    self.custom.add((namespace, tool['name']))
                    tool['type'] = 'function'
                    original_format = tool.pop('format', None)
                    if original_format:
                        tool['description'] = (tool.get('description', '') +
                            '\nInput constraint metadata (do NOT pass this metadata as the tool input): ' + json.dumps(original_format))
                    tool['parameters'] = {'type':'object', 'properties':{'input':{'type':'string',
                        'description':'The actual raw tool payload requested by the task. Never pass the format, schema, or grammar definition itself.'}},
                        'required':['input'], 'additionalProperties':False}
        tools(request.get('tools', []))
        for item in request.get('input', []):
            if item.get('type') in {'additional_tools', 'tool_search_output'}:
                tools(item.get('tools', []))
        converted = []
        for item in request.get('input', []):
            kind = item.get('type')
            if kind == 'agent_message' and 'agent_messages' in self.adaptations:
                try:
                    message = AgentMessage.model_validate(item)
                except ValueError:
                    error = ValueError('UNSUPPORTED_AGENT_MESSAGE_CONTENT')
                    error.code = 'UNSUPPORTED_AGENT_MESSAGE_CONTENT'
                    parts = item.get('content')
                    shapes = []
                    for part in parts if isinstance(parts, list) else []:
                        if not isinstance(part, dict):
                            shapes.append('non_object')
                            continue
                        kind = part.get('type')
                        if kind == 'encrypted_content':
                            value = part.get('encrypted_content')
                            shape = ('ciphertext' if isinstance(value, str) and value.startswith('gAAAA') else
                                     'readable' if host_plaintext(value) else
                                     'opaque_string' if isinstance(value, str) else 'non_string')
                            shapes.append('encrypted_content:' + shape)
                        else:
                            shapes.append(kind if kind in {'input_text','text','output_text'} else 'other')
                    error.agent_content_shapes = sorted(set(shapes))
                    raise error from None
                parts = [part.text for part in message.content]
                item = {'type':'message','role':'user','content':[{'type':'input_text','text':'\n'.join(parts)}]}
            elif (kind in {'function_call_output', 'custom_tool_call_output'}
                    and not item.get('call_id') and isinstance(item.get('name'), str)
                    and 'standalone_outputs' in self.adaptations):
                StandaloneOutput.model_validate(item)
                # Reuse only the standalone-output conversion, not portable history normalization.
                item = normalize_history({'input':[item]}, portable=True)['input'][0]
            elif kind == 'custom_tool_call' and 'custom_tools' in self.adaptations:
                CustomCall.model_validate(item)
                if (item.get('namespace'), item.get('name')) not in self.custom:
                    raise ValueError('UNREGISTERED_CUSTOM_TOOL_HISTORY')
                item['type'] = 'function_call'
                item['arguments'] = json.dumps({'input':item.pop('input')})
            elif kind == 'custom_tool_call_output' and 'custom_tools' in self.adaptations:
                item['type'] = 'function_call_output'
            converted.append(item)
        request['input'] = converted
        guidance = progress_guidance(original)
        if guidance:
            request['instructions'] = (request.get('instructions') or '') + guidance
        return request

    def stream_events(self, original):
        event = super().stream_events(original)[0]
        kind = event.get('type', '')
        if (kind.startswith('response.function_call_arguments.')
                and event.get('item_id') in self.custom_ids):
            return []  # JSON wrapper deltas are not raw custom-tool input.
        def restore(item):
            if (item.get('type') != 'function_call'
                    or (item.get('namespace'), item.get('name')) not in self.custom):
                return
            if item.get('id'):
                self.custom_ids.add(item['id'])
            arguments = item.pop('arguments', '')
            if kind == 'response.output_item.added':
                raw = ''
            else:
                try:
                    raw = CustomArguments.model_validate_json(arguments).input
                except ValueError:
                    raise ValueError('INVALID_CUSTOM_TOOL_INPUT') from None
            item.update(type='custom_tool_call', input=raw)
        if 'item' in event:
            restore(event['item'])
        for item in event.get('response', {}).get('output', []):
            restore(item)
        return [event]
