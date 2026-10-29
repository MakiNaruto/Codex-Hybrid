import io
import json
import tempfile
import unittest
import threading
import urllib.request
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gateway.server import (Gateway, Server, route, cached_directory, authenticated_official_catalog,
                            refresh_official_directory)


class OfficialCatalogTests(unittest.TestCase):
    def test_official_stream_uses_300_second_socket_timeout(self):
        settings = {'source': {'type': 'yaml'}, 'models': ['gpt-6.1-sol'],
                    'official_models': ['gpt-6.1-sol'], 'cc_snapshot': {'models': []},
                    'local_token': 'test-token', 'max_concurrent_requests': 1}
        gateway = Gateway(settings)
        gateway.record = lambda record: None
        captured = []

        class Opener:
            def open(self, request, timeout):
                captured.append(timeout)
                return io.BytesIO(b'data: {"type":"response.completed","response":'
                                  b'{"status":"completed","output":[]}}\n\n')

        gateway.opener = Opener()
        server = Server(('127.0.0.1', 0), gateway.handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f'http://127.0.0.1:{server.server_port}/responses',
                data=json.dumps({'model': 'gpt-6.1-sol', 'stream': True, 'input': []}).encode(),
                headers={'Authorization': 'Bearer subscription-token', 'X-Connected-Token': 'test-token'})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request) as response:
                self.assertIn(b'response.completed', response.read())
            self.assertEqual(captured, [300])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_filtered_refresh_retains_official_models_and_they_remain_routable(self):
        settings = {'source': {'type': 'yaml'},
                    'models': ['gpt-6.1-sol'], 'official_models': ['gpt-6.1-sol'],
                    'cc_snapshot': {'models': []},
                    'official_catalog': [{'slug': 'gpt-6.1-sol', 'display_name': 'Sol'}]}
        owner = SimpleNamespace(settings=settings, opener=None)
        with patch('gateway.server.authenticated_official_catalog',
                   return_value=[{'slug': 'gpt-6-luna'}]), \
                patch('gateway.server.load_source', return_value=SimpleNamespace(models={})):
            directory = refresh_official_directory(owner, {})
        self.assertEqual([m['slug'] for m in directory['models']],
                         ['gpt-6.1-sol', 'gpt-6-luna'])
        owner.settings['cc_snapshot'] = directory
        url, payload, _, _ = route(
            {'model': 'gpt-6.1-sol', 'stream': True, 'input': []},
            {'Authorization': 'Bearer subscription-token'}, owner.settings)
        self.assertEqual(url, 'https://chatgpt.com/backend-api/codex/responses')
        self.assertEqual(payload['model'], 'gpt-6.1-sol')

    def test_responses_refresh_unknown_model_without_prior_models_request(self):
        settings = {'source': {'type': 'yaml'}, 'models': ['stale'],
                    'official_models': ['stale'], 'local_token': 'local-test',
                    'max_concurrent_requests': 1}
        gateway = Gateway(settings)
        gateway.record = lambda record: None
        server = Server(('127.0.0.1', 0), gateway.handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        headers = {'Authorization': 'Bearer subscription-token',
                   'X-Connected-Token': 'local-test', 'Content-Type': 'application/json'}
        external = SimpleNamespace(models={})
        try:
            for model, directory, expected in [
                    ('gpt-6.1-sol', None, 'MODEL_NOT_ALLOWED'),
                    ('gpt-6.1-sol', [{'slug': 'gpt-6.1-sol'}], 'STREAM_REQUIRED'),
                    ('unlisted-model', [{'slug': 'gpt-6.1-sol'}], 'MODEL_NOT_ALLOWED')]:
                request = urllib.request.Request(
                    f'http://127.0.0.1:{server.server_port}/responses',
                    data=json.dumps({'model': model, 'stream': False, 'input': []}).encode(),
                    headers=headers)
                with patch('gateway.server.authenticated_official_catalog',
                           return_value=directory) as refresh, \
                        patch('gateway.server.load_source', return_value=external):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request)
                    with error.exception as response:
                        self.assertEqual(json.load(response)['error']['message'], expected)
                    refresh.assert_called_once()
            self.assertEqual(gateway.settings['official_models'], ['gpt-6.1-sol'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_catalog_request_forwards_subscription_auth_but_not_local_or_cookie_headers(self):
        response = io.BytesIO(json.dumps({'models': [{'slug': 'gpt-account-model'}]}).encode())
        captured = {}

        class Opener:
            def open(self, request, timeout):
                captured.update(url=request.full_url, headers=dict(request.header_items()), timeout=timeout)
                return response

        result = authenticated_official_catalog({
            'Authorization': 'Bearer subscription-token',
            'ChatGPT-Account-ID': 'account-id',
            'Cookie': 'session-cookie',
            'X-Connected-Token': 'local-token',
        }, {'official_header_passthrough': True}, Opener())
        self.assertEqual(result, [{'slug': 'gpt-account-model'}])
        self.assertEqual(captured['url'], 'https://chatgpt.com/backend-api/codex/models')
        self.assertEqual(captured['headers']['Authorization'], 'Bearer subscription-token')
        normalized = {name.lower(): value for name, value in captured['headers'].items()}
        self.assertEqual(normalized['chatgpt-account-id'], 'account-id')
        self.assertNotIn('cookie', normalized)
        self.assertNotIn('x-connected-token', normalized)

    def test_catalog_without_subscription_auth_does_not_query_or_use_cached_models(self):
        class Opener:
            def open(self, *args, **kwargs):
                raise AssertionError('must not make an unauthenticated request')
        self.assertIsNone(authenticated_official_catalog({}, {}, Opener()))

    def test_catalog_rejects_malformed_official_response(self):
        class Opener:
            def open(self, request, timeout):
                return io.BytesIO(b'{"models":[{}]}')
        self.assertIsNone(authenticated_official_catalog(
            {'Authorization': 'Bearer subscription-token'}, {}, Opener()))

    def test_authenticated_account_models_merge_with_external_models(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog_path = Path(temp) / 'models.json'
            external = SimpleNamespace(models={'vendor/model': {
                'enabled': True, 'display_name': 'Vendor Model',
                'provider': 'vendor', 'context_window': 8192,
            }})
            settings = {
                'source': {'type': 'yaml', 'path': 'unused'},
                'catalog': str(catalog_path),
                'official_models': ['stale-model'],
                'models': ['stale-model', 'vendor/model'],
            }

            class Opener:
                def open(self, request, timeout):
                    return io.BytesIO(json.dumps({'models': [
                        {'slug': 'gpt-account-model', 'priority': 1}
                    ]}).encode())

            owner = SimpleNamespace(settings=settings, opener=Opener(), settings_path=None)
            with patch('gateway.server.load_source', return_value=external):
                result = refresh_official_directory(owner, {
                    'Authorization': 'Bearer subscription-token'
                })
            self.assertEqual([item['slug'] for item in result['models']],
                             ['gpt-account-model', 'vendor/model'])
            self.assertEqual(owner.settings['official_models'], ['gpt-account-model'])
            self.assertEqual(owner.settings['models'], ['gpt-account-model', 'vendor/model'])


    def test_http_catalog_preserves_version_and_response_model_passes_route(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / 'models.yaml'
            source.write_text('version: 1\nproviders: {}\n')
            settings = {'source': {'type': 'yaml', 'path': str(source)},
                        'models': ['stale'], 'official_models': ['stale'],
                        'local_token': 'local-test', 'max_concurrent_requests': 1,
                        'catalog': str(directory / 'models.json')}
            gateway = Gateway(settings)
            gateway.settings_path = directory / 'settings.json'
            gateway.settings_path.write_text(json.dumps(settings))
            requests = []

            class Opener:
                def open(self, request, timeout):
                    requests.append(request)
                    return io.BytesIO(b'{"models":[{"slug":"gpt-6.1-sol"}]}')

            gateway.opener = Opener()
            server = Server(('127.0.0.1', 0), gateway.handler())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                headers = {'Authorization': 'Bearer subscription-test-token',
                           'X-Connected-Token': 'local-test', 'ChatGPT-Account-ID': 'account'}
                request = urllib.request.Request(
                    f'http://127.0.0.1:{server.server_port}/models?client_version=0.165.0',
                    headers=headers)
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request) as response:
                    result = json.load(response)
                self.assertEqual(requests[0].full_url,
                                 'https://chatgpt.com/backend-api/codex/models?client_version=0.165.0')
                self.assertEqual(result['models'][0]['slug'], 'gpt-6.1-sol')
                url, payload, outgoing, _ = route(
                    {'model': 'gpt-6.1-sol', 'stream': True, 'input': []}, headers, gateway.settings)
                self.assertEqual(url, 'https://chatgpt.com/backend-api/codex/responses')
                self.assertEqual(outgoing['Authorization'], headers['Authorization'])
                self.assertEqual(payload['model'], 'gpt-6.1-sol')
                saved = gateway.settings_path.read_bytes()
                records = []
                gateway.record = records.append
                for failure in (TimeoutError(),
                                urllib.error.HTTPError('https://chatgpt.com', 503, 'unavailable', {}, None),
                                ValueError('invalid JSON')):
                    with self.subTest(failure=type(failure).__name__), \
                            patch.object(gateway.opener, 'open', side_effect=failure):
                        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request) as response:
                            self.assertEqual(response.status, 200)
                            self.assertEqual(json.load(response), result)
                        self.assertEqual(gateway.settings_path.read_bytes(), saved)
                        self.assertIn('gpt-6.1-sol', gateway.settings['models'])
                        route({'model': 'gpt-6.1-sol', 'stream': True, 'input': []}, headers, gateway.settings)
                    if isinstance(failure, urllib.error.HTTPError):
                        failure.close()
                self.assertEqual(len(records), 3)
                self.assertTrue(all(record['cached_directory'] for record in records))
                anonymous = urllib.request.Request(request.full_url,
                    headers={'X-Connected-Token': 'local-test'})
                with patch.object(gateway.opener, 'open') as upstream:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(anonymous)
                    self.assertEqual(error.exception.code, 401)
                    error.exception.close()
                    upstream.assert_not_called()
                Path(gateway.settings['catalog']).unlink()
                with patch.object(gateway.opener, 'open', side_effect=TimeoutError()):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request)
                    self.assertEqual(error.exception.code, 502)
                    error.exception.close()
                    self.assertEqual(gateway.settings_path.read_bytes(), saved)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_refresh_merges_latest_disk_settings_and_updates_cc_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / 'settings.json'
            catalog_path = directory / 'models.json'
            stale = {'source': {'type': 'cc-switch', 'path': 'unused'},
                     'catalog': str(catalog_path), 'models': ['stale'],
                     'official_models': ['stale'], 'local_token': 'old'}
            latest = dict(stale, local_token='new', custom_setting='preserved')
            path.write_text(json.dumps(latest))
            external = SimpleNamespace(models={'vendor/model': {
                'enabled': True, 'display_name': 'Vendor', 'provider': 'vendor',
                'context_window': 8192}}, bindings={'vendor/model': {'id': 'current'}},
                source_revision='current-revision')
            owner = SimpleNamespace(settings=stale, settings_path=path, opener=None)
            with patch('gateway.server.authenticated_official_catalog',
                       return_value=[{'slug': 'gpt-6.1-sol'}]), \
                    patch('gateway.server.load_source', return_value=external):
                result = refresh_official_directory(owner, {'Authorization': 'Bearer test'})
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['local_token'], 'new')
            self.assertEqual(saved['custom_setting'], 'preserved')
            self.assertEqual(saved['models'], ['gpt-6.1-sol', 'vendor/model'])
            self.assertEqual(saved['cc_snapshot']['models'], result['models'])
            self.assertEqual(saved['cc_snapshot']['bindings'], external.bindings)
            self.assertEqual(saved['cc_snapshot']['revision'], external.source_revision)
            self.assertEqual(json.loads(catalog_path.read_text(encoding='utf-8')), result)
            self.assertEqual(owner.settings, saved)

    def test_failed_settings_write_restores_catalog_and_keeps_memory_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path = directory / 'settings.json'
            catalog_path = directory / 'models.json'
            settings = {'catalog': str(catalog_path), 'models': ['stale'],
                        'official_models': ['stale']}
            path.write_text(json.dumps(settings))
            original = '{"models":[{"slug":"stale"}]}'
            catalog_path.write_text(original)
            owner = SimpleNamespace(settings=settings, settings_path=path, opener=None)
            from management.service import private_write

            def write(target, value):
                if Path(target) == path:
                    raise OSError('simulated settings write failure')
                private_write(target, value)

            with patch('gateway.server.authenticated_official_catalog',
                       return_value=[{'slug': 'fresh'}]), \
                    patch('management.service.private_write', side_effect=write):
                with self.assertRaises(OSError):
                    refresh_official_directory(owner, {})
            self.assertEqual(catalog_path.read_text(), original)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), settings)
            self.assertIs(owner.settings, settings)


    def test_cache_rejects_missing_corrupt_or_mismatched_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'models.json'
            settings = {'catalog': str(path), 'models': ['allowed']}
            self.assertIsNone(cached_directory(settings))
            for content in ('{', '{"models":[{}]}', '{"models":[]}',
                            '{"models":[{"slug":"different"}]}'):
                path.write_text(content)
                self.assertIsNone(cached_directory(settings))
            path.write_text('{"models":[{"slug":"allowed"}]}')
            self.assertEqual(cached_directory(settings), {'models': [{'slug': 'allowed'}]})

    def test_cache_uses_committed_cc_snapshot_when_catalog_file_is_missing(self):
        models = [{'slug': 'official'}, {'slug': 'vendor/model'}]
        settings = {'models': ['official', 'vendor/model'], 'cc_snapshot': {'models': models}}
        self.assertEqual(cached_directory(settings), {'models': models})


if __name__ == '__main__':
    unittest.main()
