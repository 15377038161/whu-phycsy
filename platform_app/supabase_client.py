"""Minimal, read-only Supabase Data API / Auth helper for the current user's JWT.

This module only wraps the platform-injected Supabase environment variables
and builds the correct headers (`Authorization: Bearer <jwt>`, `apikey`,
`X-Instance-ID`). It does not hold service role, does not decode JWTs locally,
and does not expose tokens in URLs, logs or responses.

All functions accept a user JWT and make outbound HTTP calls on the server.
The caller is responsible for retrieving the JWT from a secure server-side
session and for deciding what to do with the result.
"""

from __future__ import annotations

import os

import httpx


def _supabase_env() -> tuple[str, str, str] | None:
    """Return (url, anon_key, tenant_id) from platform-injected env vars."""
    url = os.getenv("CODER_SUPABASE_URL", "").strip()
    anon_key = os.getenv("CODER_SUPABASE_ANON_KEY", "").strip()
    tenant_id = os.getenv("CODER_SUPABASE_TENANT_ID", "").strip()
    if not url or not anon_key or not tenant_id:
        return None
    return url.rstrip("/"), anon_key, tenant_id


def _env_ok() -> bool:
    """Return True if all required Supabase environment variables are present."""
    return _supabase_env() is not None


def _headers(jwt: str) -> dict[str, str]:
    env = _supabase_env()
    if env is None:
        raise RuntimeError("Supabase environment variables are incomplete")
    _url, anon_key, tenant_id = env
    return {
        "Authorization": f"Bearer {jwt}",
        "apikey": anon_key,
        "X-Instance-ID": tenant_id,
    }


def auth_get_user(jwt: str, *, timeout: float = 10.0) -> httpx.Response:
    """Call Supabase Auth /auth/v1/user with the user's JWT."""
    env = _supabase_env()
    if env is None:
        raise RuntimeError("Supabase environment variables are incomplete")
    url = env[0]
    return httpx.get(
        f"{url}/auth/v1/user",
        headers=_headers(jwt),
        timeout=timeout,
    )


def refresh_access_token(refresh_token: str, *, timeout: float = 10.0) -> httpx.Response:
    """Refresh a Supabase session using a refresh token.

    The response contains a new access_token and refresh_token. The caller must
    store the new tokens server-side and never return them to the client.
    """
    env = _supabase_env()
    if env is None:
        raise RuntimeError("Supabase environment variables are incomplete")
    url, anon_key, tenant_id = env
    return httpx.post(
        f"{url}/auth/v1/token?grant_type=refresh_token",
        json={"refresh_token": refresh_token},
        headers={
            "apikey": anon_key,
            "X-Instance-ID": tenant_id,
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )


def data_api_request(
    method: str,
    path: str,
    jwt: str,
    *,
    timeout: float = 10.0,
) -> httpx.Response:
    """Call Supabase Data API (PostgREST) with the user's JWT.

    `path` must start with `/` and is appended to `/rest/v1`. The caller must
    hard-code the path; this helper never builds URLs from user input.
    """
    env = _supabase_env()
    if env is None:
        raise RuntimeError("Supabase environment variables are incomplete")
    url = env[0]
    if not path.startswith("/"):
        path = f"/{path}"
    return httpx.request(
        method,
        f"{url}/rest/v1{path}",
        headers=_headers(jwt),
        timeout=timeout,
    )
