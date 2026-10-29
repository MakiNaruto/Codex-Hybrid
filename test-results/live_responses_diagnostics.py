"""Live diagnostic controls; does not change the active gateway configuration."""
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from live_responses_probe import ROOT, SETTINGS, FUNCTION, RESULTS, probe
from gateway.server import route
from gateway.transport import FreshProxyOpener, records

CHAT_RESULTS = []


def chat(model, name, messages, tools=False):
    start = time.monotonic()
    result = {'model': model, 'case': name, 'protocol': 'chat_control'}
    key = ''
    message = None
    try:
        url, _, headers, _ = route({'model': model, 'stream': True, 'input': []},
                                  {'Authorization': 'Bearer synthetic-local-probe'}, SETTINGS)
        url = url.removesuffix('/responses') + '/chat/completions'
        key = headers.get('Authorization', '').removeprefix('Bearer ')
        body = {'model': model.split('/', 1)[1], 'messages': messages, 'stream': True,
                'max_tokens': 1024}
        if tools:
            body['tools'] = [{'type': 'function', 'function': {k: v for k, v in FUNCTION.items()
                                                             if k not in ('type', 'strict')}}]
        result['endpoint'] = url
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        with FreshProxyOpener().open(req, timeout=35) as stream:
            result['http_status'] = stream.status
            text, calls, finish = [], {}, None
            errors = []
            for event in records(stream):
                if event.get('error'):
                    errors.append(event['error'])
                for choice in event.get('choices', []):
                    delta = choice.get('delta', {})
                    if delta.get('content'):
                        text.append(delta['content'])
                    for call in delta.get('tool_calls', []):
                        item = calls.setdefault(call['index'], {'id': '', 'type': 'function',
                                                               'function': {'name': '', 'arguments': ''}})
                        if call.get('id'):
                            item['id'] = call['id']
                        for field in ('name', 'arguments'):
                            item['function'][field] += call.get('function', {}).get(field) or ''
                    finish = choice.get('finish_reason') or finish
            message = {'role': 'assistant', 'content': ''.join(text) or None}
            if calls:
                message['tool_calls'] = list(calls.values())
            result.update(message=message, finish_reason=finish, errors=errors,
                          completed=finish in ('stop', 'tool_calls'))
    except urllib.error.HTTPError as error:
        result.update(http_status=error.code, error_body=error.read(12000).decode('utf-8', errors='replace'))
    except Exception as error:
        result.update(exception_type=type(error).__name__, exception=str(error))
    result['elapsed_ms'] = round((time.monotonic() - start) * 1000)
    encoded = json.dumps(result, ensure_ascii=False)
    if key:
        encoded = encoded.replace(key, '[REDACTED]')
    result = json.loads(encoded)
    CHAT_RESULTS.append(result)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return message, result


def chat_control(model):
    user = {'role': 'user', 'content': 'Remember token CONTROL-863. Reply only CONTROL-863.'}
    message, result = chat(model, 'chat_plain', [user])
    if not result.get('completed'):
        return
    chat(model, 'chat_second_turn', [user, message, {'role': 'user', 'content': 'Repeat the token.'}])
    prompt = {'role': 'user', 'content': 'Call multiply with a=137, b=29. Do not calculate it yourself.'}
    message, result = chat(model, 'chat_tool_call', [prompt], tools=True)
    if result.get('completed') and message and message.get('tool_calls'):
        call = message['tool_calls'][0]
        args = json.loads(call['function']['arguments'])
        chat(model, 'chat_tool_result', [prompt, message, {'role': 'tool', 'tool_call_id': call['id'],
             'content': str(args['a'] * args['b'])}], tools=True)


def extra_responses():
    model = next(m for m in SETTINGS['models'] if m.endswith('/qwen-plus'))
    first = {'role': 'user', 'content': 'Reply only OK.'}
    for name, extra in {
        'include_only': {'include': ['reasoning.encrypted_content']},
        'reasoning_only': {'reasoning': {'effort': 'low'}},
        'namespace_invoke': {'input': [{'role': 'user', 'content':
            'Use math.multiply with a=137 b=29. You must call the tool.'}],
            'tools': [{'type': 'namespace', 'name': 'math', 'tools': [FUNCTION]}]},
        'custom_invoke': {'input': [{'role': 'user', 'content':
            'Call the echo tool with input PROBE-729. You must call the tool.'}],
            'tools': [{'type': 'custom', 'name': 'echo', 'description': 'Echo text.'}]},
    }.items():
        body = {'input': [first], **extra}
        response, result = probe(model, name, body)
        if result.get('completed') and response and name in ('namespace_invoke', 'custom_invoke'):
            output = response.get('output', [])
            calls = [item for item in output if item.get('type') in ('function_call', 'custom_tool_call')]
            if calls:
                call = calls[0]
                custom = call['type'] == 'custom_tool_call'
                probe(model, name + '_result_replay', {'input': body['input'] + output + [{
                    'type': 'custom_tool_call_output' if custom else 'function_call_output',
                    'call_id': call['call_id'], 'output': 'PROBE-729' if custom else '3973'}],
                    'tools': body['tools']})


if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(chat_control, m) for m in SETTINGS['models']
                   if m not in SETTINGS['official_models']]
        futures.append(executor.submit(extra_responses))
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as error:
                print('diagnostic harness exception:', type(error).__name__, flush=True)
    (ROOT / 'live-responses-diagnostics-2026-10-29.json').write_text(
        json.dumps({'responses': RESULTS, 'chat_controls': CHAT_RESULTS}, ensure_ascii=False, indent=2),
        encoding='utf-8')
    print('saved', len(RESULTS), 'Responses cases and', len(CHAT_RESULTS), 'Chat controls', flush=True)
