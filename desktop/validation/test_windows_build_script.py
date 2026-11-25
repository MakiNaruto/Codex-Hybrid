"""Exercise the Windows build entry point without running the build toolchain."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/build_desktop.ps1'
SHELLS = [shell for name in ('powershell', 'pwsh') if (shell := shutil.which(name))]


@unittest.skipUnless(SHELLS, 'PowerShell is required')
class WindowsBuildScriptTests(unittest.TestCase):
    def run_entry_point(self, shell, target):
        with tempfile.TemporaryDirectory(prefix='desktop build ') as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            tools = root / 'desktop/tools'
            tools.mkdir(parents=True)
            wrapper = root / 'scripts/build_desktop.ps1'
            wrapper.write_text(SCRIPT.read_text())
            (tools / 'build_windows.ps1').write_text('[CmdletBinding()]\nparam()\n' + target)
            return subprocess.run(
                [shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(wrapper)],
                cwd=root.parent, capture_output=True, text=True, timeout=30,
            )

    def test_parameterless_invocation_reaches_platform_script(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_entry_point(shell, 'Write-Output "TARGET_REACHED"\nexit 0\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('TARGET_REACHED', result.stdout)
                self.assertEqual(result.stderr, '')

    def test_platform_exit_code_is_preserved(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_entry_point(shell, 'exit 37\n')
                self.assertEqual(result.returncode, 37, result.stderr)

    def test_platform_error_fails_entry_point(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_entry_point(shell, 'throw "BUILD_FAILED"\n')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('BUILD_FAILED', result.stderr)
