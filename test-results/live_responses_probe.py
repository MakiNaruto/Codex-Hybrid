"""Opt-in live probes. Credentials stay in memory; persisted requests are synthetic."""
import concurrent.futures
import copy
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from gateway.server import route
from gateway.transport import FreshProxyOpener, records

ROOT = Path(__file__).resolve().parent
SETTINGS = json.loads((Path.home() / '.codex-hybrid/settings.json').read_text(encoding='utf-8'))
RESULTS = []
FUNCTION = {'type': 'function', 'name': 'multiply', 'description': 'Multiply two integers.',
            'parameters': {'type': 'object', 'properties': {'a': {'type': 'integer'},
                           'b': {'type': 'integer'}}, 'required': ['a', 'b'], 'additionalProperties': False},
            'strict': True}


def probe(model, name, body):
    body = dict(body, model=model, stream=True, store=False)
    start = time.monotonic()
    result = {'model': model, 'case': name, 'request': copy.deepcopy(body)}
    key = ''
    response = None
    try:
        url, payload, headers, _ = route(body, {'Authorization': 'Bearer synthetic-local-probe'}, SETTINGS)
        key = headers.get('Authorization', '').removeprefix('Bearer ')
        result['endpoint'] = url
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with FreshProxyOpener().open(request, timeout=35) as stream:
            result['http_status'] = stream.status
            result['content_type'] = stream.headers.get('Content-Type')
            types, outputs, errors = [], [], []
            for event in records(stream):
                types.append(event.get('type', ''))
                if event.get('type') == 'response.output_item.done':
                    outputs.append(event['item'])
                if event.get('type') == 'response.completed':
                    response = event.get('response', {})
                if event.get('error') or event.get('type') in ('error', 'response.failed'):
                    errors.append(event)
            result.update(event_types=sorted(set(types)), event_count=len(types), errors=errors)
            if response is None and outputs:
                response = {'output': outputs}
            result['completed'] = 'response.completed' in types
            if response is not None:
                result['response'] = response
    except urllib.error.HTTPError as error:
        result.update(http_status=error.code, error_body=error.read(12000).decode('utf-8', errors='replace'))
    except Exception as error:
        result.update(exception_type=type(error).__name__, exception=str(error))
    result['elapsed_ms'] = round((time.monotonic() - start) * 1000)
    # Defensive redaction, including credentials accidentally echoed by an endpoint.
    encoded = json.dumps(result, ensure_ascii=False)
    if key:
        encoded = encoded.replace(key, '[REDACTED]')
    result = json.loads(encoded)
    RESULTS.append(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('request', 'response')}, ensure_ascii=True), flush=True)
    return response, result


def run_model(model):
    first = {'role': 'user', 'content': 'Remember token PROBE-729. Reply only PROBE-729.'}
    response, result = probe(model, 'plain_turn_1', {'input': [first]})
    if result.get('completed') and response:
        history = [first] + response.get('output', [])
        probe(model, 'plain_turn_2_replay', {'input': history + [
            {'role': 'user', 'content': 'Which token did I ask you to remember? Reply only that token.'}]})
        prompt = {'role': 'user', 'content': 'Call multiply with a=137, b=29. Do not compute it yourself.'}
        tool_response, tr = probe(model, 'function_call', {'input': [prompt], 'tools': [FUNCTION]})
        if tr.get('completed') and tool_response:
            output = tool_response.get('output', [])
            calls = [i for i in output if i.get('type') == 'function_call']
            if calls:
                call = calls[0]
                args = json.loads(call['arguments'])
                product = args['a'] * args['b']
                probe(model, 'function_result_replay', {'input': [prompt] + output + [
                    {'type': 'function_call_output', 'call_id': call['call_id'], 'output': str(product)}],
                    'tools': [FUNCTION]})
        cases = {
            'namespace_tool': {'tools': [{'type': 'namespace', 'name': 'math', 'tools': [FUNCTION]}]},
            'custom_tool': {'tools': [{'type': 'custom', 'name': 'echo', 'description': 'Echo a string.'}]},
            'tool_search': {'tools': [{'type': 'tool_search'}]},
            'codex_reasoning_fields': {'reasoning': {'effort': 'low'}, 'include': ['reasoning.encrypted_content']},
        }
        for name, extra in cases.items():
            probe(model, name, {'input': [first], **extra})


if __name__ == '__main__':
    models = [m for m in SETTINGS['models'] if m not in SETTINGS['official_models']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_model, model) for model in models]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as error:
                print('probe harness exception:', type(error).__name__, flush=True)
    (ROOT / 'live-responses-2026-10-29.json').write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved', len(RESULTS), 'cases', flush=True)
