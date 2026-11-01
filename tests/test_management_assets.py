"""Shared pages must reference assets that the browser HTTP adapter can serve."""
import io
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import urljoin

from management.http import WEB, handle


class ManagementAssetTests(unittest.TestCase):
    def test_all_page_scripts_and_styles_are_served(self):
        for page in ('index.html', 'entry.html'):
            references = re.findall(r'(?:src|href)="([^"#?]+\.(?:js|css))"',
                                    (WEB / page).read_text(encoding='utf-8'))
            self.assertTrue(references, page)
            for reference in references:
                asset = urljoin('/manage/', reference)
                with self.subTest(page=page, asset=asset):
                    request = SimpleNamespace(
                        path=asset, headers={'Host': '127.0.0.1:1234'},
                        server=SimpleNamespace(server_port=1234), send_response=Mock(),
                        send_header=Mock(), end_headers=Mock(), wfile=io.BytesIO())
                    self.assertTrue(handle(request, SimpleNamespace(settings={}), 'GET'))
                    request.send_response.assert_called_once_with(200)
                    self.assertEqual(request.wfile.getvalue(),
                                     (WEB / asset.rsplit('/', 1)[-1]).read_bytes())
