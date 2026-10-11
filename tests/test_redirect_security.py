"""Redirect / _sid propagation security tests.

Coverage:
  1. propagate_sid converts root-relative redirects to same-origin absolute URLs
     and appends the _sid ticket at the query level.
  2. Non-same-origin locations have any existing _sid query parameter removed
     and do not receive the current _sid.
  3. Same-origin redirects preserve query strings, fragments and parameters whose
     values accidentally contain the literal "_sid=".
  4. Malformed / unsafe URLs (userinfo, control characters, backslash, unknown
     scheme, invalid port) are rejected: the redirect is cancelled (400) and the
     Location header is removed.
  5. Host / X-Forwarded-Host manipulation does not change the resolved origin.
  6. Without a trusted public base all redirects are cancelled (400).
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

    @app.get("/test-redirect-port-zero")
    def test_redirect_port_zero():
        return redirect("https://app.example.edu.cn:0/student/home?_sid=stolen")

    @app.get("/test-redirect-userinfo")
    def test_redirect_userinfo():
        return redirect("https://user:pass@app.example.edu.cn/student/home?_sid=stolen")

    @app.get("/test-redirect-backslash")
    def test_redirect_backslash():
        return redirect("https://evil.example.com/\\student/home?_sid=stolen")

    @app.get("/test-redirect-control-char")
    def test_redirect_control_char():
        return redirect("https://evil.example.com/student/home?\x00_sid=stolen")

    @app.get("/test-redirect-unknown-scheme")
    def test_redirect_unknown_scheme():
        return redirect("javascript:alert(1)?_sid=stolen")

    @app.get("/test-redirect-invalid-port")
    def test_redirect_invalid_port():
        return redirect("https://app.example.edu.cn:abc/student/home?_sid=stolen")

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


def test_propagate_sid_port_zero_treated_as_non_default(redirect_app):
    """Port 0 is explicit and must not match the protocol default port."""
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-port-zero")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "https://app.example.edu.cn:0/student/home"
    assert "_sid=" not in location


def test_propagate_sid_rejects_userinfo(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-userinfo")

    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_propagate_sid_rejects_backslash(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-backslash")

    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_propagate_sid_rejects_control_char(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-control-char")

    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_propagate_sid_rejects_unknown_scheme(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-unknown-scheme")

    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_propagate_sid_rejects_invalid_port(redirect_app):
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-invalid-port")

    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_propagate_sid_missing_public_base_fail_closed(redirect_app):
    """Without a trusted public base all redirects are cancelled."""
    redirect_app.config["APP_PUBLIC_BASE_URL"] = ""
    with redirect_app.test_client() as client:
        client.get("/health")
        resp = client.get("/test-redirect-root")

    assert resp.status_code == 400
    assert "Location" not in resp.headers
    assert "_sid=" not in resp.get_data(as_text=True)


def test_propagate_sid_no_session_still_strips_existing_sid(redirect_app):
    """Even without a current _sid, an existing _sid on an external URL is removed."""
    with redirect_app.test_client() as client:
        resp = client.get("/test-redirect-external-with-sid")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "https://evil.example.com/callback?foo=bar"
    assert "_sid=" not in location


def test_propagate_sid_no_session_safe_same_origin_no_sid(redirect_app, monkeypatch):
    """A safe same-origin redirect without a current _sid is allowed without a ticket."""
    monkeypatch.setattr("platform_app.current_sid", lambda: None)
    with redirect_app.test_client() as client:
        resp = client.get("/test-redirect-root")

    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location == "https://app.example.edu.cn/student/home"
    assert _extract_sid(location) is None


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
