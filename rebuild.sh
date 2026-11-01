#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# 先正常退出测试应用
bash desktop/stage0/build_macos_intel.sh

cp desktop/stage0/tauri/target/debug/hybrid-stage0-shell \
  "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-shell"

cp desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-probe"

# A PyInstaller executable inside Contents/MacOS looks in Contents/Frameworks.
# Verify the installed executable, not only the standalone dist copy.
.venv/bin/python - <<'RUNTIME'
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('build_probe', 'desktop/stage0/build_probe.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
app = Path('desktop/build/stage0/Codex Hybrid Tray Preview.app')
build.install_macos_runtime(app, Path('desktop/dist/stage0/_internal'))
with tempfile.TemporaryDirectory() as home:
    result = subprocess.run([str((app / 'Contents/MacOS/hybrid-stage0-probe').resolve()),
                             'desktop-snapshot'], env={**os.environ, 'HOME': home},
                            capture_output=True, text=True, timeout=15, check=True)
    assert json.loads(result.stdout)['status'] == 'not_configured'
print('Packaged macOS Python runtime verified.')
RUNTIME

# Keep the Finder/Dock icon aligned with the replaceable icon assets.
python3 - <<'ICONS'
from pathlib import Path
import plistlib
import shutil

contents = Path("desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents")
resources = contents / "Resources"
resources.mkdir(exist_ok=True)
shutil.copyfile("desktop/stage0/tauri/icons/icon.icns", resources / "icon.icns")
plist_path = contents / "Info.plist"
with plist_path.open("rb") as stream:
    info = plistlib.load(stream)
info["CFBundleIconFile"] = "icon.icns"
with plist_path.open("wb") as stream:
    plistlib.dump(info, stream)
ICONS

# Refresh this bundle's icon registration after updating its contents in place.
touch "desktop/build/stage0/Codex Hybrid Tray Preview.app"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "desktop/build/stage0/Codex Hybrid Tray Preview.app"

if [[ "${STAGE0_OPEN_APP:-1}" == 1 ]]; then
  open "./desktop/build/stage0/Codex Hybrid Tray Preview.app"
fi
