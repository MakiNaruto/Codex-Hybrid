"""Checkout bootstrap paths and argument forwarding without starting a service."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from cli import bootstrap
from desktop import service


class BootstrapTests(unittest.TestCase):
    def test_relocated_bootstrap_preserves_root_and_literal_arguments(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(bootstrap.ROOT, root)
        arguments = ['status', '--data-dir', 'C:/Data with spaces/&literal']
        with patch.object(bootstrap.sys, 'argv', ['bootstrap.py', *arguments]), \
                patch.object(Path, 'is_file', return_value=True), \
                patch.object(bootstrap.subprocess, 'run') as check, \
                patch.object(bootstrap.subprocess, 'call', return_value=7) as invoke:
            check.return_value.returncode = 0
            self.assertEqual(bootstrap.main(), 7)
        command = invoke.call_args.args[0]
        self.assertEqual(command[1:], ['-m', 'cli', *arguments])
        self.assertEqual(Path(command[0]).parent.parent, root / '.venv')
        self.assertEqual(invoke.call_args.kwargs['cwd'], root)
        self.assertEqual(invoke.call_args.kwargs['env']['PYTHONPATH'].split(os.pathsep)[0], str(root / 'src'))

    def test_gateway_ownership_accepts_new_and_legacy_entries_only_for_this_instance(self):
        processes = []
        for index, entry in enumerate(('src/gateway/entry.py', 'scripts/gateway.py')):
            command = ['python', str(service.ROOT / entry), '--settings', str(service.RUNTIME / 'settings.json')]
            processes.append(SimpleNamespace(info={'cmdline': command}, pid=index + 1))
        foreign = ['python', str(service.ROOT / 'src/gateway/entry.py'), '--settings',
                   str(service.RUNTIME / 'other-settings.json')]
        processes.append(SimpleNamespace(info={'cmdline': foreign}, pid=3))
        with patch('psutil.process_iter', return_value=processes):
            self.assertEqual([process.pid for process in service.owned_gateway_processes()], [1, 2])


if __name__ == '__main__':
    unittest.main()
