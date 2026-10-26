import json
import unittest

from model_catalog.cc_switch import decode
from model_catalog.catalog import Catalog


class CCProtocolTests(unittest.TestCase):
    def endpoint(self, base, wire='responses', meta=None):
        parsed = decode('codex', json.dumps({
            'config': {'model_provider': 'vendor', 'model': 'example',
                       'model_providers': {'vendor': {'base_url': base, 'wire_api': wire}}},
            'auth': {'OPENAI_API_KEY': 'test-only'},
        }), meta)
        catalog = Catalog('unused.yaml', data={'version': 1, 'providers': {'vendor': {
            'base_url': base, 'protocol': parsed['protocol'],
            'credentials': {'api_key_env': 'UNUSED'},
            'models': {'default': {'model_id': 'example'}},
        }}})
        return catalog.providers['vendor']['endpoint']

    def test_vendor_codex_records_use_chat_endpoint(self):
        for base in ['https://dashscope.aliyuncs.com/compatible-mode/v1',
                     'https://dashscope-intl.aliyuncs.com/compatible-mode/v1/',
                     'https://open.bigmodel.cn/api/coding/paas/v4',
                     'https://open.bigmodel.cn/api/paas/v4',
                     'https://api.z.ai/api/coding/paas/v4']:
            with self.subTest(base=base):
                self.assertEqual(self.endpoint(base, meta={'apiFormat': 'openai_chat'}), base.rstrip('/') + '/chat/completions')

    def test_other_responses_endpoints_are_preserved(self):
        for base in ['https://api.openai.com/v1', 'https://proxy.example/v1',
                     'https://open.bigmodel.cn/custom',
                     'https://open.bigmodel.cn.example/api/coding/paas/v4']:
            with self.subTest(base=base):
                self.assertEqual(self.endpoint(base), base + '/responses')

    def test_metadata_overrides_wire_in_both_directions(self):
        base = 'https://open.bigmodel.cn/api/coding/paas/v4'
        self.assertEqual(self.endpoint(base, 'responses', {'apiFormat': 'openai_chat'}),
                         base + '/chat/completions')
        self.assertEqual(self.endpoint(base, 'chat', {'apiFormat': 'openai_responses'}),
                         base + '/responses')

    def test_explicit_chat_is_preserved(self):
        self.assertEqual(self.endpoint('https://proxy.example/v1', 'chat'),
                         'https://proxy.example/v1/chat/completions')


if __name__ == '__main__':
    unittest.main()
