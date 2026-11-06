"""Provider routing context and host collaboration guidance."""
import copy
import json
import re


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


def progress_guidance(request):
    """Tell external models how to make multi-agent progress visible."""
    if not {'collaboration', 'connected_agent_bridge'} & collaboration_namespaces(request):
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
        if item.get('type') in {'additional_tools', 'tool_search_output'}:
            visit(item.get('tools', []))
        elif item.get('type') == 'agent_message':
            found.add('collaboration')
    return found
