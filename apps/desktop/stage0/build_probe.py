"""Build the stage0 sidecar on its native OS. Run with a Python containing dependencies."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def install_macos_runtime(app, libraries):
    """PyInstaller uses Contents/Frameworks when its executable is inside MacOS."""
    contents = Path(app) / 'Contents'
    frameworks = contents / 'Frameworks'
    if frameworks.is_symlink():
        frameworks.unlink()
    if frameworks.exists():
        raise ValueError('Refusing to replace an existing app Frameworks directory')
    target = contents / 'MacOS/_internal'
    # This is generated runtime output. Replace it so removed modules and
    # framework symlinks from an earlier build cannot survive a rebuild.
    if target.is_symlink():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    shutil.copytree(libraries, target, symlinks=True)
    frameworks.symlink_to('MacOS/_internal', target_is_directory=True)


def hidden_imports(system):
    # codex_integration.client uses import_module; static dependency analysis cannot see it.
    modules = {'Darwin': 'codex_integration.macos_client',
               'Windows': 'codex_integration.windows_client'}
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
    environment['PYINSTALLER_CONFIG_DIR'] = str(ROOT / 'apps/desktop/build/stage0/pyinstaller-cache')
    system = platform.system()
    dist = ROOT / 'apps/desktop/dist/stage0'
    output = dist / 'macos-folder' if system == 'Darwin' else dist
    command = [sys.executable, '-X', 'utf8', '-m', 'PyInstaller', '--noconfirm', bundle_mode(system),
               '--name', 'hybrid-stage0-probe', '--paths', str(ROOT / 'src'),
               '--add-data', str(ROOT / 'src/management/web') + ':management/web',
               '--python-option', 'X utf8', '--python-option', 'u',
               '--distpath', str(output),
               '--workpath', str(ROOT / 'apps/desktop/build/stage0' / ('pyinstaller-' + target)),
               '--specpath', str(ROOT / 'apps/desktop/build/stage0'), str(Path(__file__).with_name('probe.py'))]
    for module in hidden_imports(platform.system()):
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
