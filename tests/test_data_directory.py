import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop.paths import data_directory, check_legacy_installation
from desktop.preferences import configure


class DataDirectoryTests(unittest.TestCase):
    def test_default_is_user_directory_independent_of_legacy_home(self):
        with patch.dict(os.environ, {'CODEX_HYBRID_HOME': '/old'}, clear=True), patch('pathlib.Path.home', return_value=Path('/user')):
            self.assertEqual(data_directory(), Path('/user/.codex-hybrid'))

    def test_explicit_directory_overrides_environment(self):
        with patch.dict(os.environ, {'CODEX_HYBRID_DATA_DIR': '/environment'}, clear=True):
            self.assertEqual(data_directory('/explicit'), Path('/explicit').resolve())
            self.assertEqual(data_directory(), Path('/environment').resolve())

    def test_legacy_pointer_requires_explicit_selection_without_reading_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'cli-config.json').write_text('invalid legacy JSON')
            with patch.dict(os.environ, {'CODEX_HYBRID_HOME': temp}, clear=True), \
                    patch('pathlib.Path.home', return_value=root):
                with self.assertRaisesRegex(ValueError, '--data-dir'):
                    check_legacy_installation(root / 'new')
                check_legacy_installation(root / 'new', explicit=True)
                self.assertFalse((root / 'new').exists())

    def test_config_rejects_removed_write_options(self):
        with self.assertRaises(SystemExit) as error:
            configure(['--set', '--port', '18892'])
        self.assertEqual(error.exception.code, 2)

    def test_config_inspects_custom_directory_without_creating_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'instance'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                configure(['--data-dir', str(target)])
            self.assertIn(str(target), output.getvalue())
            self.assertFalse(target.exists())
