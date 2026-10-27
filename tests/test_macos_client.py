from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop import macos_client as client


class MacOSClientTests(unittest.TestCase):
    def test_discovery_validates_bundle_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)/'Codex.app'
            executable = bundle/'Contents/MacOS/Codex'
            executable.parent.mkdir(parents=True)
            executable.touch()
            plist = bundle/'Contents/Info.plist'
            for identity, available in [('other.application', False), (client.BUNDLE_ID, True)]:
                plist.write_bytes(plistlib.dumps({'CFBundleIdentifier': identity, 'CFBundleExecutable': 'Codex'}))
                with patch.object(client.sys, 'platform', 'darwin'), patch.object(client.subprocess, 'run',
                        return_value=Mock(stdout=str(bundle))):
                    target = client.discover(Path.home()/'.codex')
                    self.assertEqual(bool(target), available)
                    if available:
                        self.assertEqual(target['executable'], str(executable.resolve()))

    def test_custom_home_is_not_automatically_launched(self):
        with patch.object(client.sys, 'platform', 'darwin'), patch.object(client.subprocess, 'run') as run:
            self.assertIsNone(client.discover('/tmp/custom-codex-home'))
            run.assert_not_called()

    def test_close_permission_failure_does_not_terminate_process(self):
        process = Mock()
        with patch.object(client, 'processes', return_value=[process]), patch.object(client.subprocess, 'run',
                side_effect=subprocess.CalledProcessError(1, 'osascript')):
            result = client.close({'bundle': '/Applications/Codex.app'})
        self.assertFalse(result)
        self.assertEqual(result.reason, 'quit_denied')
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_close_requires_process_exit(self):
        with patch.object(client, 'processes', return_value=[Mock()]), patch.object(client.subprocess, 'run'), \
                patch.object(client.psutil, 'wait_procs', return_value=([], [Mock()])):
            self.assertEqual(client.close({'bundle': '/Applications/Codex.app'}).reason, 'exit_timeout')

    def test_launch_uses_exact_bundle_and_checks_process(self):
        with patch.object(client.subprocess, 'run') as run, patch.object(client, 'processes', return_value=[Mock()]):
            self.assertEqual(client.launch({'bundle': '/Applications/Codex.app'}), 'started')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/open', '-a', '/Applications/Codex.app'])

    def test_process_matching_excludes_other_apps_and_helpers(self):
        target = {'executable': '/Applications/Codex.app/Contents/MacOS/Codex'}
        exact, other, helper = Mock(), Mock(), Mock()
        for process in (exact, other, helper):
            process.info = {'name': 'Codex'}
            process.exe.return_value = target['executable']
            process.cmdline.return_value = [target['executable']]
        other.exe.return_value = '/tmp/Codex'
        helper.cmdline.return_value.append('--type=renderer')
        with patch.object(client.psutil, 'process_iter', return_value=[exact, other, helper]):
            self.assertEqual(client.processes(target), [exact])
