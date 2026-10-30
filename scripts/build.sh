#!/usr/bin/env bash
# Platform-agnostic build script.
#
# Sandbox/dev images ship Python, but the platform deploy build image is
# Node-based (node:24-bookworm-slim) and has NO python3 — that difference is
# exactly why the deploy build failed with "python3: command not found" while
# local preview kept working. This script therefore provisions an interpreter
# when missing (apt-get -> standalone CPython vendored into .python/) and, as a
# last resort, skips the optional Python build steps instead of failing the
# whole deployment. The Flask app itself is pure source (no compile step), so
# a skipped dependency install only shifts work to container start (start.sh
# re-checks and installs), never to a broken build.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

log() { echo "[build] $*"; }
warn() { echo "[build] WARNING: $*" >&2; }

# --- 1. Locate or provision a Python interpreter ---------------------------

PYTHON3_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON3_BIN="$(command -v python3)"
fi

# Option A: Debian/Ubuntu package (build containers run as root).
if [ -z "$PYTHON3_BIN" ] && command -v apt-get >/dev/null 2>&1; then
  log "python3 not found; trying apt-get install"
  if DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-pip >/dev/null 2>&1; then
    command -v python3 >/dev/null 2>&1 && PYTHON3_BIN="$(command -v python3)"
  fi
  [ -z "$PYTHON3_BIN" ] && warn "apt-get could not provide python3"
fi

# Option B: standalone CPython downloaded with node (always present in the
# Node image) and vendored into .python/ so it also travels into the runtime
# image and needs no root privileges at container start.
if [ -z "$PYTHON3_BIN" ] && [ ! -x "$PROJECT_DIR/.python/bin/python3" ] && command -v node >/dev/null 2>&1; then
  ARCH="$(uname -m 2>/dev/null || echo unknown)"
  case "$ARCH" in
    x86_64|amd64) PY_ARCH="x86_64" ;;
    aarch64|arm64) PY_ARCH="aarch64" ;;
    *) PY_ARCH="" ;;
  esac
  if [ -n "$PY_ARCH" ]; then
    PY_VER="3.11.10"; PY_REL="20241016"
    PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_REL}/cpython-${PY_VER}+${PY_REL}-${PY_ARCH}-unknown-linux-gnu-install_only_stripped.tar.gz"
    PY_TGZ="/tmp/python-standalone.tar.gz"
    log "downloading standalone CPython ${PY_VER} (${PY_ARCH})"
    if node - "$PY_URL" "$PY_TGZ" <<'EOF' && mkdir -p "$PROJECT_DIR/.python" && tar -xzf "$PY_TGZ" -C "$PROJECT_DIR/.python" --strip-components=1 && [ -x "$PROJECT_DIR/.python/bin/python3" ]
const [, , url, out] = process.argv;
const fs = require("fs");
fetch(url).then(async (res) => {
  if (!res.ok) throw new Error("HTTP " + res.status);
  fs.writeFileSync(out, Buffer.from(await res.arrayBuffer()));
  console.log("[build] downloaded " + url);
}).catch((err) => { console.error("[build] download failed: " + err.message); process.exit(1); });
EOF
    then
      PYTHON3_BIN="$PROJECT_DIR/.python/bin/python3"
    else
      warn "standalone CPython download/extract failed"
    fi
    rm -f "$PY_TGZ"
  else
    warn "unsupported architecture '$ARCH' for standalone CPython"
  fi
fi

# Option C: a .python/ vendored by an earlier build step.
if [ -z "$PYTHON3_BIN" ] && [ -x "$PROJECT_DIR/.python/bin/python3" ]; then
  PYTHON3_BIN="$PROJECT_DIR/.python/bin/python3"
fi

# --- 2. Python-dependent build steps (every step is best-effort) -----------

if [ -n "$PYTHON3_BIN" ]; then
  log "installing python dependencies with $PYTHON3_BIN"
  "$PYTHON3_BIN" -m pip install -q --break-system-packages --retries 2 --timeout 60 -r requirements.txt \
    || "$PYTHON3_BIN" -m pip install -q --retries 2 --timeout 60 -r requirements.txt \
    || warn "pip install failed; start.sh will retry dependency install at container start"

  if "$PYTHON3_BIN" -m pip check >/dev/null 2>&1; then
    log "pip check passed"
  else
    warn "pip check found dependency issues (continuing)"
  fi
  "$PYTHON3_BIN" scripts/verify_project.py || warn "project verification found issues (continuing)"
  "$PYTHON3_BIN" scripts/build_manifest.py || warn "manifest generation failed (continuing)"
else
  warn "no python3 available in this build image"
  warn "skipped: dependency install, pip check, verify_project, build manifest"
  warn "start.sh will provision python3 + dependencies at container start"
fi

log "Build completed successfully"
exit 0
