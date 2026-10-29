"""Bridge Codex v2 additional_tools/namespaces to DeepSeek Responses tools.

Does not execute tools. The original Codex backend remains the executor.
"""
import copy
import json
import re

from adapters.request_compat import normalize_history, stream_error_event


class UnregisteredToolError(ValueError):
    def __init__(self, name):
        super().__init__('Upstream requested an unregistered tool')
        self.tool_name = name if isinstance(name, str) and re.fullmatch(r'[\w.:-]{0,128}', name) else '<invalid>'


class ResponsesAdapter:
    """Explicit portable compatibility bridge, also used by ChatAdapter.

    Native Responses routes use NativeResponsesAdapter instead.
    """
    def __init__(self):
        self.bindings = {}
        self.call_bindings = {}
        self.pending_added = {}

    def alias(self, namespace, name):
        alias = (namespace + '__' if namespace else '') + name
        if len(alias) > 128:
            raise ValueError('Tool alias exceeds DeepSeek limit')
        return alias

    def convert_tool(self, tool, namespace=None):
        if tool['type'] == 'tool_search':
            if tool.get('execution') != 'client' or not isinstance(tool.get('parameters'), dict):
                raise ValueError('Only client tool search with an explicit schema is supported')
            name = 'connected_native_tool_search'
            binding = {'namespace': None, 'name': name, 'type': 'tool_search'}
            if name in self.bindings and self.bindings[name] != binding:
                raise ValueError('Ambiguous tool name')
            self.bindings[name] = binding
            parameters = copy.deepcopy(tool['parameters'])
            self.strip_extensions(parameters)
            return [{'type': 'function', 'name': name,
                     'description': tool.get('description', 'Discover additional tools available in Codex.'),
                     'parameters': parameters}]
        if tool['type'] == 'namespace':
            result = []
            for nested in tool['tools']:
                result.extend(self.convert_tool(nested, tool['name']))
            return result
        if tool['type'] not in {'function', 'custom'}:
            raise ValueError('Unsupported tool type: '+tool['type'])
        name = self.alias(namespace, tool['name'])
        binding = {'namespace': namespace, 'name': tool['name'], 'type': tool['type']}
        if name in self.bindings and self.bindings[name] != binding:
            raise ValueError('Ambiguous tool name')
        self.bindings[name] = binding
        if tool['type'] == 'custom':
            parameters = {'type': 'object', 'properties': {'input': {'type': 'string',
                'description': 'The complete raw tool input, such as JavaScript source.'}},
                'required': ['input'], 'additionalProperties': False}
        else:
            parameters = copy.deepcopy(tool.get('parameters', {'type':'object','properties':{}}))
            self.strip_extensions(parameters)
        return [{'type':'function','name':name,'description':tool.get('description',''),
                 'parameters':parameters}]

    def strip_extensions(self, value):
        if isinstance(value, dict):
            value.pop('encrypted', None)
            schema_maps = {
                'properties', 'patternProperties', '$defs', 'definitions',
                'dependentSchemas', 'dependencies',
            }
            literal_data = {'default', 'examples', 'example', 'const', 'enum'}
            for key, nested in value.items():
                if key in literal_data:
                    continue
                if key in schema_maps and isinstance(nested, dict):
                    for schema in nested.values():
                        self.strip_extensions(schema)
                else:
                    self.strip_extensions(nested)
        elif isinstance(value, list):
            for nested in value:
                self.strip_extensions(nested)

    def request(self, original):
        request = normalize_history(original, portable=True)
        tools = self._register_request_tools(request)
        request['input'] = self._convert_history(request.get('input', []))
        unique = self._unique_tools(tools)
        request['tools'] = list(unique.values())
        instructions = self._coordination_instructions(request.get('instructions'), unique)
        if instructions is not None:
            request['instructions'] = instructions
        return request

    def _register_request_tools(self, request):
        """Register current and discovered tools before resolving historical calls."""
        tools = []
        for tool in request.get('tools', []):
            tools.extend(self.convert_tool(tool))
        for item in request.get('input', []):
            if item.get('type') in {'additional_tools', 'tool_search_output'}:
                for tool in item.get('tools', []):
                    tools.extend(self.convert_tool(tool))
        return tools

    def _convert_history(self, items):
        """Translate history using this request's complete tool binding table."""
        converted = []
        for item in items:
            kind = item.get('type')
            if kind == 'additional_tools':
                continue
            if kind == 'tool_search_call':
                converted.append({'type': 'function_call', 'name': 'connected_native_tool_search',
                    'call_id': item['call_id'], 'arguments': json.dumps(item['arguments'])})
                continue
            if kind == 'tool_search_output':
                advertised = []
                for tool in item.get('tools', []):
                    advertised.extend(self.convert_tool(tool))
                converted.append({'type': 'function_call_output', 'call_id': item['call_id'],
                    'output': json.dumps({'status': item['status'], 'tools': advertised})})
                continue
            if kind == 'agent_message':
                # Codex v2 delivers delegated tasks as agent_message rather than
                # a user message. The provider-visible string spans must survive
                # translation, otherwise the worker never receives its task.
                content = []
                for part in item.get('content', []):
                    if part.get('type') == 'input_text':
                        content.append(part['text'])
                    elif part.get('type') == 'encrypted_content':
                        content.append(part['encrypted_content'])
                    else:
                        raise ValueError('Unsupported agent-message content')
                converted.append({'type':'message','role':'user',
                    'content':[{'type':'input_text','text':'\n'.join(content)}]})
                continue
            if kind in {'function_call','custom_tool_call'}:
                alias = self.alias(item.get('namespace'),item['name'])
                expected_type = 'custom' if kind == 'custom_tool_call' else 'function'
                binding = self.bindings.get(alias)
                if binding is None and not item.get('namespace'):
                    # Host history can omit the namespace. Only recover a name
                    # from a unique registered tool of the same call kind.
                    candidates = [(key, value) for key, value in self.bindings.items()
                                  if value['name'] == item['name'] and value['type'] == expected_type]
                    if len(candidates) == 1:
                        alias, binding = candidates[0]
                if binding is None or binding['type'] != expected_type:
                    raise UnregisteredToolError(alias)
                self.call_bindings[item['call_id']] = binding
                if kind == 'custom_tool_call':
                    item['arguments'] = json.dumps({'input':item.pop('input')})
                    item['type'] = 'function_call'
                item.pop('namespace',None)
                item['name'] = alias
            elif kind == 'custom_tool_call_output':
                item['type'] = 'function_call_output'
            converted.append(item)
        return converted

    @staticmethod
    def _unique_tools(tools):
        # Model switches can update descriptions of the same historical tool.
        # Execution schemas must still agree; keep the latest guidance text.
        unique = {}
        for tool in tools:
            previous = unique.get(tool['name'])
            if previous is not None and (
                    {k: v for k, v in previous.items() if k != 'description'} !=
                    {k: v for k, v in tool.items() if k != 'description'}):
                raise ValueError('Conflicting tool definitions')
            unique[tool['name']] = tool
        return unique

    def _coordination_instructions(self, instructions, unique):
        """Describe only coordination aliases actually registered for this turn."""
        coordination = {'spawn_agent', 'send_message', 'followup_task', 'wait_agent',
                        'list_agents', 'interrupt_agent'}
        aliases = [f"{binding['name']} = `{alias}`" for alias, binding in self.bindings.items()
                   if binding['name'] in coordination or (
                       binding['name'] == 'wait' and {'ids', 'targets'} &
                       unique[alias].get('parameters', {}).get('properties', {}).keys())]
        if aliases:
            return (instructions or '') + (
                '\nNative agent coordination tools registered for this request: ' + '; '.join(aliases) +
                '. Use these exact callable names, even if earlier instructions name a host namespace. '
                'Use the registered coordination wait tool for agents, never a process stdin tool.')
        return instructions

    def item(self, original):
        item = copy.deepcopy(original)
        if item.get('type') != 'function_call':
            return item
        name = item.get('name')
        binding = self.bindings.get(name)
        if binding is None:
            # Providers may return the discovered tool's original name rather
            # than its flattened alias. Resolve only an unambiguous registered
            # name; never route an invented name to an executor.
            candidates = [b for b in self.bindings.values() if b['type'] != 'tool_search' and
                name in {b['name'],
                    (b['namespace'] + '.' + b['name']) if b['namespace'] else b['name'],
                    (b['namespace'] + '_' + b['name']) if b['namespace'] else b['name']}]
            if len(candidates) == 1:
                binding = candidates[0]
        if binding is None:
            raise UnregisteredToolError(item.get('name'))
        self.call_bindings[item['call_id']] = binding
        item['name'] = binding['name']
        if binding['type'] == 'tool_search':
            item.pop('name', None)
            item['type'] = 'tool_search_call'
            item['execution'] = 'client'
            item['arguments'] = json.loads(item.get('arguments') or '{}')
            return item
        if binding['namespace']:
            item['namespace'] = binding['namespace']
        if binding['type'] == 'custom':
            arguments = item.pop('arguments','')
            item['type'] = 'custom_tool_call'
            item['input'] = json.loads(arguments)['input'] if arguments else ''
        return item

    def event(self, original):
        failure = stream_error_event(original)
        if failure is not None:
            return failure
        if 'choices' in original:
            raise ValueError('UPSTREAM_PROTOCOL_MISMATCH')
        event = copy.deepcopy(original)
        kind = event.get('type','')
        # JSON wrapper argument deltas aren't raw custom-tool input deltas. Final
        # output_item.done carries the reconstructed raw input accepted by Codex.
        if kind.startswith('response.function_call_arguments.'):
            return None
        if 'item' in event:
            event['item'] = self.item(event['item'])
        if 'response' in event:
            event['response']['output'] = [self.item(i) for i in event['response'].get('output',[])]
        return event

    def stream_events(self, original):
        """Do not reject a provisional tool name before its final item arrives."""
        item = original.get('item', {})
        kind = original.get('type')
        identity = item.get('id') or item.get('call_id')
        try:
            adapted = self.event(original)
        except UnregisteredToolError:
            if kind == 'response.output_item.added' and identity:
                self.pending_added[identity] = copy.deepcopy(original)
                return []
            raise
        result = []
        if kind == 'response.output_item.done' and identity in self.pending_added:
            added = self.pending_added.pop(identity)
            added['item'] = copy.deepcopy(adapted['item'])
            added['item']['status'] = 'in_progress'
            if added['item'].get('type') == 'custom_tool_call':
                added['item']['input'] = ''
            elif added['item'].get('type') == 'tool_search_call':
                added['item']['arguments'] = {}
            else:
                added['item']['arguments'] = ''
            result.append(added)
        if kind in {'response.completed', 'response.incomplete'} and self.pending_added:
            raise ValueError('Stream ended with unresolved provisional tools')
        if adapted is not None:
            result.append(adapted)
        return result
