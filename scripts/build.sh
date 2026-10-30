#!/usr/bin/env bash
# Platform-agnostic build script (Python/Flask app on a Node-based platform image).
#
# Why this exists: the platform deploy pipeline builds with its own Dockerfile
# (nextjs-v3 profile, node:24-bookworm-slim) and its runtime stage hard-codes:
#   COPY --from=build /app/.next/standalone ./      <- becomes /app in runtime
#   COPY --from=build /app/.next/static ./.next/static
#   COPY --from=build /app/public ./public
# then launches the payload (Next.js standalone convention: `node server.js`,
# non-root `node` user, NO system Python in the runtime image). Our repo has no
# Next.js, so this script assembles a self-contained runtime payload that
# satisfies that contract:
#   .next/standalone/  = vendored relocatable CPython (.python/) + Flask app
#                        source + server.js entry that spawns the Flask app
#   .next/static/, public/ = web assets (kept non-empty so the COPY steps work)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

log() { echo "[build] $*"; }
warn() { echo "[build] WARNING: $*" >&2; }
fatal() { echo "[build] FATAL: $*" >&2; exit 1; }

PY_VER="3.11.10"; PY_REL="20241016"
ARCH="$(uname -m 2>/dev/null || echo unknown)"
case "$ARCH" in
  x86_64|amd64) PY_ARCH="x86_64" ;;
  aarch64|arm64) PY_ARCH="aarch64" ;;
  *) PY_ARCH="" ;;
esac
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_REL}/cpython-${PY_VER}+${PY_REL}-${PY_ARCH}-unknown-linux-gnu-install_only_stripped.tar.gz"

# --- 1. Locate or provision a BUILD-time Python interpreter ----------------
# Used for verify_project / build_manifest. The runtime payload (section 3)
# vendors its own interpreter regardless of what is available here.

PYTHON3_BIN=""
command -v python3 >/dev/null 2>&1 && PYTHON3_BIN="$(command -v python3)"

if [ -z "$PYTHON3_BIN" ] && command -v apt-get >/dev/null 2>&1; then
  log "python3 not found; trying apt-get install"
  if DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-pip >/dev/null 2>&1; then
    command -v python3 >/dev/null 2>&1 && PYTHON3_BIN="$(command -v python3)"
  fi
  [ -z "$PYTHON3_BIN" ] && warn "apt-get could not provide python3"
fi

# Download a standalone CPython into $PROJECT_DIR/.python (shared by build-time
# use and the runtime payload).
if [ -n "$PY_ARCH" ] && [ ! -x "$PROJECT_DIR/.python/bin/python3" ]; then
  log "downloading standalone CPython ${PY_VER} (${PY_ARCH})"
  PY_TGZ="/tmp/python-standalone.tar.gz"
  rm -f "$PY_TGZ"
  node - "$PY_URL" "$PY_TGZ" <<'EOF'
const [, , url, out] = process.argv;
const fs = require("fs");
fetch(url).then(async (res) => {
  if (!res.ok) throw new Error("HTTP " + res.status);
  fs.writeFileSync(out, Buffer.from(await res.arrayBuffer()));
  console.log("[build] downloaded " + url);
}).catch((err) => { console.error("[build] download failed: " + err.message); process.exit(1); });
EOF
  if [ -s "$PY_TGZ" ]; then
    rm -rf "$PROJECT_DIR/.python"
    mkdir -p "$PROJECT_DIR/.python"
    if tar -xzf "$PY_TGZ" -C "$PROJECT_DIR/.python" --strip-components=1 && [ -x "$PROJECT_DIR/.python/bin/python3" ]; then
      [ -z "$PYTHON3_BIN" ] && PYTHON3_BIN="$PROJECT_DIR/.python/bin/python3"
    else
      warn "standalone CPython extract failed"; rm -rf "$PROJECT_DIR/.python"
    fi
  else
    warn "standalone CPython download produced no file"
  fi
  rm -f "$PY_TGZ"
fi
[ -z "$PYTHON3_BIN" ] && [ -x "$PROJECT_DIR/.python/bin/python3" ] && PYTHON3_BIN="$PROJECT_DIR/.python/bin/python3"

# --- 2. BUILD-time Python steps (best-effort, never fail the build) ---------

