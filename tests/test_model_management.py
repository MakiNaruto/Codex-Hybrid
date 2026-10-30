"""Management selection persists locally and cannot be bypassed by routing."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from gateway.server import route
from model_catalog.catalog import ConfigError
from model_catalog.sources import load_source, source_key
import test_cc_sync as cc_sync


class ModelManagementTests(unittest.TestCase):
    setUp = cc_sync.CCSyncTests.setUp
    def test_native_adaptations_persist_and_route_without_changing_cc(self):
        from adapters.minimal_responses import MinimalResponsesAdapter
        self.manager.publish()
        before = self.fixture.database.read_bytes()
        self.manager.save_models(self.manager.view()['source_id'], [{'key':'record-a/model-b',
            'responses_compatibility':'native','responses_adaptations':['custom_tools']}])
        settings = self.gateway.settings
        _, _, _, adapt = route({'model':'record-a/model-b','stream':True,'input':[], 'tools':[]},
            {'Authorization':'Bearer fixture-auth-only'}, settings)
        self.assertIsInstance(adapt.__self__, MinimalResponsesAdapter)
        self.assertEqual(load_source(settings).select('record-a/model-b')[1]['responses_adaptations'], ['custom_tools'])
        self.assertEqual(self.fixture.database.read_bytes(), before)
        self.assertEqual(json.loads(self.path.read_text())['model_preferences'], settings['model_preferences'])
        with self.assertRaises(ConfigError):
            self.manager.save_models(self.manager.view()['source_id'], [{'key':'record-a/model-b',
                'responses_adaptations':['guess']}])
        self.assertEqual(self.gateway.settings, settings)
    # Reuse the real SQLite fixture and manager lifecycle, without inheriting its test cases below.
    def test_remove_add_compatibility_survive_sync_and_never_write_cc(self):
        self.manager.publish()
        before = self.fixture.database.read_bytes()
        source_id = self.manager.view()['source_id']
        self.manager.save_models(source_id, [{'key':'record-a/model-a','added':False},
                                             {'key':'record-a/model-b','responses_compatibility':'native'}])
        settings = self.gateway.settings
        self.assertNotIn('record-a/model-a', settings['models'])
        with self.assertRaisesRegex(ConfigError, 'MODEL_NOT_ALLOWED'):
            route({'model':'record-a/model-a','stream':True}, {'Authorization':'Bearer fixture-auth-only'}, settings)
        self.assertEqual(load_source(settings).select('record-a/model-b')[1]['responses_compatibility'],'native')
        self.assertEqual(self.fixture.database.read_bytes(), before)
        self.fixture.write_provider(models=('model-a','model-b','new-model'))
        self.manager.sync_cc()
        self.assertNotIn('record-a/new-model', self.gateway.settings['models'])
        self.assertNotIn('record-a/model-a', self.gateway.settings['models'])
        self.assertEqual(load_source(self.gateway.settings).select('record-a/model-b')[1]['responses_compatibility'],'native')
        self.manager.save_models(source_id, [{'key':'record-a/model-a','added':True}])
        self.assertIn('record-a/model-a', self.gateway.settings['models'])
        persisted=json.loads(self.path.read_text())
        self.assertEqual(persisted['model_preferences'], self.gateway.settings['model_preferences'])

    def test_invalid_batch_and_changed_source_leave_settings_untouched(self):
        self.manager.publish()
        previous = copy.deepcopy(self.gateway.settings)
        for source_id, updates in [
            ('stale-source',[{'key':'record-a/model-a','added':False}]),
            (self.manager.view()['source_id'],[{'key':'record-a/model-a','added':False},{'key':'missing','added':True}]),
            (self.manager.view()['source_id'],[{'key':'record-a/model-a','added':'false'}])]:
            with self.subTest(updates=updates), self.assertRaises(ConfigError):
                self.manager.save_models(source_id, updates)
            self.assertEqual(self.gateway.settings, previous)

    def test_write_failure_preserves_membership_and_directory(self):
        self.manager.publish()
        previous=copy.deepcopy(self.gateway.settings)
        directory=Path(previous['catalog']).read_bytes()
        from management.service import private_write
        def fail_settings(path, value):
            if Path(path)==self.path: raise OSError('fixture')
            private_write(path,value)
        with patch('management.service.private_write',side_effect=fail_settings), self.assertRaises(OSError):
            self.manager.save_models(self.manager.view()['source_id'],[{'key':'record-a/model-a','added':False}])
        self.assertEqual(self.gateway.settings,previous)
        self.assertEqual(Path(previous['catalog']).read_bytes(),directory)

class ModelManagementHTTPTests(unittest.TestCase):
    def setUp(self):
        import test_web_workflow
        self.fixture=test_web_workflow.WebWorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manager=self.fixture.manager
        self.manager.save_provider('vendor',{'protocol':'openai_responses','base_url':'https://fixture.invalid/v1',
            'models':{'a':{'model_id':'a'},'b':{'model_id':'b'}}},'fixture-key')

    def test_http_models_updates_are_authenticated_and_route_effective(self):
        import http.client
        import threading
        from gateway.server import Server
        gateway=self.fixture.gateway
        gateway.settings['management_auth_required']=True
        server=Server(('127.0.0.1',0),gateway.handler())
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def post(authorized=True):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
            headers={'Content-Type':'application/json'}
            if authorized:headers['Authorization']='Bearer '+gateway.settings['management_token']
            body={'source_id':self.manager.view()['source_id'],'updates':[
                {'key':'vendor/a','added':False},{'key':'vendor/b','responses_compatibility':'native'}]}
            connection.request('POST','/manage/api/models',json.dumps(body),headers)
            response=connection.getresponse()
            result=response.status,json.loads(response.read())
            connection.close()
            return result
        self.assertEqual(post(False)[0],403)
        self.assertIn('vendor/a',gateway.settings['models'])
        self.assertEqual(post()[0],200)
        self.assertNotIn('vendor/a',gateway.settings['models'])
        self.assertEqual(load_source(gateway.settings).select('vendor/b')[1]['responses_compatibility'],'native')
