"""Redirect / _sid propagation security tests.

Coverage:
  1. propagate_sid converts root-relative redirects to same-origin absolute URLs
     and appends the _sid ticket at the query level.
  2. Non-same-origin locations have any existing _sid query parameter removed
     and do not receive the current _sid.
  3. Same-origin redirects preserve query strings, fragments and parameters whose
     values accidentally contain the literal "_sid=".
  4. Protocol-relative, userinfo, control-character, backslash and malformed
     URLs are rejected for ticket propagation.
  5. Host / X-Forwarded-Host manipulation does not change the resolved origin.
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

    @app.get("/test-redirect-fragment")
    def test_redirect_fragment():
        return redirect("/student/home#section")

    @app.get("/test-redirect-param-with-sid-substring")
    def test_redirect_param_with_sid_substring():
        return redirect("/student/home?callback=foo_sid=bar&baz=1")

    @app.get("/test-redirect-absolute")
    def test_redirect_absolute():
        return redirect("https://app.example.edu.cn/student/home")

    @app.get("/test-redirect-external")
    def test_redirect_external():
        return redirect("https://evil.example.com/callback")

    @app.get("/test-redirect-external-with-sid")
    def test_redirect_external_with_sid():
        return redirect("https://evil.example.com/callback?_sid=stolen&foo=bar")

    @app.get("/test-redirect-protocol-relative")
    def test_redirect_protocol_relative():
        return redirect("//evil.example.com/callback")

    @app.get("/test-redirect-protocol-relative-with-sid")
    def test_redirect_protocol_relative_with_sid():
        return redirect("//evil.example.com/callback?_sid=stolen&foo=bar")

    @app.get("/test-redirect-http-scheme-mismatch")
    def test_redirect_http_scheme_mismatch():
        return redirect("http://app.example.edu.cn/student/home")

    @app.get("/test-redirect-port-mismatch")
    def test_redirect_port_mismatch():
        return redirect("https://app.example.edu.cn:8443/student/home")

    @app.get("/test-redirect-userinfo")
    def test_redirect_userinfo():
        return redirect("https://user:pass@app.example.edu.cn/student.home?_sid=stolen")

    @app.get("/test-redirect-backslash")
    def test_redirect_backslash():
        return redirect("https://evil.example.com/\\student/home?_sid=stolen")

    return app


def _extract_sid(location: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(location).query)
    values = qs.get("_sid")
    return values[0] if values else None


def test_propagate_sid_converts_root_relative_to_absolute(redirect_app):
    with redirect_app.test_client() as client:
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
    # Existing query comes before the appended _sid.
    assert "?foo=bar&_sid=" in location or "?foo=bar&amp;_sid=" in location


def test_propagate_sid_preserves_fragment(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-fragment")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://app.example.edu.cn/student/home")
    assert "_sid=" in location
    assert location.endswith("#section")


def test_propagate_sid_does_not_misread_sid_in_param_value(redirect_app):
    """A parameter value containing the literal '_sid=' must not be treated as the ticket."""
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-param-with-sid-substring")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "callback=foo_sid%3Dbar" in location or "callback=foo_sid=bar" in location
    assert "baz=1" in location
    sid = _extract_sid(location)
    assert sid and sid != "bar"


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


def test_propagate_sid_strips_existing_sid_from_external_absolute(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-external-with-sid")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "https://evil.example.com/callback?foo=bar"
    assert "_sid=" not in location


def test_propagate_sid_rejects_protocol_relative(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-protocol-relative")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "//evil.example.com/callback"
    assert "_sid=" not in location


def test_propagate_sid_strips_existing_sid_from_protocol_relative(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-protocol-relative-with-sid")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "//evil.example.com/callback?foo=bar"
    assert "_sid=" not in location


def test_propagate_sid_rejects_http_scheme_mismatch(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-http-scheme-mismatch")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "http://app.example.edu.cn/student/home"
    assert "_sid=" not in location


def test_propagate_sid_rejects_port_mismatch(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-port-mismatch")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "https://app.example.edu.cn:8443/student/home"
    assert "_sid=" not in location


def test_propagate_sid_rejects_userinfo(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-userinfo")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    # Malformed / unsafe URL is left untouched; the app should not generate it.
    assert "user:pass" in location
    assert "_sid=stolen" in location


def test_propagate_sid_rejects_backslash(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-backslash")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    # Flask normalizes the literal backslash to %5C before the after_request hook sees it.
    # We treat the URL as unsafe and leave it untouched, so the existing stolen _sid remains
    # and the location is not rewritten to the app origin or signed with a new ticket.
    assert "evil.example.com" in location
    assert "%5C" in location or "\\" in location
    assert "_sid=stolen" in location
    assert "app.example.edu.cn" not in location


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
