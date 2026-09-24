#!/bin/bash
# Run the Atlantis regeneration driver: forwards every argument to atl_recreate.py
# (caption | batch | review | verify, plus their options). Prefers the project
# venv (.venv, made by make install), then PYTHON, then python3; the interpreter
# needs Pillow, PyYAML and numpy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
fi
PY="${PY:-${PYTHON:-python3}}"

"$PY" -c 'import PIL, yaml, numpy' 2>/dev/null || {
  echo "error: $PY lacks Pillow, PyYAML or numpy - run: make install" >&2
  exit 1
}

exec "$PY" "$SCRIPT_DIR/atl_recreate.py" "$@"
