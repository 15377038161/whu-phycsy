"""Backward-compatible credential and short-lived session helpers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash


TOKEN_TTL_SECONDS = 60 * 60 * 8


def password_hash(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def verify_password(account: dict[str, Any], candidate: str) -> tuple[bool, bool]:
    """Return (valid, should_upgrade_legacy_password)."""
    digest = account.get("password_hash")
    if digest:
        try:
            return check_password_hash(digest, candidate), False
        except ValueError:
            return False, False
    return secrets.compare_digest(str(account.get("password", "")), candidate), True


def new_session_token(role: str, student_id: str | None = None) -> tuple[str, dict[str, Any]]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_TTL_SECONDS)
    payload: dict[str, Any] = {"role": role, "expires_at": expires_at.isoformat()}
    if student_id:
        payload["student_id"] = student_id
    return token, payload


def session_is_active(payload: dict[str, Any] | None) -> bool:
    if not payload or not payload.get("expires_at"):
        return False
    try:
        return datetime.now(timezone.utc) < datetime.fromisoformat(payload["expires_at"])
    except (TypeError, ValueError):
        return False
