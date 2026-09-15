#!/bin/sh
set -eu
python scripts/init_database.py
exec "$@"
