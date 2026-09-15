#!/usr/bin/env bash
# Deploy run: start the Flask app on the platform-assigned port.
set -euo pipefail
cd "$(dirname "$0")/.."
# Deploy environment has no PostgreSQL DATABASE_URL; APP_ENV=production would
# abort startup (see platform_app/__init__.py). Use "preview" so the app runs
# with its built-in SQLite database and secure defaults for this platform.
export APP_ENV=preview
exec python3 app.py
