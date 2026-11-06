#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../../.."

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != x86_64 ]]; then
  echo 'This entry point requires an Intel Mac.' >&2
  exit 1
fi
PYTHON="${STAGE0_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo 'Prepare the Python environment using apps/desktop/docs/build-macos-intel.md first.' >&2
  exit 1
fi
"$PYTHON" -c 'import platform; assert platform.machine() == "x86_64", "Use an x86_64 Python"'
xcrun --find clang >/dev/null
command -v cargo >/dev/null
export CARGO_HOME="${CARGO_HOME:-$PWD/apps/desktop/build/stage0/cargo-home}"
if [[ ! -d apps/desktop/build/stage0/tools/PyInstaller ]]; then
  "$PYTHON" -m pip install --target apps/desktop/build/stage0/tools \
    -r apps/desktop/tools/requirements.txt
fi
cargo fetch --offline --locked --manifest-path apps/desktop/src-tauri/Cargo.toml || \
  cargo fetch --locked --manifest-path apps/desktop/src-tauri/Cargo.toml

"$PYTHON" -X utf8 apps/desktop/tools/build_sidecar.py --tools-dir apps/desktop/build/stage0/tools
"$PYTHON" -X utf8 apps/desktop/validation/verify.py \
  --executable apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  --output apps/desktop/build/stage0/frozen-results-macos-x86_64.json
cargo build --offline --locked --manifest-path apps/desktop/src-tauri/Cargo.toml \
  --target-dir apps/desktop/build/stage0/tauri-target --features custom-protocol
# Tauri's externalBin copies only the executable; onedir libraries must be beside it.
# This also supports running the unbundled shell directly from target/debug.
ditto apps/desktop/dist/stage0/_internal apps/desktop/build/stage0/tauri-target/debug/_internal


mkdir -p "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS"

cp apps/desktop/build/stage0/tauri-target/debug/hybrid-stage0-shell \
  "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-shell"

cp apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-probe"

# Install runtime, metadata and icons, then validate the packaged executable.
"$PYTHON" apps/desktop/tools/platforms/macos.py
"$PYTHON" -X utf8 apps/desktop/validation/verify.py \
  --executable "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-probe" \
  --output apps/desktop/build/stage0/packaged-results-macos-x86_64.json

# Refresh this bundle's icon registration after updating its contents in place.
touch "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "apps/desktop/build/stage0/Codex Hybrid Tray Preview.app"

if [[ "${STAGE0_OPEN_APP:-1}" == 1 ]]; then
  open "./apps/desktop/build/stage0/Codex Hybrid Tray Preview.app"
fi
