"""超星 OAuth 用户令牌服务端安全存储与校验测试。

覆盖：
  1. _verify_access_token 通过 Supabase Auth /auth/v1/user 校验
  2. _refresh_access_token 刷新令牌
  3. chaoxing_callback 仅在校验成功后建立会话
  4. access_token / refresh_token 只存服务端 app_sessions，不回传客户端/日志
  5. 注销清除令牌
"""

from __future__ import annotations

import pytest

from platform_app.models import AppSession


@pytest.fixture
def app_for_token(tmp_path):
    from platform_app import create_app

    return create_app({
        "TESTING": True,
        "SECRET_KEY": "token-test-secret",
        "DATA_DIR": str(tmp_path / "data"),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'token.db'}",
    })


@pytest.fixture
def supabase_env(monkeypatch):
    """提供一组伪造但完整的 Supabase 环境变量用于测试。"""
    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")


@pytest.fixture(autouse=True)
def public_base_env(monkeypatch):
    """测试用公开域名，避免沙箱环境变量触发 fail closed。"""
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.edu.cn")
    monkeypatch.delenv("CODER_PROJECTS_DOMAIN", raising=False)


def _make_verified_user(cxid: str = "123456789", realname: str = "测试用户"):
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        "aud": "authenticated",
        "role": "authenticated",
        "user_metadata": {"cxid": cxid, "realname": realname},
    }


def _make_exchange_response(access_token: str = "fake-access", refresh_token: str = "fake-refresh"):
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "expires_at": 1234567890,
        "user": _make_verified_user(),
    }


class _FakeResponse:
    def __init__(self, status_code: int, json_data):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


def test_verify_access_token_success(app_for_token, supabase_env, monkeypatch):
    from platform_app.blueprints.auth import _verify_access_token

    user = _make_verified_user()
    calls = []

    def fake_get(url, *, headers, timeout):
        calls.append((url, headers))
        return _FakeResponse(200, user)

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.test_request_context("/"):
        result, error = _verify_access_token("test-access-token")

    assert error is None
    assert result == user
    assert calls[0][0] == "https://fake.supabase.co/auth/v1/user"
    assert calls[0][1]["Authorization"] == "Bearer test-access-token"
    assert calls[0][1]["apikey"] == "fake-anon-key"
    assert calls[0][1]["X-Instance-ID"] == "fake-tenant-id"


def test_verify_access_token_missing_env(app_for_token, monkeypatch):
    from platform_app.blueprints.auth import _verify_access_token

    monkeypatch.delenv("CODER_SUPABASE_URL", raising=False)
    monkeypatch.delenv("CODER_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("CODER_SUPABASE_TENANT_ID", raising=False)

    with app_for_token.test_request_context("/"):
        result, error = _verify_access_token("test-access-token")

    assert result is None
    assert "环境变量不完整" in error


def test_verify_access_token_invalid(app_for_token, supabase_env, monkeypatch):
    from platform_app.blueprints.auth import _verify_access_token

    monkeypatch.setattr(
        "platform_app.blueprints.auth.httpx.get",
        lambda *args, **kwargs: _FakeResponse(401, {"error": "invalid token"}),
    )

    with app_for_token.test_request_context("/"):
        result, error = _verify_access_token("bad-token")

    assert result is None
    assert "校验失败 (401)" in error


def test_refresh_access_token_success(app_for_token, supabase_env, monkeypatch):
    from platform_app.blueprints.auth import _refresh_access_token

    new_session = _make_exchange_response("new-access", "new-refresh")
    calls = []

    def fake_post(url, *, json, headers, timeout):
        calls.append((url, json, headers))
        return _FakeResponse(200, new_session)

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)

    with app_for_token.test_request_context("/"):
        result, error = _refresh_access_token("old-refresh")

    assert error is None
    assert result == new_session
    assert calls[0][0] == "https://fake.supabase.co/auth/v1/token?grant_type=refresh_token"
    assert calls[0][1]["refresh_token"] == "old-refresh"
    assert calls[0][2]["X-Instance-ID"] == "fake-tenant-id"


