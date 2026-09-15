#!/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

PORT=5000

usage() {
  echo "Usage: $0 -p <port>"
}

while getopts "p:h" opt; do
  case "$opt" in
    p)
      PORT="$OPTARG"
      ;;
    h)
      usage
      exit 0
      ;;
    \?)
      echo "Invalid option: -$OPTARG"
      usage
      exit 1
      ;;
  esac
done

export PORT

# Seed schema and default demo data (admin/admin123, S001/123456) so the
# deployment is usable out of the box. init_database.py is idempotent and
# seeds defaults only in non-production mode; existing data is never touched.
python scripts/init_database.py

exec python -m gunicorn --bind "0.0.0.0:$PORT" --workers 2 --timeout 120 app:app
