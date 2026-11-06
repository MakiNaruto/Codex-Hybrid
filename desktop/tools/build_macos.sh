#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != x86_64 ]]; then
  echo 'This entry point requires an Intel Mac.' >&2
  exit 1
fi
PYTHON="${STAGE0_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo 'Prepare the Python environment using desktop/docs/build-macos-intel.md first.' >&2
  exit 1
fi
"$PYTHON" -c 'import platform; assert platform.machine() == "x86_64", "Use an x86_64 Python"'
xcrun --find clang >/dev/null
command -v cargo >/dev/null
export CARGO_HOME="${CARGO_HOME:-$PWD/desktop/build/stage0/cargo-home}"
if [[ ! -d desktop/build/stage0/tools/PyInstaller ]]; then
  "$PYTHON" -m pip install --target desktop/build/stage0/tools \
    -r desktop/tools/requirements.txt
fi
cargo fetch --offline --locked --manifest-path desktop/src-tauri/Cargo.toml || \
  cargo fetch --locked --manifest-path desktop/src-tauri/Cargo.toml

"$PYTHON" -X utf8 desktop/tools/build_sidecar.py --tools-dir desktop/build/stage0/tools
"$PYTHON" -X utf8 desktop/validation/verify.py \
  --executable desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  --output desktop/build/stage0/frozen-results-macos-x86_64.json
cargo build --offline --locked --manifest-path desktop/src-tauri/Cargo.toml \
  --target-dir desktop/build/stage0/tauri-target --features custom-protocol
# Tauri's externalBin copies only the executable; onedir libraries must be beside it.
# This also supports running the unbundled shell directly from target/debug.
ditto desktop/dist/stage0/_internal desktop/build/stage0/tauri-target/debug/_internal


mkdir -p "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS"

cp desktop/build/stage0/tauri-target/debug/hybrid-stage0-shell \
  "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-shell"

cp desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-probe"

# Install runtime, metadata and icons, then validate the packaged executable.
"$PYTHON" desktop/tools/platforms/macos.py
"$PYTHON" -X utf8 desktop/validation/verify.py \
  --executable "desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-probe" \
  --output desktop/build/stage0/packaged-results-macos-x86_64.json

# Refresh this bundle's icon registration after updating its contents in place.
touch "desktop/build/stage0/Codex Hybrid Tray Preview.app"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "desktop/build/stage0/Codex Hybrid Tray Preview.app"

if [[ "${STAGE0_OPEN_APP:-1}" == 1 ]]; then
  open "./desktop/build/stage0/Codex Hybrid Tray Preview.app"
fi
