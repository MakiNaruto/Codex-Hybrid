#!/bin/bash
set -euo pipefail
exec bash "$(dirname "$0")/../apps/desktop/tools/build_macos.sh" "$@"
