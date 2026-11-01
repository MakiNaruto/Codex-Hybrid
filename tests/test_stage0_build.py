"""Native packaging target selection; no platform runtime claims."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('stage0_build', Path(__file__).resolve().parents[1] / 'desktop/stage0/build_probe.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class Stage0BuildTests(unittest.TestCase):
    def test_macos_dynamic_backend_is_bundled_only_for_macos(self):
        self.assertEqual(build.hidden_imports('Darwin'), ['desktop.macos_client'])
        self.assertEqual(build.hidden_imports('Windows'), [])

    def test_macos_avoids_onefile_extraction_and_windows_keeps_onefile(self):
        self.assertEqual(build.bundle_mode('Darwin'), '--onedir')
        self.assertEqual(build.bundle_mode('Windows'), '--onefile')

    def test_intel_mac_is_a_native_target(self):
        self.assertEqual(build.native_target('Darwin', 'x86_64'), 'x86_64-apple-darwin')

    def test_existing_targets_are_preserved(self):
        self.assertEqual(build.native_target('Darwin', 'arm64'), 'aarch64-apple-darwin')
        self.assertEqual(build.native_target('Windows', 'AMD64'), 'x86_64-pc-windows-msvc')

    def test_unsupported_architecture_fails_before_building(self):
        for system, machine in [('Linux', 'x86_64'), ('Windows', 'ARM64'), ('Darwin', 'unknown')]:
            with self.subTest(system=system, machine=machine):
                with self.assertRaises(ValueError):
                    build.native_target(system, machine)
