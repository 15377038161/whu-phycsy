#!/usr/bin/env bash
# Deploy run: start the Flask app on the platform-assigned port.
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV=production
exec python3 app.py
