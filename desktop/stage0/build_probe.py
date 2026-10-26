"""Build the stage0 sidecar on its native OS. Run with a Python containing dependencies."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools-dir', type=Path, help='Optional directory containing PyInstaller installed with --target')
    args = parser.parse_args()
    targets = {('Windows', 'AMD64'): 'x86_64-pc-windows-msvc',
               ('Darwin', 'arm64'): 'aarch64-apple-darwin'}
    target = targets.get((platform.system(), platform.machine()))
    if target is None:
        parser.error('Run on Windows x64 or macOS arm64 with a matching Python interpreter')
    environment = os.environ.copy()
    if args.tools_dir:
        environment['PYTHONPATH'] = str(args.tools_dir.resolve())
    environment['PYINSTALLER_CONFIG_DIR'] = str(ROOT / 'desktop/build/stage0/pyinstaller-cache')
    command = [sys.executable, '-X', 'utf8', '-m', 'PyInstaller', '--noconfirm', '--onefile',
               '--name', 'hybrid-stage0-probe', '--paths', str(ROOT / 'src'),
               '--add-data', str(ROOT / 'src/management/web') + ':management/web',
               '--python-option', 'X utf8', '--python-option', 'u',
               '--distpath', str(ROOT / 'desktop/dist/stage0'),
               '--workpath', str(ROOT / 'desktop/build/stage0/pyinstaller'),
               '--specpath', str(ROOT / 'desktop/build/stage0'), str(Path(__file__).with_name('probe.py'))]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    suffix = '.exe' if os.name == 'nt' else ''
    executable = ROOT / ('desktop/dist/stage0/hybrid-stage0-probe' + suffix)
    shutil.copy2(executable, executable.with_name('hybrid-stage0-probe-' + target + suffix))
    print(executable)


if __name__ == '__main__':
    main()
