#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != x86_64 ]]; then
  echo 'This entry point requires an Intel Mac.' >&2
  exit 1
fi
PYTHON="${STAGE0_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo 'Prepare the Python environment using apps/desktop/docs/build-macos-intel.md first.' >&2
  exit 1
fi
export CARGO_HOME="${CARGO_HOME:-$PWD/apps/desktop/build/stage0/cargo-home}"
if [[ ! -d apps/desktop/build/stage0/tools/PyInstaller ]]; then
  "$PYTHON" -m pip install --target apps/desktop/build/stage0/tools \
    -r apps/desktop/stage0/requirements.txt
fi
cargo fetch --offline --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml || \
  cargo fetch --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml

# 先正常退出测试应用
bash apps/desktop/stage0/build_macos_intel.sh

mkdir -p "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS"

cp apps/desktop/stage0/tauri/target/debug/hybrid-stage0-shell \
  "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-shell"

cp apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-probe"

# A PyInstaller executable inside Contents/MacOS looks in Contents/Frameworks.
# Verify the installed executable, not only the standalone dist copy.
"$PYTHON" - <<'RUNTIME'
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('build_probe', 'apps/desktop/stage0/build_probe.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
app = Path('apps/desktop/build/stage0/Codex Hybrid Tray Preview.app')
build.install_macos_runtime(app, Path('apps/desktop/dist/stage0/_internal'))
with tempfile.TemporaryDirectory() as home:
    result = subprocess.run([str((app / 'Contents/MacOS/hybrid-stage0-probe').resolve()),
                             'desktop-snapshot'], env={**os.environ, 'HOME': home},
                            capture_output=True, text=True, timeout=15, check=True)
    assert json.loads(result.stdout)['status'] == 'not_configured'
print('Packaged macOS Python runtime verified.')
RUNTIME

# Keep the Finder/Dock icon aligned with the replaceable icon assets.
"$PYTHON" - <<'ICONS'
from pathlib import Path
import plistlib
import shutil

contents = Path("apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents")
resources = contents / "Resources"
resources.mkdir(exist_ok=True)
shutil.copyfile("apps/desktop/stage0/tauri/icons/icon.icns", resources / "icon.icns")
plist_path = contents / "Info.plist"
info = {
    "CFBundleExecutable": "hybrid-stage0-shell",
    "CFBundleIconFile": "icon.icns",
    "CFBundleIdentifier": "local.codex-hybrid.tray-preview",
    "CFBundleName": "Codex Hybrid Tray Preview",
    "CFBundlePackageType": "APPL",
    "CFBundleVersion": "0",
    "NSHighResolutionCapable": True,
}
with plist_path.open("wb") as stream:
    plistlib.dump(info, stream)
ICONS

# Refresh this bundle's icon registration after updating its contents in place.
touch "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app"

if [[ "${STAGE0_OPEN_APP:-1}" == 1 ]]; then
  open "./apps/desktop/build/stage0/Codex Hybrid Tray Preview.app"
fi
