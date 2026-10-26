"""Run the same isolated checks against source Python or the frozen executable."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


def fixture(directory, port):
    (directory / 'stage0-fixture.marker').touch()
    original = 'model = "fixture-official"\n'
    config = directory / 'codex-config.toml'
    config.write_text(original, encoding='utf-8')
    (directory / 'models.yaml').write_text('version: 1\nproviders: {}\n', encoding='utf-8')
    write_json(directory / 'models.json', {'models': [{'slug': 'fixture-official', 'priority': 1}]})
    write_json(directory / 'state.json', {
        'config_path': str(config), 'activated': False,
        'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
    })
    settings_path = directory / 'settings.json'
    write_json(settings_path, {
        'port': port, 'catalog': str(directory / 'models.json'),
        'source': {'type': 'yaml', 'path': str(directory / 'models.yaml')},
        'official_models': ['fixture-official'], 'models': ['fixture-official'],
        'local_token': 'stage0-local-fake-token', 'management_token': 'stage0-management-fake-token',
        'management_auth_required': True, 'max_concurrent_requests': 2,
    })
    return settings_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, help='Frozen one-file executable; omit for source mode')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    results = []
    environment = os.environ.copy()
    # Frozen checks must not resolve imports from this checkout or a Python installation.
    for name in list(environment):
        if name.startswith(('PYTHON', 'CODEX_HYBRID_', 'MODEL_ROUTER_', 'CONNECTED_')):
            environment.pop(name)
    if args.executable is None:
        environment['PYTHONPATH'] = str(ROOT / 'src')
    else:
        environment['PATH'] = os.path.join(environment.get('SystemRoot', 'C:/Windows'), 'System32') if os.name == 'nt' else '/usr/bin:/bin'

    def checked(condition, name):
        if not condition:
            raise AssertionError(name)
        results.append(name)

    with tempfile.TemporaryDirectory(prefix='hybrid-stage0-') as temporary:
        directory = Path(temporary) / '隔离 data with spaces'
        directory.mkdir()
        if args.executable:
            executable = directory / args.executable.name
            shutil.copy2(args.executable.resolve(), executable)
            command = [str(executable)]
        else:
            command = [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('probe.py'))]
        options = {'cwd': directory, 'env': environment, 'text': True, 'encoding': 'utf-8',
                   'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE}
        started = time.monotonic()
        process = subprocess.run([*command, 'report'], timeout=60, **options)
        checked(process.returncode == 0, 'entrypoint_runs_outside_checkout')
        metadata = json.loads(process.stdout)
        checked(all(metadata['static_files'].values()), 'management_static_resources_present')
        checked(metadata['frozen'] == bool(args.executable), 'expected_source_or_frozen_mode')
        checked(metadata['utf8_mode'] == 1, 'utf8_mode_explicitly_enabled')

        # Hold the chosen port during all management calls: an accidental listener cannot bind.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
            settings = fixture(directory, port)
            requests = ['inspect', 'save_fixture_provider', 'inspect', 'test_fixture_connection',
                        'invalid_method', 'shutdown']
            process = subprocess.run([*command, 'control', '--settings', str(settings)],
                                     input=''.join(json.dumps({'id': i, 'method': method}) + '\n'
                                                   for i, method in enumerate(requests)),
                                     timeout=60, **options)
            checked(process.returncode == 0, 'stdio_control_exits_cleanly')
            replies = [json.loads(line) for line in process.stdout.splitlines()]
            checked(len(replies) == 6 and all(reply['id'] == i for i, reply in enumerate(replies)),
                    'stdio_request_ids_and_response_framing')
            checked(replies[0]['result']['models'] == [] and replies[0]['result']['source_error'] is None,
                    'empty_provider_management_without_gateway_listener')
            checked(replies[1]['result']['saved'] and len(replies[2]['result']['models']) == 1,
                    'save_provider_and_publish_catalog_without_listener')
            checked(replies[2]['result']['models'][0]['display_name'] == '隔离测试模型',
                    'unicode_model_name_round_trips_over_stdio_and_files')
            checked('stage0-fake-key' not in json.dumps(replies[2]), 'management_view_omits_api_key')
            checked(replies[3]['result']['status'] == 'completed',
                    'connection_test_with_real_adapter_and_mock_transport')
            checked('error' in replies[4] and replies[5]['result']['stopped'],
                    'unknown_method_does_not_kill_control_process')
            checked((directory / 'codex-config.toml').read_text() == 'model = "fixture-official"\n',
                    'configuration_management_does_not_change_codex_routing')

        # This is the actual gateway implementation with fixture config, on a temporary port.
        child = subprocess.Popen([*command, 'gateway', '--settings', str(settings)],
                                 stdin=subprocess.PIPE, **options)
        lines = queue.Queue()
        reader = threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True)
        reader.start()
        try:
            first_line = lines.get(timeout=60)
            if not first_line:
                raise RuntimeError('Isolated gateway exited before ready: ' + child.stderr.read())
            message = json.loads(first_line)
            checked(message['status'] == 'listening', 'gateway_child_ready_event')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f'http://127.0.0.1:{port}/healthz', timeout=5) as response:
                checked(json.load(response)['service'] == 'connected-native-gateway', 'gateway_health_check')
            request = urllib.request.Request(f'http://127.0.0.1:{port}/manage/api/state',
                                             headers={'Authorization': 'Bearer stage0-management-fake-token'})
            with opener.open(request, timeout=5) as response:
                checked(len(json.load(response)['models']) == 1, 'gateway_loads_saved_configuration')
            request.add_header('Origin', 'https://stage0.invalid')
            try:
                opener.open(request, timeout=5).close()
                raise AssertionError('origin_restriction')
            except urllib.error.HTTPError as error:
                with error:
                    checked(error.code == 403, 'management_origin_restriction_preserved')
        finally:
            # Cooperative exit is essential for a one-file bootloader plus interpreter tree.
            # All fallback process handles are descendants of this verifier's own child.
            try:
                child.communicate(input='shutdown\n', timeout=10)
            except subprocess.TimeoutExpired:
                import psutil
                owned = psutil.Process(child.pid)
                descendants = owned.children(recursive=True)
                for process in reversed(descendants):
                    try:
                        process.terminate()
                    except psutil.NoSuchProcess:
                        pass
                psutil.wait_procs(descendants, timeout=5)
                child.terminate()
                child.communicate(timeout=5)
        checked(child.returncode == 0, 'isolated_gateway_cooperative_shutdown')
        with socket.socket() as connection:
            connection.settimeout(2)
            checked(connection.connect_ex(('127.0.0.1', port)) != 0, 'gateway_port_released_after_shutdown')

        # Simulate loss of the controller by closing its stdin pipe, without killing the app.
        orphan_check = subprocess.Popen([*command, 'gateway', '--settings', str(settings)],
                                        stdin=subprocess.PIPE, **options)
        try:
            orphan_check.stdin.close()
            orphan_check.stdin = None
            orphan_check.communicate(timeout=30)
            checked(orphan_check.returncode == 0, 'gateway_exits_on_controller_eof')
        finally:
            if orphan_check.poll() is None:
                # Same owned-process-tree cleanup as above, never a name-based system kill.
                import psutil
                descendants = psutil.Process(orphan_check.pid).children(recursive=True)
                for process in reversed(descendants):
                    try:
                        process.terminate()
                    except psutil.NoSuchProcess:
                        pass
                psutil.wait_procs(descendants, timeout=5)
                orphan_check.terminate()
                orphan_check.communicate(timeout=5)
        report = {'mode': 'frozen' if args.executable else 'source', 'metadata': metadata,
                  'elapsed_seconds': round(time.monotonic() - started, 3),
                  'checks_passed': len(results), 'checks': results,
                  'limits': ['mock upstream only; no paid API request',
                             'host may have Python installed; frozen run removes Python paths',
                             'no production Codex configuration or lifecycle changes']}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.output, report)
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
