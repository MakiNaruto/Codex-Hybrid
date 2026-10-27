from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from desktop import client


class DesktopClientTests(unittest.TestCase):
    def test_windows_dispatches_lifecycle_and_preserves_timeouts(self):
        implementation = Mock()
        target = {'fixture': True}
        implementation.discover.return_value = target
        implementation.close.return_value = client.CloseResult(True)
        implementation.launch.return_value = 'started'
        with patch.object(client.sys, 'platform', 'win32'), \
                patch.object(client, 'import_module', return_value=implementation) as load:
            self.assertEqual(client.discover(Path('fixture')), target)
            self.assertIs(client.processes(target), implementation.processes.return_value)
            self.assertTrue(client.close(target, timeout=7))
            self.assertEqual(client.launch(target, timeout=9), 'started')
        self.assertTrue(all(call.args == ('desktop.windows_client',) for call in load.call_args_list))
        implementation.close.assert_called_once_with(target, timeout=7)
        implementation.launch.assert_called_once_with(target, timeout=9)

    def test_macos_and_other_platforms_fall_back_without_loading_windows(self):
        for platform in ('darwin', 'linux'):
            with self.subTest(platform=platform), patch.object(client.sys, 'platform', platform), \
                    patch.object(client, 'import_module') as load:
                self.assertIsNone(client.discover(Path('fixture')))
                for operation in (client.processes, client.close, client.launch):
                    with self.assertRaisesRegex(client.DesktopControlError, 'unsupported_platform'):
                        operation({})
                load.assert_not_called()
