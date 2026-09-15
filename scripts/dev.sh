#!/usr/bin/env bash
# Dev run: start Flask with debug/reloader on the platform-assigned port.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 app.py
