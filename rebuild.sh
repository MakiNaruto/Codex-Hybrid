#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# 先正常退出测试应用
bash desktop/stage0/build_macos_intel.sh

cp desktop/stage0/tauri/target/debug/hybrid-stage0-shell \
  "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-shell"

cp desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-probe"

# The macOS sidecar is onedir; copy its libraries alongside the executable.
ditto desktop/dist/stage0/_internal \
  "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/_internal"

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

open "./desktop/build/stage0/Codex Hybrid Tray Preview.app"