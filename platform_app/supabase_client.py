"""PostgREST data-access client for the platform built-in Supabase (PolarDB).

This is the future data layer replacing the direct-SQL SQLAlchemy engine
(platform_app/db.py). It talks to the built-in database over its REST/Data API.

Security contract (see supabase skill):
- Always send `X-Instance-ID: <tenant_id>` (tenant routing).
- Use the low-privilege anon key only; NEVER service role.
- Row-level security is enforced by the database (RLS) — anon key + per-user JWT.
- When a user is authenticated, pass their JWT as `Authorization: Bearer <token>`
  so PostgREST/Rls can scope to that user (auth.uid()).

Secrets are read from the process environment at call time (same as ai_service).
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class SupabaseAPIError(RuntimeError):
    """Raised when the Data API returns an error or non-2xx status."""


class SupabaseAPI:
    def __init__(self, access_token: str | None = None) -> None:
        self._base_url = (os.getenv("CODER_SUPABASE_URL") or "").rstrip("/")
        self._anon_key = os.getenv("CODER_SUPABASE_ANON_KEY") or ""
        self._tenant_id = os.getenv("CODER_SUPABASE_TENANT_ID") or ""
        # access_token carries the authenticated user's JWT for RLS scoping.
        self._access_token = access_token

    # -- headers -------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {
            "apikey": self._anon_key,
            "X-Instance-ID": self._tenant_id,
            "Accept": "application/json",
        }
        token = self._access_token or self._anon_key
        headers["Authorization"] = f"Bearer {token}"
        return headers

    # -- low-level request ---------------------------------------------------
    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None) -> Any:
        if not self._base_url or not self._anon_key or not self._tenant_id:
            raise SupabaseAPIError("CODER_SUPABASE_URL / ANON_KEY / TENANT_ID are not configured")
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self._base_url}{path}"
        resp = httpx.request(
            method,
            url,
            params=params,
            json=json,
            headers=self._headers(),
            timeout=httpx.Timeout(connect=15, read=60, write=30, pool=10),
        )
        if resp.status_code >= 400:
            detail = resp.text[:400]
            raise SupabaseAPIError(f"Data API {method} {path} -> {resp.status_code}: {detail}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # -- helpers (REST/PostgREST path, e.g. /rest/v1/<table>) ----------------
    def select(self, table: str, *, select: str = "*", filters: dict[str, Any] | None = None, order: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": select}
        if filters:
            for key, value in filters.items():
                params[key] = f"eq.{value}"
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        data = self._request("GET", f"/rest/v1/{table}", params=params)
        return data if isinstance(data, list) else (data or [])

    def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]], *, returning: str | None = "id") -> list[dict[str, Any]]:
        params = {"select": returning} if returning else None
        data = self._request("POST", f"/rest/v1/{table}", params=params, json=rows)
        return data if isinstance(data, list) else (data or [])

    def update(self, table: str, values: dict[str, Any], *, filters: dict[str, Any], returning: str | None = "id") -> list[dict[str, Any]]:
        if not filters:
            raise SupabaseAPIError("update() requires at least one filter to avoid updating the whole table")
        params: dict[str, Any] = {"select": returning} if returning else None
        for key, value in filters.items():
            params[key] = f"eq.{value}"
        data = self._request("PATCH", f"/rest/v1/{table}", params=params, json=values)
        return data if isinstance(data, list) else (data or [])

    def delete(self, table: str, *, filters: dict[str, Any]) -> None:
        if not filters:
            raise SupabaseAPIError("delete() requires at least one filter to avoid clearing the table")
        params: dict[str, Any] = {}
        for key, value in filters.items():
            params[key] = f"eq.{value}"
        self._request("DELETE", f"/rest/v1/{table}", params=params)


# module-level helper mirroring createSupabaseServer() / getSupabase() naming
def get_supabase(access_token: str | None = None) -> SupabaseAPI:
    """Return a Data API client. Pass the authenticated user's JWT when available."""
    return SupabaseAPI(access_token=access_token)