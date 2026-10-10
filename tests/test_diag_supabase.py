"""Supabase Auth/Data API 服务端诊断端点安全测试。

覆盖：
  1. 诊断端点仅对已登录用户可用，且受 CSRF 保护
  2. 不返回 access_token / refresh_token / 完整 JWT
  3. 服务端使用会话中的用户 JWT 调用 Supabase Auth / Data API
  4. token 过期时能在服务端静默刷新并更新会话
  5. 缺失环境变量、缺失 token、Data API 403 等异常状态正确上报
"""

from __future__ import annotations

import pytest

from platform_app.models import User


class _FakeResponse:
    def __init__(self, status_code: int, json_data):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


@pytest.fixture
def diag_app(tmp_path, monkeypatch):
    from platform_app import create_app

    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.edu.cn")
    monkeypatch.delenv("CODER_PROJECTS_DOMAIN", raising=False)
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "diag-test-secret",
        "DATA_DIR": str(tmp_path / "data"),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'diag.db'}",
    })


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")


@pytest.fixture
def sample_user(diag_app):
    from platform_app.db import transaction

    with diag_app.app_context():
        with transaction() as db:
            user = User(
                id="cx_123456789",
                username="cx_123456789",
                name="测试用户",
                role="student",
                password_hash="!chaoxing-oauth-no-password!",
                active=True,
                chaoxing_cxid="123456789",
            )
            db.add(user)
    return user


def _login_client(client, user_id: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _verified_user(cxid: str = "123456789") -> dict:
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        "aud": "authenticated",
        "role": "authenticated",
        "user_metadata": {"cxid": cxid},
    }


def test_diag_auth_rejects_anonymous(diag_app):
    with diag_app.test_client() as client:
        resp = client.post("/api/diag/auth")
    assert resp.status_code == 401
    assert resp.json["diag_status"] == "unauthenticated"


def test_diag_auth_requires_csrf(diag_app, sample_user, supabase_env, raw_client_open):
    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        resp = raw_client_open(
            client,
            "/api/diag/auth",
            method="POST",
            headers={"X-CSRFToken": "wrong-token"},
        )
    assert resp.status_code == 400


def test_diag_auth_missing_env(diag_app, sample_user, monkeypatch):
    monkeypatch.delenv("CODER_SUPABASE_URL", raising=False)
    monkeypatch.delenv("CODER_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("CODER_SUPABASE_TENANT_ID", raising=False)
    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/auth")
    assert resp.status_code == 200
    data = resp.json
    assert data["env_ok"] is False
    assert data["auth_status"] == "missing_env"
    assert data["local_user_id"] == sample_user.id


def test_diag_auth_no_token(diag_app, sample_user, supabase_env):
    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        resp = client.post("/api/diag/auth")
    assert resp.status_code == 200
    data = resp.json
    assert data["env_ok"] is True
    assert data["auth_status"] == "no_token"


def test_diag_auth_ok_and_masks_sensitive_data(diag_app, sample_user, supabase_env, monkeypatch):
    calls = []

    def fake_get(url, *, headers, timeout):
        calls.append((url, headers))
        return _FakeResponse(200, _verified_user())

    monkeypatch.setattr("platform_app.supabase_client.httpx.get", fake_get)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
            sess["cx_refresh_token"] = "test-refresh-token"
        resp = client.post("/api/diag/auth")

    assert resp.status_code == 200
    data = resp.json
    assert data["env_ok"] is True
    assert data["auth_status"] == "ok"
    assert data["mapping_match"] is True
    assert data["local_user_id"] == sample_user.id
    assert data["local_role"] == "student"
    assert data["supabase_uid_mask"] == "0000***0000"
    assert data["local_cxid_mask"] == "1234***6789"
    text = resp.get_data(as_text=True)
    assert "test-access-token" not in text
    assert "test-refresh-token" not in text
    assert "00000000-0000-0000-0000-000000000000" not in text


def test_diag_auth_refreshes_expired_token(diag_app, sample_user, supabase_env, monkeypatch):
    get_calls = []

    def fake_get(url, *, headers, timeout):
        get_calls.append((url, headers))
        if len(get_calls) == 1:
            return _FakeResponse(401, {"error": "invalid token"})
        return _FakeResponse(200, _verified_user())

    def fake_post(url, *, json, headers, timeout):
        return _FakeResponse(200, {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "token_type": "bearer",
            "expires_in": 3600,
            "user": _verified_user(),
        })

    monkeypatch.setattr("platform_app.supabase_client.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.post", fake_post)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "old-access-token"
            sess["cx_refresh_token"] = "old-refresh-token"
        resp = client.post("/api/diag/auth")

    assert resp.status_code == 200
    data = resp.json
    assert data["auth_status"] == "ok"
    text = resp.get_data(as_text=True)
    assert "old-access-token" not in text
    assert "new-access-token" not in text
    assert "old-refresh-token" not in text
    assert "new-refresh-token" not in text

    # 服务端会话应已更新为新令牌
    with diag_app.app_context():
        from platform_app.db import db_session
        from platform_app.models import AppSession

        rows = db_session().query(AppSession).all()
        session_row = next((r for r in rows if r.data.get("user_id") == sample_user.id), None)
        assert session_row is not None
        assert session_row.data.get("cx_access_token") == "new-access-token"
        assert session_row.data.get("cx_refresh_token") == "new-refresh-token"


def test_diag_data_ok_and_masks_row(diag_app, sample_user, supabase_env, monkeypatch):
    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, _verified_user())

    def fake_request(method, url, *, headers, timeout):
        return _FakeResponse(200, [{
            "id": sample_user.id,
            "role": "student",
            "auth_user_id": "00000000-0000-0000-0000-000000000000",
        }])

    monkeypatch.setattr("platform_app.supabase_client.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.request", fake_request)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/data")

    assert resp.status_code == 200
    data = resp.json
    assert data["env_ok"] is True
    assert data["data_status"] == "ok"
    assert data["row_count"] == 1
    assert data["row"]["auth_user_id_mask"] == "0000***0000"
    text = resp.get_data(as_text=True)
    assert "test-access-token" not in text
    assert "00000000-0000-0000-0000-000000000000" not in text


def test_diag_data_forbidden(diag_app, sample_user, supabase_env, monkeypatch):
    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, _verified_user())

    def fake_request(method, url, *, headers, timeout):
        return _FakeResponse(403, {"message": "Access denied by RLS"})

    monkeypatch.setattr("platform_app.supabase_client.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.request", fake_request)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/data")

    assert resp.status_code == 200
    assert resp.json["data_status"] == "forbidden"


def test_diag_data_no_cxid(diag_app, supabase_env):
    from platform_app.db import transaction

    with diag_app.app_context():
        with transaction() as db:
            user = User(
                id="local_user_001",
                username="local_user_001",
                name="本地用户",
                role="teacher",
                password_hash="hashed",
                active=True,
                chaoxing_cxid=None,
            )
            db.add(user)

    with diag_app.test_client() as client:
        _login_client(client, "local_user_001")
        resp = client.post("/api/diag/data")

    assert resp.status_code == 200
    assert resp.json["data_status"] == "no_cxid"
