"""Build the stage0 sidecar on its native OS. Run with a Python containing dependencies."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_paths import ROOT, DESKTOP, SIDECAR, BUILD, DIST, WEB


def hidden_imports(system):
    # codex_integration.client uses import_module; static dependency analysis cannot see it.
    modules = {'Darwin': 'codex_integration.platforms.macos.client',
               'Windows': 'codex_integration.platforms.windows.client'}
    return [modules[system]] if system in modules else []


def bundle_mode(system):
    # macOS launches frequently inside the desktop shell: avoid per-launch
    # onefile extraction. Keep the existing Windows packaging contract.
    return '--onedir' if system == 'Darwin' else '--onefile'


def native_target(system, machine):
    targets = {('Windows', 'AMD64'): 'x86_64-pc-windows-msvc',
               ('Darwin', 'arm64'): 'aarch64-apple-darwin',
               ('Darwin', 'x86_64'): 'x86_64-apple-darwin'}
    try:
        return targets[(system, machine)]
    except KeyError:
        raise ValueError('Run on Windows x64 or macOS Intel/arm64 with a matching Python interpreter') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools-dir', type=Path, help='Optional directory containing PyInstaller installed with --target')
    args = parser.parse_args()
    try:
        target = native_target(platform.system(), platform.machine())
    except ValueError as error:
        parser.error(str(error))
    environment = os.environ.copy()
    if args.tools_dir:
        environment['PYTHONPATH'] = str(args.tools_dir.resolve())
    environment['PYINSTALLER_CONFIG_DIR'] = str(BUILD / 'pyinstaller-cache')
    system = platform.system()
    dist = DIST
    output = dist / 'macos-folder' if system == 'Darwin' else dist
    command = [sys.executable, '-X', 'utf8', '-m', 'PyInstaller', '--noconfirm', bundle_mode(system),
               '--name', 'hybrid-stage0-probe', '--paths', str(ROOT / 'src'), '--paths', str(DESKTOP),
               '--add-data', str(WEB) + ':management/web',
               '--python-option', 'X utf8', '--python-option', 'u',
               '--distpath', str(output),
               '--workpath', str(BUILD / ('pyinstaller-' + target)),
               '--specpath', str(BUILD), str(SIDECAR)]
    for module in [*hidden_imports(platform.system()), 'validation.probe']:
        command[-1:-1] = ['--hidden-import', module]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    suffix = '.exe' if os.name == 'nt' else ''
    executable = (output / 'hybrid-stage0-probe' / 'hybrid-stage0-probe'
                  if system == 'Darwin' else output / ('hybrid-stage0-probe' + suffix))
    staged = dist / ('hybrid-stage0-probe-' + target + suffix)
    shutil.copy2(executable, staged)
    if system == 'Darwin':
        # Both the target-suffixed sidecar and manual .app need these adjacent
        # libraries. Never distribute the small onedir executable on its own.
        libraries = dist / '_internal'
        if libraries.exists():
            shutil.rmtree(libraries)  # Generated libraries only; discard stale builds.
        shutil.copytree(executable.parent / '_internal', libraries, symlinks=True)
    print(staged)


if __name__ == '__main__':
    main()
