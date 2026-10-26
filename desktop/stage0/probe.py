"""Isolated feasibility probe, not the production desktop control protocol.

Requires an explicit fixture settings file. Never discovers real user configuration.
"""
import argparse
import io
import json
from pathlib import Path
import sys
import threading

from gateway.server import Gateway, Server
from management.http import WEB


def report():
    import psutil
    import yaml
    return {
        'frozen': bool(getattr(sys, 'frozen', False)),
        'python': sys.version.split()[0],
        'utf8_mode': sys.flags.utf8_mode,
        'yaml': yaml.__version__,
        'psutil': psutil.__version__,
        'static_files': {name: (WEB / name).is_file()
                         for name in ('index.html', 'app.js', 'entry.html', 'entry.js', 'style.css')},
    }


class FixtureOpener:
    """No network: exercise real request construction and stream adaptation."""
    def open(self, request, timeout):
        if request.full_url != 'https://stage0.invalid/v1/chat/completions':
            raise ValueError('UNEXPECTED_FIXTURE_ENDPOINT')
        if json.loads(request.data)['model'] != 'fixture-model':
            raise ValueError('UNEXPECTED_FIXTURE_MODEL')
        chunk = {'choices': [{'index': 0, 'delta': {'content': 'hello'}, 'finish_reason': 'stop'}]}
        return io.BytesIO(('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n').encode())


def control(settings_path):
    gateway = Gateway(json.loads(settings_path.read_text(encoding='utf-8')), settings_path)
    # Constructing Gateway/Management does not construct or bind a Server.
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            method = request.get('method')
            if method == 'inspect':
                result = gateway.manager.view()
            elif method == 'save_fixture_provider':
                result = gateway.manager.save_provider('fixture', {
                    'base_url': 'https://stage0.invalid/v1',
                    'protocol': 'openai_chat_completions',
                    'models': {'default': {'model_id': 'fixture-model', 'display_name': '隔离测试模型'}},
                }, api_key='stage0-fake-key')
            elif method == 'test_fixture_connection':
                gateway.opener = FixtureOpener()
                result = gateway.manager.test_connection('fixture/default')
            elif method == 'shutdown':
                print(json.dumps({'id': request.get('id'), 'result': {'stopped': True}}), flush=True)
                return
            else:
                raise ValueError('METHOD_NOT_ALLOWED')
            response = {'id': request.get('id'), 'result': result}
        except Exception as error:
            response = {'id': request.get('id') if isinstance(request, dict) else None,
                        'error': {'type': type(error).__name__}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('report', 'control', 'gateway'))
    parser.add_argument('--settings', type=Path)
    args = parser.parse_args()
    if args.mode == 'report':
        print(json.dumps(report()))
        return
    if args.settings is None:
        parser.error('--settings is required; no default user directory is permitted')
    marker = args.settings.parent / 'stage0-fixture.marker'
    if not marker.is_file():
        parser.error('settings must belong to an explicitly marked stage0 fixture')
    if args.mode == 'control':
        control(args.settings)
    else:
        gateway = Gateway(json.loads(args.settings.read_text(encoding='utf-8')), args.settings)
        with Server(('127.0.0.1', gateway.settings['port']), gateway.handler()) as server:
            def shutdown_on_control_input():
                # Cooperative shutdown also lets the PyInstaller bootloader reap its child.
                # EOF means the controller disappeared; do not leave an orphaned listener.
                for line in sys.stdin:
                    if line.strip() == 'shutdown':
                        break
                server.shutdown()

            threading.Thread(target=shutdown_on_control_input, daemon=True).start()
            print(json.dumps({'status': 'listening', 'port': server.server_port}), flush=True)
            server.serve_forever()


if __name__ == '__main__':
    main()
