"""Redirect / _sid propagation security tests.

Coverage:
  1. propagate_sid converts root-relative redirects to same-origin absolute URLs
     and appends the _sid ticket.
  2. External absolute / protocol-relative redirects do not receive _sid.
  3. Same-origin absolute redirects keep _sid.
  4. Missing public base configuration causes fail-closed (no _sid).
  5. The boundary is not bypassed by a hostile Host / X-Forwarded-Host header.
"""
from __future__ import annotations

import pytest
from flask import redirect

from platform_app import create_app


@pytest.fixture
def redirect_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.edu.cn")
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.delenv("CODER_PROJECTS_DOMAIN", raising=False)
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "redirect-test-secret",
            "DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'redirect.db'}",
        }
    )

    @app.get("/test-redirect-root")
    def test_redirect_root():
        return redirect("/student/home")

    @app.get("/test-redirect-query")
    def test_redirect_query():
        return redirect("/student/home?foo=bar")

    @app.get("/test-redirect-absolute")
    def test_redirect_absolute():
        return redirect("https://app.example.edu.cn/student/home")

    @app.get("/test-redirect-external")
    def test_redirect_external():
        return redirect("https://evil.example.com/callback")

    @app.get("/test-redirect-protocol-relative")
    def test_redirect_protocol_relative():
        return redirect("//evil.example.com/callback")

    return app


def _extract_sid(location: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(location).query)
    values = qs.get("_sid")
    return values[0] if values else None


def test_propagate_sid_converts_root_relative_to_absolute(redirect_app):
    with redirect_app.test_client() as client:
        # Establish a session so the client has a stable sid.
        client.get("/health")
        resp = client.get("/test-redirect-root")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://app.example.edu.cn/student/home")
    assert "_sid=" in location
    sid = _extract_sid(location)
    assert sid and len(sid) > 0


def test_propagate_sid_preserves_query_string(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-query")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://app.example.edu.cn/student/home")
    assert "foo=bar" in location
    assert "_sid=" in location
    assert "&" in location or "?_sid=" not in location  # _sid appended after existing query


def test_propagate_sid_allows_same_origin_absolute(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-absolute")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://app.example.edu.cn/student/home")
    assert "_sid=" in location


def test_propagate_sid_rejects_external_absolute(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-external")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "https://evil.example.com/callback"
    assert "_sid=" not in location


def test_propagate_sid_rejects_protocol_relative(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-protocol-relative")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "//evil.example.com/callback"
    assert "_sid=" not in location


def test_propagate_sid_missing_public_base_fail_closed(tmp_path, monkeypatch):
    """Without a trusted public base the ticket must not be appended (fail closed)."""
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "")
    monkeypatch.setenv("CODER_PROJECTS_DOMAIN", "")
    monkeypatch.setenv("APP_ENV", "preview")
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "redirect-fail-closed-secret",
            "DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'redirect.db'}",
        }
    )
    # Explicitly clear the cached public base to exercise runtime fail-closed path.
    app.config["APP_PUBLIC_BASE_URL"] = ""

    @app.get("/test-redirect")
    def test_redirect():
        return redirect("/student/home")

    with app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "/student/home"
    assert "_sid=" not in location


def test_propagate_sid_ignores_hostile_x_forwarded_host(redirect_app):
    """A hostile Host / X-Forwarded-Host must not influence the resolved origin."""
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get(
            "/test-redirect-root",
            headers={
                "Host": "evil.example.com",
                "X-Forwarded-Host": "evil.example.com",
                "X-Forwarded-Proto": "https",
            },
        )

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://app.example.edu.cn/student/home")
    assert "evil.example.com" not in location
    assert "_sid=" in location
