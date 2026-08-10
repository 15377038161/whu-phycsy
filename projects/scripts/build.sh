#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Some sandbox images ship Python where `python3 -m venv` cannot bootstrap
# pip (ensurepip's bundled wheels are missing), leaving a venv with no pip.
# Always start fresh: remove any stale/broken venv, try to create one, and
# fall back to a system-level install when the venv has no usable pip. This
# must never abort so run.sh always gets to execute.
rm -rf .venv
python3 -m venv .venv 2>/dev/null || true

if [ -x ".venv/bin/python" ] && .venv/bin/python -m pip --version >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install -q -r requirements.txt
else
    rm -rf .venv
    python3 -m pip install -q --user -r requirements.txt
fi

echo "Build completed successfully"
