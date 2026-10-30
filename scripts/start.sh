#!/usr/bin/env bash
# Deploy run: start the Flask app on the platform-assigned port.
#
# The platform deploy image is Node-based (node:24-bookworm-slim) with no
# system python3. The interpreter is resolved in layers:
#   1. system python3 (sandbox/dev images)
#   2. .python/ vendored into this payload by scripts/build.sh (deploy image)
#   3. apt-get install (last resort, only works as root)
# build.sh pre-installs dependencies into vendor-py/ next to this script and
# sets the same env (PYTHONPATH/LD_LIBRARY_PATH/PYTHONHOME) the probe used.
set -euo pipefail
cd "$(dirname "$0")/.."
# Deploy environment has no PostgreSQL DATABASE_URL; APP_ENV=production would
# abort startup (see platform_app/__init__.py). Use "preview" so the app runs
# with its built-in SQLite database and secure defaults for this platform.
export APP_ENV=preview

PYTHON3_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON3_BIN="$(command -v python3)"
elif [ -x "./.python/bin/python3" ]; then
  PYTHON3_BIN="./.python/bin/python3"
elif command -v apt-get >/dev/null 2>&1 \
  && DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-pip >/dev/null 2>&1; then
  PYTHON3_BIN="$(command -v python3 || true)"
fi

if [ -z "$PYTHON3_BIN" ]; then
  echo "[start] ERROR: no python3 interpreter found (system/.python/apt-get all unavailable)" >&2
  echo "[start] The deploy image is Node-based; build must vendor .python/ via scripts/build.sh" >&2
  exit 1
fi

# Payload layout produced by build.sh: dependencies in vendor-py/, optional
# vendored shared libs in .python/lib, apt-copy fallback needs PYTHONHOME.
if [ -d "./vendor-py" ]; then
  export PYTHONPATH="./vendor-py${PYTHONPATH:+:$PYTHONPATH}"
fi
if [ -d "./.python/lib" ]; then
  export LD_LIBRARY_PATH="./.python/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [ -f "./.python/.needs-pythonhome" ]; then
  export PYTHONHOME="$(cd ./.python && pwd)"
fi

if ! "$PYTHON3_BIN" -c "import flask, gunicorn, sqlalchemy, psycopg, docx, openpyxl, xlrd, pypdf, reportlab, httpx, dotenv" >/dev/null 2>&1; then
  echo "[start] python dependencies missing; installing with $PYTHON3_BIN"
  "$PYTHON3_BIN" -m pip install -q --break-system-packages --retries 2 --timeout 60 -r requirements.txt \
    || "$PYTHON3_BIN" -m pip install -q --retries 2 --timeout 60 -r requirements.txt
fi

exec "$PYTHON3_BIN" app.py
