"""Bridge Codex v2 additional_tools/namespaces to DeepSeek Responses tools.

Does not execute tools. The original Codex backend remains the executor.
"""
import copy
import json
import re
import uuid

from adapters.request_compat import inline_history


class UnregisteredToolError(ValueError):
    def __init__(self, name):
        super().__init__('Upstream requested an unregistered tool')
        self.tool_name = name if isinstance(name, str) and re.fullmatch(r'[\w.:-]{0,128}', name) else '<invalid>'


def plaintext_collaboration_schema(original):
    """Expose ordinary bridge tools; leave OpenAI's reserved schemas untouched.

The wire namespace is custom; the gateway maps calls back to native Codex.
No existing ciphertext is decrypted or altered.
"""
    request = copy.deepcopy(original)
    def visit(tools, namespace=None):
        for tool in tools:
            if tool.get('type') == 'namespace':
                visit(tool.get('tools', []), tool['name'])
                if tool['name'] == 'collaboration':
                    tool['name'] = 'connected_agent_bridge'
            elif namespace == 'collaboration' and tool.get('name') in {
                    'spawn_agent', 'send_message', 'followup_task'}:
                properties = tool.get('parameters', {}).get('properties', {})
                if tool['name'] == 'spawn_agent' and 'task_name' in properties:
                    properties['task_name']['description'] = (
                        properties['task_name'].get('description', '') +
                        '\nTask names must be unique within the parent, including agents created before '
                        'an edited message was re-executed. Editing/retrying a message does not delete '
                        'existing agents. For a fresh execution, choose a new lowercase suffix such as '
                        '_run2 or _run3 when the preferred name already exists; report the actual name. '
                        'If creation returns an already-exists error, retry with a fresh suffixed name. '
                        'Use followup_task only when the user intends to continue the existing execution. '
                        'If the user explicitly forbids changing the exact name, report the conflict instead.')
                    properties['task_name']['description'] += (
                        '\nFor configured external executions the local gateway treats task_name as a preferred label '
                        'and appends a unique run suffix automatically, including retries of unchanged edited '
                        'messages. Use the actual returned task path for follow-up, wait and messaging. '
                        'Do not ask for permission merely because the preferred label was used before.')
                for field in ['message']:
                    if field in properties:
                        properties[field].pop('encrypted', None)
    visit(request.get('tools', []))
    for item in request.get('input', []):
        if item.get('type') == 'additional_tools':
            visit(item.get('tools', []))
        elif item.get('type') == 'function_call' and item.get('namespace') == 'collaboration':
            item['namespace'] = 'connected_agent_bridge'
        elif item.get('type') == 'agent_message':
            # Native collaboration can place an external model's plaintext
            # message into encrypted_content. OpenAI attempts to decrypt that
            # field and returns invalid_encrypted_content. Retain provenance
            # and plaintext without attempting to decrypt genuine ciphertext.
            for part in item.get('content', []):
                value = part.get('encrypted_content')
                if (part.get('type') == 'encrypted_content' and isinstance(value, str)
                        and not value.startswith('gAAAA')):
                    part.clear()
                    part.update(type='input_text', text=value)
    return request


def native_coordination_event(original):
    event=copy.deepcopy(original)
    def restore(item):
        if item.get('type') == 'function_call' and item.get('namespace') == 'connected_agent_bridge':
            item['namespace']='collaboration'
    if 'item' in event: restore(event['item'])
    for item in event.get('response',{}).get('output',[]): restore(item)
    return event


class NativeCoordinationAdapter:
    """Give every newly spawned external execution a unique native task path.

    A call retains its name across output_item.done and response.completed.
    Existing-target tools and GPT-only spawns retain their original arguments.
    """
    def __init__(self, external_model):
        self.external_model = external_model
        self.external_models = {external_model} if isinstance(external_model, str) else set(external_model)
        self.names = {}
        self.spawn_items = set()

    def event(self, original):
        event = native_coordination_event(original)
        item = event.get('item', {})
        if (item.get('type') == 'function_call' and item.get('namespace') == 'collaboration'
                and item.get('name') == 'spawn_agent' and item.get('id')):
            self.spawn_items.add(item['id'])
        if (event.get('type', '').startswith('response.function_call_arguments.')
                and event.get('item_id') in self.spawn_items):
            # Final output_item.done supplies the consistent rewritten arguments.
            return None

        def rename(item):
            if not (item.get('type') == 'function_call' and item.get('namespace') == 'collaboration'
                    and item.get('name') == 'spawn_agent' and item.get('arguments')):
                return
            try:
                arguments = json.loads(item['arguments'])
            except ValueError:
                return  # Incomplete arguments on output_item.added are not executable.
            if arguments.get('model') not in self.external_models:
                return
            preferred = arguments.get('task_name')
            if not isinstance(preferred, str) or not re.fullmatch(r'[a-z0-9_]+', preferred):
                return  # Keep native validation for invalid names.
            call_id = item.get('call_id') or item.get('id')
            if not call_id:
                raise ValueError('Spawn call has no stable identity')
            if call_id not in self.names:
                self.names[call_id] = preferred[:80] + '_run_' + uuid.uuid4().hex
            arguments['task_name'] = self.names[call_id]
            item['arguments'] = json.dumps(arguments, ensure_ascii=False)

        if 'item' in event:
            rename(event['item'])
        for output in event.get('response', {}).get('output', []):
            rename(output)
        return event


class ResponsesAdapter:
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
        request = inline_history(original)
        tools = []
        for tool in request.get('tools', []): tools.extend(self.convert_tool(tool))
        items = request.get('input', [])
        for item in items:
            if item.get('type') in {'additional_tools', 'tool_search_output'}:
                for tool in item.get('tools', []): tools.extend(self.convert_tool(tool))
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
                self.call_bindings[item['call_id']] = self.bindings[alias]
                if kind == 'custom_tool_call':
                    item['arguments'] = json.dumps({'input':item.pop('input')})
                    item['type'] = 'function_call'
                item.pop('namespace',None)
                item['name'] = alias
            elif kind == 'custom_tool_call_output':
                item['type'] = 'function_call_output'
            elif kind == 'reasoning':
                # Encrypted OpenAI reasoning cannot be consumed by another provider.
                if not item.get('content'):
                    continue
                item.pop('encrypted_content',None)
                item.pop('summary',None)
            elif item.get('role') == 'developer':
                # DeepSeek treats developer as user; retain instruction priority explicitly.
                item['role'] = 'system'
            converted.append(item)
        request['input'] = converted
        # Search results can repeat definitions already present in additional_tools.
        unique = {}
        for tool in tools:
            if tool['name'] in unique and unique[tool['name']] != tool:
                raise ValueError('Conflicting tool definitions')
            unique[tool['name']] = tool
        request['tools'] = list(unique.values())
        return request

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
