"""Keep the different CLI byte and management text write contracts explicit."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop.service import private_write as write_client_snapshot
from management.service import private_write as write_management_text


class PrivateWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_client_snapshot_preserves_bytes_and_utf8_text(self):
        path = self.directory / 'snapshot'
        for value, expected in [(b'\xff\x00\r\n', b'\xff\x00\r\n'), ('中文\r\n', '中文\r\n'.encode())]:
            with self.subTest(value=value):
                write_client_snapshot(path, value)
                self.assertEqual(path.read_bytes(), expected)
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    def test_only_management_creates_missing_parents(self):
        path = self.directory / 'nested' / 'settings.json'
        with self.assertRaises(FileNotFoundError):
            write_client_snapshot(path, 'text')
        self.assertFalse(path.parent.exists())
        write_management_text(path, '中文\r\n')
        self.assertEqual(path.read_bytes(), '中文\r\n'.encode())

    def test_management_cleans_failed_temporary_write_and_retains_destination(self):
        path = self.directory / 'settings.json'
        path.write_text('original')
        with patch('management.service.os.replace', side_effect=OSError('replace failed')):
            with self.assertRaises(OSError):
                write_management_text(path, 'replacement')
        self.assertEqual(path.read_text(), 'original')
        self.assertEqual(list(self.directory.glob('*.tmp')), [])

    @unittest.skipIf(os.name == 'nt', 'POSIX mode bits; Windows uses directory ACLs')
    def test_both_writers_create_private_files(self):
        for write in (write_client_snapshot, write_management_text):
            path = self.directory / write.__module__
            write(path, 'private')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @unittest.skipIf(os.name == 'nt', 'Symlink creation can require Windows privileges')
    def test_atomic_replacement_does_not_write_through_destination_symlink(self):
        original = self.directory / 'original'
        original.write_text('keep')
        for write in (write_client_snapshot, write_management_text):
            path = self.directory / write.__module__
            path.symlink_to(original)
            write(path, 'replacement')
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.read_text(), 'replacement')
            self.assertEqual(original.read_text(), 'keep')
