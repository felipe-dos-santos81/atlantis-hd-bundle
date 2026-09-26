#!/bin/bash
# Start ComfyUI from its own checkout and venv (default ~/ComfyUI), listening on :8188.
set -euo pipefail

COMFY_DIR="${COMFY_DIR:-$HOME/ComfyUI}"
PY="$COMFY_DIR/venv/bin/python"

[ -f "$COMFY_DIR/main.py" ] || { echo "error: $COMFY_DIR/main.py not found - set COMFY_DIR" >&2; exit 1; }
[ -x "$PY" ] || { echo "error: $PY not found - create the ComfyUI venv first" >&2; exit 1; }

cd "$COMFY_DIR"
exec "$PY" main.py --listen 0.0.0.0 --port 8188 "$@"
