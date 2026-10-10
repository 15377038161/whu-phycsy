"""Supabase Auth/Data API 服务端诊断端点安全测试。

覆盖：
  1. 诊断端点仅对已登录用户可用，且受 CSRF 保护
  2. 仅返回固定状态枚举，不输出 user_id / role / cxid / JWT / SID / 行内容
  3. 服务端使用会话中的用户 JWT 调用 Supabase Auth / Data API
  4. token 过期时能在服务端静默刷新，刷新后必须重新 getUser 验证
  5. Data API 返回非本人归属行时拒绝并返回固定 forbidden 状态
  6. 缺失环境变量、缺失 token、Auth 无 UUID、Data API 403 等异常状态正确上报
"""

from __future__ import annotations

import pytest

from platform_app.models import AppSession, User


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


def _auth_user(uid: str = "00000000-0000-0000-0000-000000000000") -> dict:
    return {
        "id": uid,
        "aud": "authenticated",
        "role": "authenticated",
        "user_metadata": {},
    }


def _assert_status_only(resp, expected_status: str) -> None:
    """断言响应只包含固定 status 字段，不含任何个人资料或标识。"""
    assert resp.status_code == 200
    data = resp.json
    assert data == {"status": expected_status}
    text = resp.get_data(as_text=True)
    assert "cx_123456789" not in text
    assert "123456789" not in text
    assert "测试用户" not in text
    assert "00000000-0000-0000-0000-000000000000" not in text
    assert "student" not in text
    assert "teacher" not in text


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
    _assert_status_only(resp, "missing_env")


def test_diag_auth_no_token(diag_app, sample_user, supabase_env):
    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        resp = client.post("/api/diag/auth")
    _assert_status_only(resp, "no_token")


def test_diag_auth_ok(diag_app, sample_user, supabase_env, monkeypatch):
    monkeypatch.setattr(
        "platform_app.blueprints.auth.httpx.get",
        lambda *args, **kwargs: _FakeResponse(200, _auth_user()),
    )

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
            sess["cx_refresh_token"] = "test-refresh-token"
        resp = client.post("/api/diag/auth")

    _assert_status_only(resp, "ok")


def test_diag_auth_refreshes_expired_token_and_re_verifies(diag_app, sample_user, supabase_env, monkeypatch):
    get_calls = []
    new_access = "new-access-token"

    def fake_get(url, *, headers, timeout):
        get_calls.append((url, headers))
        if len(get_calls) == 1:
            return _FakeResponse(401, {"error": "invalid token"})
        # 刷新后重新 getUser 验证以及 data diag 调用都返回成功
        auth_header = headers.get("Authorization", "")
        if auth_header == f"Bearer {new_access}":
            return _FakeResponse(200, _auth_user())
        return _FakeResponse(200, _auth_user())

    def fake_post(url, *, json, headers, timeout):
        return _FakeResponse(200, {
            "access_token": new_access,
            "refresh_token": "new-refresh-token",
            "token_type": "bearer",
            "expires_in": 3600,
            "user": _auth_user(),
        })

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "old-access-token"
            sess["cx_refresh_token"] = "old-refresh-token"
        resp = client.post("/api/diag/auth")

    _assert_status_only(resp, "ok")
    # 至少两次 getUser：第一次旧 token 失败，刷新后重新验证新 token
    assert len(get_calls) >= 2
    assert get_calls[-1][1]["Authorization"] == f"Bearer {new_access}"

    # 服务端会话应已更新为新令牌
    with diag_app.app_context():
        from platform_app.db import db_session

        rows = db_session().query(AppSession).all()
        session_row = next((r for r in rows if r.data.get("user_id") == sample_user.id), None)
        assert session_row is not None
        assert session_row.data.get("cx_access_token") == new_access
        assert session_row.data.get("cx_refresh_token") == "new-refresh-token"


