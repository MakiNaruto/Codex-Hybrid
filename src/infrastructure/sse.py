"""JSON server-sent event framing shared by gateway and connection tests."""
import json


def records(source):
    """Shared JSON SSE framing; event fields may supply missing payload types."""
    data, event_type = [], ''
    first = True

    def decode():
        value = json.loads('\n'.join(data))
        if not isinstance(value, dict):
            raise ValueError('INVALID_STREAM_PAYLOAD')
        if event_type and not value.get('type'):
            value['type'] = event_type
        return value

    for raw in source:
        line = raw.decode('utf-8').rstrip('\r\n')
        if first:
            line = line.removeprefix('\ufeff')
            first = False
        if not line:
            if data:
                value = '\n'.join(data)
                if value == '[DONE]':
                    return
                yield decode()
            data, event_type = [], ''
        elif line.startswith('data:'):
            value = line[5:].removeprefix(' ')
            if value == '[DONE]':
                if data:
                    yield decode()
                return
            data.append(value)
        elif line.startswith('event:'):
            event_type = line[6:].removeprefix(' ')
    if data and '\n'.join(data) != '[DONE]':
        yield decode()
