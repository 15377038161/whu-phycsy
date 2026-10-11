"""Runtime self-attestation for deployment verification.

This module records SHA-256 hashes of the actually loaded code files at import
time and compares them against the build manifest generated during packaging.
It exposes only a strict allow-list of non-sensitive runtime facts and never
emits secrets, paths, hostnames, URLs, JWT claims, user lists, or raw errors.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

import httpx

from . import supabase_client


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# The manifest path can be overridden by tests via the RUNTIME_MANIFEST_PATH
# environment variable. Production deployments always use the default.
_MANIFEST_PATH = Path(os.getenv("RUNTIME_MANIFEST_PATH", _PROJECT_ROOT / "runtime" / "build_manifest.json"))

# Code files whose loaded hashes are compared with the build manifest.
# Paths are relative to the project root; they are used only for hashing and
# are not exposed in diagnostic responses.
_WATCHED_FILES = [
    "ai_service.py",
    "platform_app/services/progress.py",
    "platform_app/blueprints/student.py",
    "platform_app/blueprints/api.py",
    "scripts/start.sh",
]


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


def _verify_manifest(manifest: dict[str, Any], loaded: dict[str, str]) -> dict[str, Any]:
    manifest_files = manifest.get("files") or {}
    return {
        "manifest_head": str(manifest.get("head") or "unknown"),
        "manifest_match": manifest_files == loaded,
        "module_hashes_match": {
            rel: manifest_files.get(rel) == loaded.get(rel) for rel in _WATCHED_FILES
        },
    }


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


def _current_access_token() -> str | None:
    """Read the current server-side session token without validating or exposing it."""
    from flask import session

    return session.get("cx_access_token")


def _enrollment_visibility_state(token: str | None) -> dict[str, Any]:
    """Query the remote enrollments endpoint using the user's own JWT.

    Only fixed enum status and a boolean visibility flag are returned; no
    course_ids, student_ids, row counts, JWT claims, or raw response bodies.
    """
    if not supabase_client._env_ok():
        return {"enrollment_status": "missing_env", "has_visible_enrollment": False}

    if not token:
        return {"enrollment_status": "no_token", "has_visible_enrollment": False}

    try:
        resp = supabase_client.data_api_request(
            "GET",
            "/enrollments?select=course_id&limit=1",
            token,
            timeout=10.0,
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

    visible = bool(rows)
    return {
        "enrollment_status": "visible" if visible else "empty",
        "has_visible_enrollment": visible,
    }


def runtime_diagnostic_payload() -> dict[str, Any]:
    """Return the strict allow-list of runtime self-attestation facts."""
    from flask import current_app

    token = _current_access_token()
    payload: dict[str, Any] = {
        "app_env": str(current_app.config.get("APP_ENV") or os.getenv("APP_ENV", "unknown")),
        "backend_type": _backend_type(),
    }
    payload.update(_ai_config_state())
    payload.update(_enrollment_visibility_state(token))
    payload.update(_MANIFEST_VERIFY)
    return payload


def validate_csrf_token(request) -> bool:
    """Verify the request carries the session-bound CSRF token."""
    from flask import session

    expected = session.get("_csrf_token")
    if not expected:
        return False
    supplied = (
        request.headers.get("X-CSRFToken")
        or request.form.get("csrf_token")
        or request.get_json(silent=True) or {}
    )
    if isinstance(supplied, dict):
        supplied = supplied.get("csrf_token")
    if not supplied or not isinstance(supplied, str):
        return False
    return secrets.compare_digest(expected, supplied)