if [ -n "$PYTHON3_BIN" ]; then
  log "build-time interpreter: $PYTHON3_BIN"
  "$PYTHON3_BIN" -m pip install -q --break-system-packages --retries 2 --timeout 60 -r requirements.txt \
    || "$PYTHON3_BIN" -m pip install -q --retries 2 --timeout 60 -r requirements.txt \
    || warn "pip install failed for build-time interpreter (continuing)"
  "$PYTHON3_BIN" scripts/verify_project.py || warn "project verification found issues (continuing)"
  "$PYTHON3_BIN" scripts/build_manifest.py || warn "manifest generation failed (continuing)"
else
  warn "no build-time python3 available; skipped verify/manifest"
fi

# --- 3. Assemble the runtime payload (.next/standalone) ---------------------
# The runtime image has NO python3 and runs as the non-root `node` user, so the
# payload must carry a relocatable interpreter and all dependencies.

STANDALONE_DIR="$PROJECT_DIR/.next/standalone"
log "assembling runtime payload at .next/standalone"

# Fallback: no standalone download (e.g. GitHub unreachable) but a build-time
# python exists -> assemble a relocatable python by copying the binary, stdlib
# and every non-glibc shared library it links against. A marker file makes the
# runtime entry set PYTHONHOME for this layout.
vendor_payload_python_fallback() {
  local src_bin dest ver so lib
  src_bin="$(readlink -f "$PYTHON3_BIN")"
  [ -x "$src_bin" ] || return 1
  dest="$PROJECT_DIR/.python"
  rm -rf "$dest"
  mkdir -p "$dest/bin" "$dest/lib"
  cp "$src_bin" "$dest/bin/python3"
  ver="$("$src_bin" -c 'import sys;print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
  [ -d "/usr/lib/$ver" ] && cp -r "/usr/lib/$ver" "$dest/lib/$ver"
  for so in "$dest/bin/python3" "$dest/lib/$ver"/lib-dynload/*.so; do
    [ -e "$so" ] || continue
    ldd "$so" 2>/dev/null | awk '/=> \//{print $3} /^\//{print $1}'
  done | sort -u | while read -r lib; do
    case "$lib" in
      */libc.so*|*/libm.so*|*/libdl.so*|*/libpthread.so*|*/librt.so*|*/libresolv.so*|*/ld-linux*) ;;
      *) cp -n "$lib" "$dest/lib/" 2>/dev/null ;;
    esac
  done
  touch "$dest/.needs-pythonhome"
  [ -x "$dest/bin/python3" ]
}

if [ ! -x "$PROJECT_DIR/.python/bin/python3" ]; then
  warn "standalone CPython unavailable; trying relocatable assembly from $PYTHON3_BIN"
  vendor_payload_python_fallback || fatal "cannot vendor a runtime Python interpreter"
fi

PAYLOAD_PY="$PROJECT_DIR/.python/bin/python3"
PAYLOAD_HOME="$PROJECT_DIR/.python"
[ -f "$PAYLOAD_HOME/.needs-pythonhome" ] && export PYTHONHOME="$PAYLOAD_HOME"

# Pick an interpreter that actually has pip to perform the --target install.
# The downloaded standalone CPython ships pip, but the apt-copy fallback
# interpreter does NOT: Debian keeps pip in the separate python3-pip package
# (/usr/lib/python3/dist-packages), which the fallback assembly never copies,
# so `"$PAYLOAD_PY" -m pip` dies with "No module named pip". The build-time
# system python is the same CPython version on the same platform, and
# `--target` installs into a plain directory, so its pip works for either
# interpreter source.
VENDOR_PY_BIN="$PAYLOAD_PY"
if ! "$VENDOR_PY_BIN" -m pip --version >/dev/null 2>&1; then
  if [ -n "$PYTHON3_BIN" ] && env -u PYTHONHOME "$PYTHON3_BIN" -m pip --version >/dev/null 2>&1; then
    unset PYTHONHOME
    VENDOR_PY_BIN="$PYTHON3_BIN"
    log "payload interpreter has no pip; using build-time interpreter for vendor install"
  fi
fi
if ! "$VENDOR_PY_BIN" -m pip --version >/dev/null 2>&1; then
  [ -n "$PYTHON3_BIN" ] && env -u PYTHONHOME "$PYTHON3_BIN" -m ensurepip --upgrade >/dev/null 2>&1
fi
"$VENDOR_PY_BIN" -m pip --version >/dev/null 2>&1 \
  || fatal "no interpreter with pip available to install payload dependencies"

