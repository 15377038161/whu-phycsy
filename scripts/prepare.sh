#!/usr/bin/env bash
# Dev build: install Python dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."
pip3 install -q --break-system-packages -r requirements.txt
echo "prepare ok"
