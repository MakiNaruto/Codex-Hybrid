"""Native Codex collaboration schemas and request-scoped spawn identities.

This mapping is independent of portable Responses and Chat tool conversion.
"""
import copy
import json
import re
import uuid


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
                if 'message' in properties:
                    properties['message'].pop('encrypted', None)
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
    event = copy.deepcopy(original)
    def restore(item):
        if item.get('type') == 'function_call' and item.get('namespace') == 'connected_agent_bridge':
            item['namespace'] = 'collaboration'
    if 'item' in event:
        restore(event['item'])
    for item in event.get('response', {}).get('output', []):
        restore(item)
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


