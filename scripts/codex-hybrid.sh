#!/bin/sh
# Always resolve from the checkout, including paths containing spaces.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    BOOTSTRAP=${CODEX_HYBRID_PYTHON:-${MODEL_ROUTER_PYTHON:-${CONNECTED_PYTHON:-python3}}}
    "$BOOTSTRAP" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "需要 Python 3.11+，可用 CODEX_HYBRID_PYTHON 指定解释器")'
    "$BOOTSTRAP" -m venv "$ROOT/.venv"
fi
if ! "$PYTHON" -c 'import yaml; import psutil; import watchdog' 2>/dev/null; then
    "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m cli "$@"
