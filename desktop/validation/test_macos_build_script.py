"""Exercise macOS dependency preparation with isolated command stubs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools/build_macos.sh'


class MacosBuildScriptTests(unittest.TestCase):
    def run_preparation(self, offline_code=0, online_code=0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / 'desktop/tools'
            tools.mkdir(parents=True)
            (tools / 'build_macos.sh').write_text(SCRIPT.read_text())
            (root / 'desktop/build/stage0/tools/PyInstaller').mkdir(parents=True)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            commands = {
                'uname': 'if [ "$1" = -s ]; then echo Darwin; else echo x86_64; fi',
                'xcrun': 'exit 0',
                'python': 'case "$*" in *build_sidecar.py*) echo SIDECAR; exit 73;; esac',
                'cargo': '''echo "$*" >> "$CARGO_CALLS"
case " $* " in
  *" --offline "*)
    if [ "$OFFLINE_CODE" != 0 ]; then
      echo 'error: no matching package named `serde_json` found' >&2
    fi
    exit "$OFFLINE_CODE";;
  *)
    if [ "$ONLINE_CODE" != 0 ]; then echo 'network unavailable' >&2; fi
    exit "$ONLINE_CODE";;
esac''',
            }
            for name, body in commands.items():
                command = bin_dir / name
                command.write_text('#!/bin/sh\n' + body + '\n')
                command.chmod(0o755)
            calls = root / 'cargo-calls'
            env = dict(os.environ, PATH=f'{bin_dir}:/usr/bin:/bin',
                       STAGE0_PYTHON=str(bin_dir / 'python'), CARGO_HOME=str(root / 'cache'),
                       CARGO_CALLS=str(calls), OFFLINE_CODE=str(offline_code), ONLINE_CODE=str(online_code))
            result = subprocess.run(['bash', str(tools / 'build_macos.sh')], env=env,
                                    capture_output=True, text=True, timeout=10)
            return result, calls.read_text().splitlines()

    def test_cached_dependencies_need_no_network(self):
        result, calls = self.run_preparation()
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn('--offline', calls[0])
        self.assertEqual(result.stderr, '')

    def test_empty_cache_downloads_without_reporting_expected_offline_error(self):
        result, calls = self.run_preparation(offline_code=101)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('--offline', calls[1])
        self.assertNotIn('error:', result.stderr)
        self.assertIn('Downloading locked Cargo dependencies', result.stdout)

    def test_download_failure_stops_before_sidecar_and_identifies_cache(self):
        result, calls = self.run_preparation(offline_code=101, online_code=101)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('SIDECAR', result.stdout)
        self.assertIn('network unavailable', result.stderr)
        self.assertIn('CARGO_HOME=', result.stderr)
