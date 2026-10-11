#!/usr/bin/env python3
"""Generate a runtime build manifest with code-file hashes and source HEAD.

The manifest contains no environment variables, secrets, or runtime data; only
SHA-256 hashes of selected source files and the git HEAD at build time. It is
written to runtime/build_manifest.json and used by platform_app.diag_runtime to
verify that the running process loaded the same code that was packaged.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
MANIFEST_PATH = RUNTIME_DIR / "build_manifest.json"

# Code files whose integrity is attested at runtime. Keep in sync with
# platform_app.diag_runtime._WATCHED_FILES.
WATCHED_FILES = [
    "ai_service.py",
    "platform_app/services/progress.py",
    "platform_app/blueprints/student.py",
    "platform_app/blueprints/api.py",
    "scripts/start.sh",
]


def _file_hash(rel_path: str) -> str:
    full = PROJECT_ROOT / rel_path
    return hashlib.sha256(full.read_bytes()).hexdigest()


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "head": _git_head(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": {rel: _file_hash(rel) for rel in WATCHED_FILES},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[build-manifest] wrote {MANIFEST_PATH} with head {manifest['head']}")


if __name__ == "__main__":
    main()
