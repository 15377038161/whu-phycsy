"""Runtime self-attestation for deployment verification.

This module records SHA-256 hashes of the actually loaded source files at
import time (i.e. when the application process starts) and compares them
against the build manifest generated during packaging.

The hashes are a snapshot of the files that the interpreter loaded from disk
at startup; they do not prove the integrity of compiled bytecode, in-memory
patches, or runtime monkey-patches performed after import.

It exposes only a strict allow-list of non-sensitive runtime facts and never
emits secrets, paths, hostnames, URLs, JWT claims, user lists, raw errors, or
business identifiers.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import supabase_client


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# The manifest path can be overridden by tests via the RUNTIME_MANIFEST_PATH
# environment variable. Production deployments always use the default.
_MANIFEST_PATH = Path(
    os.getenv("RUNTIME_MANIFEST_PATH", _PROJECT_ROOT / "runtime" / "build_manifest.json")
)

# Code files whose loaded hashes are compared with the build manifest.
# Paths are relative to the project root; they are used only for hashing and
# are not exposed in diagnostic responses. Keys are logical labels.
_WATCHED_FILES = [
    "ai_service.py",
    "platform_app/services/progress.py",
    "platform_app/blueprints/student.py",
    "platform_app/blueprints/api.py",
    "scripts/start.sh",
]

_WATCHED_LABELS: dict[str, str] = {
    "ai_service.py": "ai",
    "platform_app/services/progress.py": "progress",
    "platform_app/blueprints/student.py": "student",
    "platform_app/blueprints/api.py": "api",
    "scripts/start.sh": "start",
}

# Git HEAD is a 40-char hex SHA-1; file hashes are 64-char hex SHA-256.
_HEAD_PATTERN = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$", re.IGNORECASE)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest() -> dict[str, Any]:
    try:
        with _MANIFEST_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _loaded_hashes() -> dict[str, str]:
    return {rel: _file_hash(_PROJECT_ROOT / rel) for rel in _WATCHED_FILES}


def _normalize_head(value: Any) -> str:
    if isinstance(value, str) and _HEAD_PATTERN.match(value):
        return value.lower()
    return "unknown"


def _verify_manifest(manifest: dict[str, Any], loaded: dict[str, str]) -> dict[str, Any]:
    manifest_files = manifest.get("files") or {}
    loaded_sha256: dict[str, str] = {}
    manifest_sha256: dict[str, str | None] = {}
    module_hashes_match: dict[str, bool] = {}
    for rel in _WATCHED_FILES:
        label = _WATCHED_LABELS[rel]
        loaded_sha = loaded.get(rel)
        manifest_sha = manifest_files.get(rel)
        loaded_sha256[label] = loaded_sha or ""
        manifest_sha256[label] = manifest_sha if isinstance(manifest_sha, str) else None
        module_hashes_match[label] = bool(loaded_sha) and loaded_sha == manifest_sha
    return {
        "manifest_head": _normalize_head(manifest.get("head")),
        "manifest_match": manifest_files == loaded,
        "loaded_sha256": loaded_sha256,
        "manifest_sha256": manifest_sha256,
        "module_hashes_match": module_hashes_match,
    }


# Computed once at process startup, when this module is first imported.
_MANIFEST = _load_manifest()
_LOADED_HASHES = _loaded_hashes()
_MANIFEST_VERIFY = _verify_manifest(_MANIFEST, _LOADED_HASHES)


def _backend_type() -> str:
    """Determine the actual business backend selection path from loaded code.

    Returns 'sqlite_local' when progress.py only exposes the legacy local
    selection_summary. Returns 'postgrest_remote' when the Data API/RPC path
    (student_selection_summary / save_student_level_selection) is present.
    This is a code-level observation, not a URL guess.
    """
    try:
        progress = importlib.import_module("platform_app.services.progress")
        if hasattr(progress, "student_selection_summary"):
            return "postgrest_remote"
    except Exception:
        pass
    return "sqlite_local"


def _app_env() -> str:
    """Return a fixed enum for the runtime environment; never a free-form string."""
    from flask import current_app

    value = str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV", "unknown")).lower()
    if value in {"production", "prod"}:
        return "production"
    if value in {"preview", "staging"}:
        return "preview"
    if value in {"development", "dev"}:
        return "development"
    return "unknown"


def _ai_config_state() -> dict[str, Any]:
    """Return only presence/source enums for AI configuration; no values."""
    native_base = bool(os.getenv("CODER_CODING_MODEL_BASE_URL", "").strip())
    native_key = bool(os.getenv("CODER_CODING_MODEL_API_KEY", "").strip())
    legacy_complete = all(
        os.getenv(key, "").strip()
        for key in ("AI_BASE_URL", "AI_API_KEY", "AI_TEXT_MODEL", "AI_VISION_MODEL")
    )
    native_present = native_base and native_key

    if native_present:
        source = "native"
    elif legacy_complete:
        source = "legacy"
    else:
        source = "unconfigured"

    return {
        "ai_native_vars_present": native_present,
        "ai_source": source,
    }


def _enrollment_visibility_state(
    token: str | None, auth_uid: str | None
) -> dict[str, Any]:
    """Query enrollment visibility using the user's own JWT and verified UUID.

    1. Resolve the business user id from `users.auth_user_id = <auth_uid>`.
    2. Query `enrollments` filtered by `student_id = <business_user_id>`.
    3. Confirm every returned row's `student_id` equals the caller's id.

    Only fixed enum status and a boolean visibility flag are returned; no
    course_ids, student_ids, auth_uids, row counts, JWT claims, or raw bodies.
    """
    if not supabase_client._env_ok():
        return {"enrollment_status": "missing_env", "has_visible_enrollment": False}

    if not token or not auth_uid:
        return {"enrollment_status": "no_token", "has_visible_enrollment": False}

    # Step 1: resolve business user id from the users table mapping.
    users_path = (
        f"/users?select=id,auth_user_id&auth_user_id=eq.{quote(auth_uid, safe='')}&limit=1"
    )
    try:
        users_resp = supabase_client.data_api_request(
            "GET", users_path, token, timeout=10.0
        )
    except Exception:
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    if users_resp.status_code in (401, 403):
        return {"enrollment_status": "forbidden", "has_visible_enrollment": False}
    if users_resp.status_code != 200:
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    try:
        users_rows = users_resp.json() or []
    except Exception:
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    if not isinstance(users_rows, list):
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    student_id: str | None = None
    for row in users_rows:
        if isinstance(row, dict) and str(row.get("auth_user_id") or "") == auth_uid:
            student_id = str(row.get("id") or "") or None
            break

    if not student_id:
        return {"enrollment_status": "mapping_missing", "has_visible_enrollment": False}

    # Step 2: query enrollments strictly for the caller's own student_id.
    enrollments_path = (
        f"/enrollments?select=student_id&student_id=eq.{quote(student_id, safe='')}&limit=1"
    )
    try:
        resp = supabase_client.data_api_request(
            "GET", enrollments_path, token, timeout=10.0
        )
    except Exception:
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    if resp.status_code in (401, 403):
        return {"enrollment_status": "forbidden", "has_visible_enrollment": False}
    if resp.status_code != 200:
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    try:
        rows = resp.json() or []
    except Exception:
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    if not isinstance(rows, list):
        return {"enrollment_status": "unreachable", "has_visible_enrollment": False}

    visible = False
    for row in rows:
        if isinstance(row, dict) and str(row.get("student_id") or "") == student_id:
            visible = True
        else:
            # Data returned for a different student_id would indicate a policy bypass.
            return {"enrollment_status": "forbidden", "has_visible_enrollment": False}

    return {
        "enrollment_status": "visible" if visible else "empty",
        "has_visible_enrollment": visible,
    }


def runtime_diagnostic_payload(
    token: str | None = None,
    auth_uid: str | None = None,
) -> dict[str, Any]:
    """Return the strict allow-list of runtime self-attestation facts."""
    payload: dict[str, Any] = {
        "app_env": _app_env(),
        "backend_type": _backend_type(),
    }
    payload.update(_ai_config_state())
    payload.update(_enrollment_visibility_state(token, auth_uid))
    payload.update(_MANIFEST_VERIFY)
    return payload
