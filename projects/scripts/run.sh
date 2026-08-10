#!/usr/bin/env bash
# Preview launcher: reads the port from .preview, seeds demo defaults for
# out-of-the-box login, and starts the Flask dev server on 0.0.0.0.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "ERROR: python is not available" >&2
  exit 1
fi

# Only activate the venv when it actually has flask; a cached .venv from a
# sandbox without ensurepip ships no pip/packages and would shadow the working
# system interpreter.
if [ -f ".venv/bin/activate" ] && .venv/bin/python -c "import flask" >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi
PYTHON_BIN="$(command -v python || command -v python3)"

# Ensure dependencies are installed even when build.sh was cached or the venv
# is unusable (sandbox images without ensurepip leave a venv missing pip).
if ! "${PYTHON_BIN}" -c "import flask" >/dev/null 2>&1; then
  echo "[run] flask not found; installing requirements..."
  "${PYTHON_BIN}" -m pip install -q --user -r requirements.txt
fi

# Read the preview port from .preview; fall back to 5000. Never touch 9000.
EXPOSE_PORT="$(awk -F '=' '/^expose_port/ {gsub(/[^0-9]/, "", $2); print $2; exit}' .preview 2>/dev/null || true)"
if [ -z "${EXPOSE_PORT}" ]; then
  EXPOSE_PORT="5000"
fi

# Clear any stale listener on the preview port before starting.
fuser -k "${EXPOSE_PORT}/tcp" 2>/dev/null || true
sleep 1

# Start the Flask dev server on all IPv4 interfaces.
# create_app() already calls init_database() (schema + seed), so no
# separate init_database.py call needed here — it only adds startup delay.
export FLASK_APP=app.py
exec "${PYTHON_BIN}" -m flask run --host=0.0.0.0 --port="${EXPOSE_PORT}"