def test_callback_stores_tokens_server_side_only(app_for_token, supabase_env, monkeypatch):
    """完整登录回跳：令牌应写入 app_sessions，响应体/Location 中不可见。"""
    from platform_app.db import db_session

    exchange_resp = _make_exchange_response("tok-access-abc", "tok-refresh-xyz")
    user = _make_verified_user()

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(200, user)
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    # 必须为同源绝对 URL（避免网关把根相对 Location 重写为沙箱前缀）
    assert location.startswith("https://app.example.edu.cn/")
    assert "/student/home" in location or "/teacher/dashboard" in location
    assert "_sid=" in location
    assert "tok-access-abc" not in location
    assert "tok-refresh-xyz" not in location
    assert b"tok-access-abc" not in resp.data
    assert b"tok-refresh-xyz" not in resp.data

    # 验证服务端 app_sessions 中保存了令牌
    sid = resp.headers.get("Set-Cookie", "")
    if "whu_sid=" in sid:
        sid_value = sid.split("whu_sid=")[1].split(";")[0]
    else:
        # URL 票据场景：从 Location 中解析 _sid
        sid_value = location.split("_sid=")[-1].split("&")[0] if "_sid=" in location else None

    with app_for_token.app_context():
        row = db_session().get(AppSession, sid_value) if sid_value else None
        assert row is not None, "回调后应创建服务端会话记录"
        assert row.data.get("cx_access_token") == "tok-access-abc"
        assert row.data.get("cx_refresh_token") == "tok-refresh-xyz"
        assert row.data.get("user_id") is not None


def test_callback_rejects_unverified_token(app_for_token, supabase_env, monkeypatch):
    """access_token 校验失败时不应建立会话。"""
    from platform_app.db import db_session

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, _make_exchange_response())
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(401, {"error": "invalid token"})
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert location.startswith("https://app.example.edu.cn/")
    assert "/login" in location

    with app_for_token.app_context():
        count = db_session().query(AppSession).count()
        # 回调会生成一个空票据用于承载 flash/csrf，但不应包含 user_id
        rows = db_session().query(AppSession).all()
        assert not any(r.data.get("user_id") for r in rows)


def test_logout_clears_tokens(app_for_token, supabase_env, monkeypatch):
    """注销后服务端会话中的 user_id 和令牌应被清除。"""
    from platform_app.db import db_session

    exchange_resp = _make_exchange_response("access-before", "refresh-before")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(200, _make_verified_user())
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.test_client() as client:
        # 先登录
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)
        sid_value = None
        if "whu_sid=" in (resp.headers.get("Set-Cookie") or ""):
            sid_value = resp.headers["Set-Cookie"].split("whu_sid=")[1].split(";")[0]
        elif "_sid=" in (resp.headers.get("Location") or ""):
            sid_value = resp.headers["Location"].split("_sid=")[-1].split("&")[0]

        assert sid_value

        # 携带 cookie 注销（POST 需要 csrf_token）
        # 从会话中读取 csrf_token
        with app_for_token.app_context():
            row = db_session().get(AppSession, sid_value)
            csrf = row.data.get("_csrf_token") if row else None

        resp2 = client.post("/logout", data={"csrf_token": csrf})
        assert resp2.status_code == 302

        with app_for_token.app_context():
            row = db_session().get(AppSession, sid_value)
            assert row is None or row.data.get("user_id") is None
            assert row is None or row.data.get("cx_access_token") is None


def test_propagate_sid_appends_to_same_origin_absolute(app_for_token):
    """同源绝对重定向（登录失败回调）应附加 _sid。"""
    with app_for_token.test_client() as client:
        # callback 失败会重定向到 /login，使用 _public_redirect 生成绝对 URL
        resp = client.get("/auth/chaoxing/callback?code=invalid", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert location.startswith("https://app.example.edu.cn/")
    assert "/login" in location
    assert "_sid=" in location


def test_propagate_sid_does_not_append_to_external_location(app_for_token):
    """外站 OAuth 等绝对跳转不得附加 _sid。"""
    from flask import Blueprint, redirect

    test_bp = Blueprint("test_external", __name__)

    @test_bp.get("/external-redirect")
    def _external_redirect():
        return redirect("https://auth.example.com/oauth?appid=123")

    app_for_token.register_blueprint(test_bp)

    with app_for_token.test_client() as client:
        client.get("/login")
        resp = client.get("/external-redirect", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert location == "https://auth.example.com/oauth?appid=123"
    assert "_sid=" not in location


def test_propagate_sid_rejects_malicious_absolute(app_for_token):
    """拒绝为同名前缀/端口不同的恶意域名附加 _sid。"""
    from flask import Blueprint, redirect

    test_bp = Blueprint("test_malicious", __name__)

    @test_bp.get("/malicious-redirect")
    def _malicious_redirect():
        return redirect("https://app.example.edu.cn.evil.com/student/home")

    app_for_token.register_blueprint(test_bp)

    with app_for_token.test_client() as client:
        client.get("/login")
        resp = client.get("/malicious-redirect", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert location == "https://app.example.edu.cn.evil.com/student/home"
    assert "_sid=" not in location