def test_diag_auth_refresh_without_reverify_fails(diag_app, sample_user, supabase_env, monkeypatch):
    """刷新响应后若重新 getUser 失败，必须返回 invalid，不能返回 ok。"""
    def fake_get(url, *, headers, timeout):
        # 旧 token 失败，刷新后的新 token 也失败
        return _FakeResponse(401, {"error": "invalid token"})

    def fake_post(url, *, json, headers, timeout):
        return _FakeResponse(200, {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "token_type": "bearer",
            "expires_in": 3600,
            "user": _auth_user(),
        })

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "old-access-token"
            sess["cx_refresh_token"] = "old-refresh-token"
        resp = client.post("/api/diag/auth")

    _assert_status_only(resp, "invalid")


def test_diag_data_ok_mapping_exists(diag_app, sample_user, supabase_env, monkeypatch):
    my_uid = "00000000-0000-0000-0000-000000000000"

    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, _auth_user(my_uid))

    def fake_request(method, url, *, headers, timeout):
        return _FakeResponse(200, [{"auth_user_id": my_uid}])

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.request", fake_request)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/data")

    _assert_status_only(resp, "ok")


def test_diag_data_rejects_other_user_row(diag_app, sample_user, supabase_env, monkeypatch):
    """Data API 返回归属不匹配的行时，必须拒绝并返回 forbidden。"""
    my_uid = "00000000-0000-0000-0000-000000000000"
    other_uid = "11111111-1111-1111-1111-111111111111"

    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, _auth_user(my_uid))

    def fake_request(method, url, *, headers, timeout):
        # 模拟异常返回：行的 auth_user_id 与当前 UUID 不一致
        return _FakeResponse(200, [{"auth_user_id": other_uid}])

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.request", fake_request)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/data")

    _assert_status_only(resp, "forbidden")


def test_diag_data_forbidden_by_rls(diag_app, sample_user, supabase_env, monkeypatch):
    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, _auth_user())

    def fake_request(method, url, *, headers, timeout):
        return _FakeResponse(403, {"message": "Access denied by RLS"})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.request", fake_request)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/data")

    _assert_status_only(resp, "forbidden")


def test_diag_data_missing_uuid(diag_app, sample_user, supabase_env, monkeypatch):
    """Auth getUser 返回的 user 对象缺少 id 时，返回固定 invalid 状态。"""
    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, {"aud": "authenticated", "role": "authenticated"})

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/data")

    _assert_status_only(resp, "invalid")


def test_diag_data_bad_json(diag_app, sample_user, supabase_env, monkeypatch):
    """Data API 返回坏 JSON 时，返回固定 unreachable 状态，不泄露原始内容。"""
    class _BadJsonResponse:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, _auth_user())

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.request", lambda *a, **k: _BadJsonResponse())

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post("/api/diag/data")

    _assert_status_only(resp, "unreachable")


def test_diag_data_response_does_not_contain_tokens(diag_app, sample_user, supabase_env, monkeypatch):
    """确保响应体中完全没有 JWT、SID、apikey 等敏感内容。"""
    def fake_get(url, *, headers, timeout):
        return _FakeResponse(200, _auth_user())

    def fake_request(method, url, *, headers, timeout):
        return _FakeResponse(200, [{"auth_user_id": "00000000-0000-0000-0000-000000000000"}])

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)
    monkeypatch.setattr("platform_app.supabase_client.httpx.request", fake_request)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
            sess["cx_refresh_token"] = "secret-refresh-token"
        resp = client.post("/api/diag/data")

    text = resp.get_data(as_text=True)
    assert "secret-access-token" not in text
    assert "secret-refresh-token" not in text
    assert "fake-anon-key" not in text
    # 响应只含固定状态
    assert resp.json == {"status": "ok"}


def test_diag_auth_html_response_for_browser(diag_app, sample_user, supabase_env, monkeypatch):
    """浏览器表单提交（Accept: text/html）时应得到简单 HTML 结果页。"""
    monkeypatch.setattr(
        "platform_app.blueprints.auth.httpx.get",
        lambda *args, **kwargs: _FakeResponse(200, _auth_user()),
    )

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "test-access-token"
        resp = client.post(
            "/api/diag/auth",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )

    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    text = resp.get_data(as_text=True)
    assert "连接诊断" in text
    assert "ok" in text
    assert "secret-access-token" not in text
    assert "cx_123456789" not in text