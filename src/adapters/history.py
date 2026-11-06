"""Native and portable history replay with explicit identity preservation."""
import copy
import json
import re


def native_plaintext_marker(value):
    """Codex stores foreign reasoning spans under UUID-index placeholders."""
    return isinstance(value, str) and re.fullmatch(
        r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-\d+', value) is not None


def normalize_history(original, *, portable=False):
    """Preserve native opaque state only on the native route; migrate readable history."""
    request = inline_history(original)
    normalized = []
    instructions = [request['instructions']] if portable and request.get('instructions') else []
    for item in request.get('input', []):
        content = item.get('content')
        if (portable and item.get('type') in {'function_call_output', 'custom_tool_call_output'}
                and not item.get('call_id') and isinstance(item.get('name'), str)):
            # Host-delivered task/context notifications use tool-output envelopes
            # without an executable call. The portable bridge targets endpoints
            # that require paired calls; this changes the message category and
            # is an explicit downgrade, not equivalent native serialization.
            source = '.'.join(value for value in (item.get('namespace'), item['name']) if isinstance(value, str))
            output = item.get('output', '')
            text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
            normalized.append({'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': f'Host-delivered context from {source}:\n{text}'}]})
            continue
        if (portable and item.get('type') in {None, 'message'}
                and item.get('role') in {'system', 'developer'}):
            if isinstance(content, str):
                instructions.append(content)
            elif isinstance(content, list) and all(
                    isinstance(part, dict) and part.get('type') in {'input_text', 'output_text', 'text'}
                    and isinstance(part.get('text'), str) for part in content):
                instructions.append('\n'.join(part['text'] for part in content))
            else:
                raise ValueError('UNSUPPORTED_SYSTEM_CONTENT')
            continue
        if portable and item.get('type') == 'reasoning':
            parts = content or item.get('summary') or []
            if not isinstance(parts, list) or any(
                    not isinstance(part, dict)
                    or part.get('type') not in {'reasoning_text', 'summary_text'}
                    or not isinstance(part.get('text'), str) for part in parts):
                raise ValueError('UNSUPPORTED_REASONING_HISTORY')
            text = ''.join(part['text'] for part in parts)
            if text:
                normalized.append({'type': 'message', 'role': 'assistant', 'content': [
                    {'type': 'output_text', 'text': 'Previous model reasoning (historical context):\n' + text,
                     'annotations': []}]})
            continue
        if (item.get('type') == 'reasoning' and content
                and (not item.get('encrypted_content')
                     or native_plaintext_marker(item['encrypted_content']))
                and all(part.get('type') == 'reasoning_text'
                        and isinstance(part.get('text'), str) for part in content)):
            # Preserve foreign plaintext as historical assistant text. Sending
            # it as native reasoning fails even with ONE part (maximum is zero).
            normalized.append({'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text', 'text':
                    'Previous model reasoning (historical context):\n' +
                    ''.join(part['text'] for part in content), 'annotations': []}]})
        else:
            normalized.append(item)
    request['input'] = normalized
    if portable and instructions:
        request['instructions'] = '\n\n'.join(instructions)
    return request


def inline_history(original):
    """Replay supplied history by value, without provider-local storage IDs.

    Keep call_id and nested resource IDs: they identify tool pairs and assets,
    not persisted response items. Bare references cannot be expanded here and
    must retain their ID rather than silently losing historical context.
    """
    request = copy.deepcopy(original)
    items = request.get('input', [])
    if isinstance(items, list):
        for item in items:
            if (isinstance(item, dict) and item.get('type') != 'item_reference'
                    and any(field in item for field in (
                        'content', 'arguments', 'input', 'output', 'encrypted_content', 'summary'))):
                item.pop('id', None)
    return request
