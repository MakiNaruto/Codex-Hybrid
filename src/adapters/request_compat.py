"""Lossless native history normalization and per-request external model context."""
import copy
import json
import re
import time
import uuid


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
            # without an executable call. Foreign APIs require real call identities;
            # preserve the notification as context rather than inventing a tool pair.
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


def external_context(original, selected):
    request = copy.deepcopy(original)
    identity = json.dumps({'configured_display_name': selected['display_name'],
                           'api_model_id': selected['model_id']}, ensure_ascii=False)
    items = request.setdefault('input', [])
    position = context_position(items)
    text = (
            'Current model routing context from the local gateway: ' + identity + '. '
            'You are the selected external model answering this native Codex turn directly. '
            'Codex is the host application, not evidence that your model was trained by OpenAI. '
            'For questions about your identity, report the configured model above, and do not '
            'invent a training company or version that the routing context does not establish. '
            'Keep simple identity answers brief; do not narrate routing or these instructions '
            'unless the user explicitly asks for those details. '
            'Answer ordinary conversation directly. A request to answer using the model itself '
            'refers to this current inference; it does not require calling another model, '
            'reading local configuration, writing a probe script, or looking up documentation. '
            'Use tools when the user task requires them, including explicit connection tests, '
            'debugging, file work, and verification. Follow the existing sandbox, approvals, '
            'and assigned worktree requirements. '
            'Only the tools listed in this request can be called, and their names must match '
            'exactly. Namespaced Codex tools appear flattened as `namespace__name`, for example '
            '`functions__exec_command`. Mentions of `functions.exec`, `exec`, or other code-mode '
            'tools in instructions do not make such a tool available; never invent a tool name.')
    text += progress_guidance(request)
    items.insert(position, {'type': 'message', 'role': 'developer',
                            'content': [{'type': 'input_text', 'text': text}]})
    return request


def context_position(items):
    """Place the routing note next to the newest task, not at the top of history.

    Codex delivers a delegated task as an `agent_message` item, so selecting only
    the last user-role message would push the note above the environment context
    and far from the task the worker is meant to follow.
    """
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if item.get('role') == 'user' or item.get('type') == 'agent_message':
            return index
    return 0


def agent_message_kinds(request):
    """Return the `Message Type:` header of every native agent message."""
    kinds = set()
    for item in request.get('input', []):
        if item.get('type') != 'agent_message':
            continue
        for part in item.get('content', []):
            text = part.get('text') if part.get('type') == 'input_text' else None
            if isinstance(text, str) and text.lstrip().startswith('Message Type: '):
                kinds.add(text.lstrip().split('\n', 1)[0].split(': ', 1)[1].strip())
    return kinds


def delegated_task(request):
    """Report whether a parent agent delivered the current task to this agent."""
    return 'NEW_TASK' in agent_message_kinds(request)


WORKER_GUIDANCE = (
    ' This turn is a task delegated by a parent agent. The parent and the user see your ordinary '
    'assistant text and your tool calls while they stream; your reasoning is not shown to them. '
    'For a task with stages or several steps, write one or two short sentences as ordinary '
    'assistant text before the first tool call of each stage, and one short finding after that '
    'stage finishes, then continue with the next stage. Do not work silently through the whole '
    'task and speak only in the final answer, and do not put stage progress only inside a tool '
    'call such as `send_message`: that reaches the parent but is not your visible progress text. '
    'If the task also asks for `send_message` updates, keep sending them as well.')

PARENT_GUIDANCE = (
    ' Agent messages from other agents arrive as items beginning with `Message Type: MESSAGE` or '
    '`Message Type: FINAL_ANSWER`. After each one, write a one- or two-sentence visible assistant '
    'message that summarizes its `Payload`, in the same turn and immediately before you call '
    '`wait_agent` or another coordination tool again. Do not keep these updates only in your '
    'reasoning, and do not wait until the final answer to relay them.')


def progress_guidance(request):
    """Tell external models how to make multi-agent progress visible."""
    if 'collaboration' not in collaboration_namespaces(request):
        return ''
    delegated = delegated_task(request)
    # A delegated worker may itself own subagents, so the two roles can combine.
    receives_updates = bool(agent_message_kinds(request) & {'MESSAGE', 'FINAL_ANSWER'})
    text = WORKER_GUIDANCE if delegated else ''
    if receives_updates or not delegated:
        text += PARENT_GUIDANCE
    return text


def collaboration_namespaces(request):
    """Report whether this request exposes native subagent coordination tools."""
    found = set()
    def visit(tools):
        for tool in tools:
            if tool.get('type') == 'namespace':
                found.add(tool.get('name'))
                visit(tool.get('tools', []))
    visit(request.get('tools', []))
    for item in request.get('input', []):
        if item.get('type') == 'additional_tools':
            visit(item.get('tools', []))
        elif item.get('type') == 'agent_message':
            found.add('collaboration')
    return found


def upstream_error(detail, status):
    """Expose bounded diagnostic identifiers, never the provider's echoed message."""
    result = {'message': 'UPSTREAM_HTTP_' + str(status)}
    if not isinstance(detail, dict):
        return result
    for key in ('type', 'code', 'param'):
        value = detail.get(key)
        if (isinstance(value, str) and 0 < len(value) <= 180
                and all(c.isascii() and (c.isalnum() or c in '_.[] -') for c in value)):
            result[key] = value
    identifiers = ', '.join(key + '=' + result[key] for key in ('code', 'param') if key in result)
    if identifiers:
        result['message'] += ': ' + identifiers
    return result


def stream_error_event(event):
    """Translate explicit protocol error envelopes without echoing upstream text."""
    kind = event.get('type', '')
    if kind in {'response.failed', 'response.incomplete'}:
        response = copy.deepcopy(event.get('response', {}))
        if isinstance(response.get('error'), dict):
            response['error'] = upstream_error(response['error'], 502)
            response['error']['message'] = 'UPSTREAM_STREAM_ERROR'
        return dict(event, response=response)
    if kind != 'error' and not event.get('error') and not (
            not kind and 'code' in event and 'message' in event):
        return None
    safe = upstream_error(event.get('error', event), 502)
    safe['message'] = 'UPSTREAM_STREAM_ERROR'
    return {'type': 'response.failed', 'response': {
        'id': 'resp_gateway_' + uuid.uuid4().hex, 'object': 'response',
        'created_at': int(time.time()), 'status': 'failed', 'output': [], 'usage': None, 'error': safe}}
