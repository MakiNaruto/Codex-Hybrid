#!/bin/bash
# Intel-only Stage0 build; never starts or modifies the user's Codex.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${STAGE0_PYTHON:-$ROOT/.venv/bin/python}"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != x86_64 ]]; then
  echo 'This entry point requires an Intel Mac.' >&2
  exit 1
fi
"$PYTHON" -c 'import platform; assert platform.machine() == "x86_64", "Use an x86_64 Python"'
xcrun --find clang >/dev/null
command -v cargo >/dev/null
export CARGO_HOME="${CARGO_HOME:-$ROOT/desktop/build/stage0/cargo-home}"
"$PYTHON" -X utf8 desktop/stage0/build_probe.py --tools-dir desktop/build/stage0/tools
"$PYTHON" -X utf8 desktop/stage0/verify.py \
  --executable desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin \
  --output desktop/build/stage0/frozen-results-macos-x86_64.json
PYTHONPATH="$ROOT/src" \
STAGE0_SNAPSHOT_EXECUTABLE="$ROOT/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin" \
  "$PYTHON" -m unittest discover -s tests -p test_desktop_controller_process.py
cargo build --offline --locked --manifest-path desktop/stage0/tauri/Cargo.toml \
  --features custom-protocol
# Tauri's externalBin copies only the executable; onedir libraries must be beside it.
# This also supports running the unbundled shell directly from target/debug.
ditto desktop/dist/stage0/_internal desktop/stage0/tauri/target/debug/_internal

printf '%s\n' 'Stage0 Intel build and frozen checks passed.' \
  'Shell: desktop/stage0/tauri/target/debug/hybrid-stage0-shell' \
  'This is a probe executable, not an app installer or production desktop client.'
