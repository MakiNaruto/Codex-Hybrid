"""macOS application runtime installation and assembly."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.build_paths import BUILD, DIST, TAURI


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


def assemble_app():
    app = BUILD / 'Codex Hybrid Tray Preview.app'
    contents = app / 'Contents'
    install_macos_runtime(app, DIST / '_internal')
    resources = contents / 'Resources'
    resources.mkdir(exist_ok=True)
    shutil.copyfile(TAURI / 'icons/icon.icns', resources / 'icon.icns')
    info = {
        'CFBundleExecutable': 'hybrid-stage0-shell',
        'CFBundleIconFile': 'icon.icns',
        'CFBundleIdentifier': 'local.codex-hybrid.tray-preview',
        'CFBundleName': 'Codex Hybrid Tray Preview',
        'CFBundlePackageType': 'APPL',
        'CFBundleVersion': '0',
        'NSHighResolutionCapable': True,
    }
    with (contents / 'Info.plist').open('wb') as stream:
        plistlib.dump(info, stream)
    # Temporary HOME prevents the packaged snapshot from reading user settings.
    with tempfile.TemporaryDirectory() as home:
        result = subprocess.run([str(contents / 'MacOS/hybrid-stage0-probe'),
                                 'desktop-snapshot'], env={**os.environ, 'HOME': home},
                                capture_output=True, text=True, timeout=15, check=True)
        if json.loads(result.stdout)['status'] != 'not_configured':
            raise RuntimeError('Packaged sidecar did not honor the isolated HOME')
    print('Packaged macOS Python runtime verified.')


if __name__ == '__main__':
    if sys.platform != 'darwin':
        raise SystemExit('This app assembly tool requires macOS')
    assemble_app()
