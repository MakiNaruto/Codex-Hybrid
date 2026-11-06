#!/bin/bash
set -euo pipefail
exec bash "$(dirname "$0")/../desktop/tools/build_macos.sh" "$@"
