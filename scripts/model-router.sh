#!/bin/sh
# Compatibility entry point for existing installations.
exec sh "$(dirname -- "$0")/codex-model-bridge.sh" "$@"