# Install runtime dependencies into a vendor dir inside the payload; the
# runtime entry adds it to PYTHONPATH. Uniform for both interpreter sources.
log "installing runtime dependencies into payload vendor dir"
rm -rf "$PROJECT_DIR/vendor-py"
"$VENDOR_PY_BIN" -m pip install -q --no-cache-dir --break-system-packages --upgrade \
  --retries 2 --timeout 60 --target "$PROJECT_DIR/vendor-py" -r requirements.txt \
  || "$VENDOR_PY_BIN" -m pip install -q --no-cache-dir --upgrade \
  --retries 2 --timeout 60 --target "$PROJECT_DIR/vendor-py" -r requirements.txt \
  || fatal "pip install into payload vendor dir failed"
unset PYTHONHOME

# Fresh payload assembly every build.
rm -rf "$STANDALONE_DIR" "$PROJECT_DIR/.next/static" "$PROJECT_DIR/public"
mkdir -p "$STANDALONE_DIR/.next" "$PROJECT_DIR/.next/static" "$PROJECT_DIR/public"
cp -r "$PROJECT_DIR/.python" "$STANDALONE_DIR/.python"
cp -r "$PROJECT_DIR/vendor-py" "$STANDALONE_DIR/vendor-py"

# App source required by the Flask app at runtime. platform_app imports the
# top-level service modules (ai_service.py, auth_service.py, ...), so every
# root-level *.py ships in the payload, not just app.py.
for item in platform_app templates static scripts; do
  [ -e "$PROJECT_DIR/$item" ] && cp -r "$PROJECT_DIR/$item" "$STANDALONE_DIR/$item"
done
find "$PROJECT_DIR" -maxdepth 1 -type f -name '*.py' -exec cp {} "$STANDALONE_DIR/" \;
# Writable runtime dirs (SQLite DB, generated reports, uploads). The platform's
# runtime COPY --chown=node:node makes them writable for the node user.
mkdir -p "$STANDALONE_DIR/runtime" "$STANDALONE_DIR/outputs" "$STANDALONE_DIR/uploads"

# Node entry point: the platform runtime launches `node server.js`.
cp "$PROJECT_DIR/scripts/standalone-server.js" "$STANDALONE_DIR/server.js"
cat > "$STANDALONE_DIR/package.json" <<'EOF'
{
  "name": "whu-quantum-runtime",
  "version": "1.0.0",
  "private": true,
  "description": "Self-contained runtime payload assembled by scripts/build.sh (Flask app + vendored CPython). Launched as `node server.js` by the platform Node-based runtime image.",
  "scripts": { "start": "node server.js" }
}
EOF

# Static assets keep .next/static and public non-empty for the COPY steps.
if [ -d "$PROJECT_DIR/static" ]; then
  cp -r "$PROJECT_DIR/static/." "$PROJECT_DIR/.next/static/"
  cp -r "$PROJECT_DIR/static/." "$PROJECT_DIR/public/"
fi
[ -f "$PROJECT_DIR/runtime/build_manifest.json" ] && cp "$PROJECT_DIR/runtime/build_manifest.json" "$STANDALONE_DIR/runtime/"

# Slim the payload and verify it end-to-end with the SAME env the runtime sets.
find "$STANDALONE_DIR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
find "$STANDALONE_DIR" -name '*.pyc' -delete 2>/dev/null

log "verifying payload interpreter + dependencies"
PYHOME_ENV=""
[ -f "$STANDALONE_DIR/.python/.needs-pythonhome" ] && PYHOME_ENV="$STANDALONE_DIR/.python"
env PYTHONHOME="$PYHOME_ENV" \
    PYTHONPATH="$STANDALONE_DIR/vendor-py" \
    LD_LIBRARY_PATH="$STANDALONE_DIR/.python/lib" \
  "$STANDALONE_DIR/.python/bin/python3" -c "import sys;import flask,gunicorn,sqlalchemy,psycopg,docx,openpyxl,xlrd,pypdf,reportlab,httpx,dotenv;print('[build] payload python',sys.version.split()[0],'deps ok')" \
  || fatal "payload python import probe failed"

if command -v node >/dev/null 2>&1; then
  node --check "$STANDALONE_DIR/server.js" || fatal "server.js failed node --check"
fi

log "runtime payload ready: .next/standalone ($(du -sh "$STANDALONE_DIR" 2>/dev/null | awk '{print $1}'))"
log "Build completed successfully"
exit 0
