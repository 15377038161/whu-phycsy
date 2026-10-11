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
from sqlalchemy import select

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


def _make_verified_user(cxid: str = "123456789", realname: str = "测试用户", metadata: dict | None = None):
    # 顶层 id 为平台已验证身份键，模拟 Supabase Auth 的不可用户编辑 sub/uid。
    # user_metadata 仅保留姓名等辅助信息，不再用于身份绑定。
    user_metadata = {"realname": realname}
    if metadata:
        user_metadata.update(metadata)
    return {
        "id": cxid,
        "aud": "authenticated",
        "role": "authenticated",
        "user_metadata": user_metadata,
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
    from platform_app.models import User

    exchange_resp = _make_exchange_response("tok-access-abc", "tok-refresh-xyz")
    # 教师身份仅由本地授权记录决定；预先创建 active teacher 以跳过 enrollment 检查。
    user = _make_verified_user(cxid="teacher-token", realname="测试教师", metadata={"role": "teacher"})

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

    with app_for_token.app_context():
        db_session().add(
            User(
                id="teacher-token",
                username="cx_teacher-token",
                name="测试教师",
                role="teacher",
                password_hash="!test!",
                active=True,
                must_change_password=False,
                chaoxing_cxid="teacher-token",
            )
        )
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    # 必须为同源绝对 URL（避免网关把根相对 Location 重写为沙箱前缀）
    assert location.startswith("https://app.example.edu.cn/")
    assert "/teacher" in location
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
    from platform_app.models import User

    exchange_resp = _make_exchange_response("access-before", "refresh-before")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(200, _make_verified_user(cxid="teacher-token", realname="测试教师", metadata={"role": "teacher"}))
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    # 教师身份仅由本地授权记录决定；预先创建 active teacher。
    with app_for_token.app_context():
        db_session().add(
            User(
                id="teacher-token",
                username="cx_teacher-token",
                name="测试教师",
                role="teacher",
                password_hash="!test!",
                active=True,
                must_change_password=False,
                chaoxing_cxid="teacher-token",
            )
        )
        db_session().commit()

    with app_for_token.test_client() as client:
        # 先以教师身份登录，确保成功建立会话
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)
        assert "/teacher" in (resp.headers.get("Location") or "")
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
            assert row is not None and row.data.get("user_id") is not None
            csrf = row.data.get("_csrf_token")

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


def _seed_teacher_and_course(db, course_name="量子力学实验"):
    """创建教师和课程，返回二者。"""
    from platform_app.models import Course, User

    teacher = User(
        id="teacher-001",
        username="teacher-001",
        name="教师甲",
        role="teacher",
        password_hash="!test!",
        active=True,
    )
    course = Course(
        id="course-001",
        teacher_id=teacher.id,
        name=course_name,
        min_experiments_required=2,
    )
    db.add_all([teacher, course])
    db.commit()
    return teacher, course


def _seed_teacher_course_student(db, course_name="量子力学实验", student_no="S001"):
    """创建教师、课程和学生（无 enrollment），返回三者。"""
    from platform_app.models import User

    teacher, course = _seed_teacher_and_course(db, course_name=course_name)
    student = User(
        id=student_no,
        username=student_no,
        name="学生甲",
        role="student",
        password_hash="!test!",
        active=True,
    )
    db.add(student)
    db.commit()
    return teacher, course, student


def test_sso_student_without_enrollment_is_rejected(app_for_token, supabase_env, monkeypatch):
    """首次超星 SSO 学生无教师授权 enrollment 时，不得自动加入课程或建立会话。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-no-enroll", "refresh-no-enroll")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(200, _make_verified_user(cxid="no-enroll", realname="未入课学生"))
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    # 只准备教师与课程，学生名单未导入
    with app_for_token.app_context():
        _seed_teacher_and_course(db_session())

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert location.startswith("https://app.example.edu.cn/")
    assert "/login" in location
    assert "/student/home" not in location

    with app_for_token.app_context():
        # 拒绝时不应创建任何用户或 enrollment
        sso_user = db_session().scalar(select(User).where(User.username == "cx_no-enroll"))
        assert sso_user is None, "无 enrollment 学生被拒绝时不应新建 cx_ 用户"
        assert (
            db_session().query(Enrollment).where(Enrollment.student_id == "cx_no-enroll").count() == 0
        )
        # 会话中不应有 user_id（保持匿名，仅承载 flash 提示）
        rows = db_session().query(AppSession).all()
        assert not any(r.data.get("user_id") for r in rows)
        assert len(rows) >= 1


def test_sso_matched_roster_without_enrollment_does_not_update_cxid(
    app_for_token, supabase_env, monkeypatch
):
    """名单学生无 enrollment 时，SSO 匹配后不得更新其 chaoxing_cxid 或创建 enrollment。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-matched-no-enroll", "refresh-matched-no-enroll")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="matched-no-enroll",
                    realname="学生甲",
                    metadata={"student_no": "matched-no-enroll-student"},
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course, student = _seed_teacher_course_student(
            db_session(), student_no="matched-no-enroll-student"
        )
        original_cxid = student.chaoxing_cxid

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")

    with app_for_token.app_context():
        refreshed = db_session().get(User, student.id)
        assert refreshed.chaoxing_cxid == original_cxid
        assert db_session().query(Enrollment).where(Enrollment.student_id == student.id).count() == 0


def test_sso_reject_clears_existing_session(app_for_token, supabase_env, monkeypatch):
    """已登录session携带user_id与令牌时，另一个无成员SSO回调应清除旧身份并拒绝业务页。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-token", "refresh-token")
    identity = {
        "cxid": "teacher-token",
        "realname": "测试教师",
        "metadata": {"role": "teacher"},
    }

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(200, _make_verified_user(**identity))
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    # 先准备一名无 enrollment 学生和一名本地已授权教师（教师用于建立旧会话）
    with app_for_token.app_context():
        teacher, course, student = _seed_teacher_course_student(
            db_session(), student_no="session-clear-student"
        )
        # 教师身份仅由本地授权记录决定；将教师账号绑定到即将使用的 cx_ 用户名
        teacher.username = "cx_teacher-token"
        teacher.chaoxing_cxid = "teacher-token"
        db_session().add(Enrollment(course_id=course.id, student_id=teacher.id))
        db_session().commit()

    def _sid_from(location: str) -> str:
        return location.split("_sid=")[-1].split("&")[0] if "_sid=" in location else ""

    with app_for_token.test_client() as client:
        # 第一步：以教师身份登录，建立带 user_id 和令牌的旧会话
        identity.update(
            {"cxid": "teacher-token", "realname": "测试教师", "metadata": {"role": "teacher"}}
        )
        resp1 = client.get("/auth/chaoxing/callback?code=teacher", follow_redirects=False)
        assert resp1.status_code == 302
        old_location = resp1.headers.get("Location", "")
        assert "/teacher" in old_location
        old_sid = _sid_from(old_location)
        assert old_sid

        with app_for_token.app_context():
            old_row = db_session().get(AppSession, old_sid)
            assert old_row is not None
            assert old_row.data.get("user_id") is not None
            assert old_row.data.get("cx_access_token") is not None

        # 第二步：同一浏览器发起另一个无 enrollment 学生的 SSO 回调
        identity.update(
            {"cxid": "session-clear-student", "realname": "学生甲", "metadata": {}}
        )
        resp2 = client.get("/auth/chaoxing/callback?code=student", follow_redirects=False)
        assert resp2.status_code == 302
        new_location = resp2.headers.get("Location", "")
        assert "/login" in new_location
        # 同一 _sid 票据会被复用，但服务端数据已被清空
        new_sid = _sid_from(new_location)
        assert new_sid == old_sid

        # 第三步：业务页应拒绝访问
        resp3 = client.get("/student/home", follow_redirects=False)
        assert resp3.status_code == 302
        assert "/login" in resp3.headers.get("Location", "")

        with app_for_token.app_context():
            row = db_session().get(AppSession, old_sid)
            assert row is not None
            assert row.data.get("user_id") is None
            assert row.data.get("cx_access_token") is None
            assert row.data.get("cx_refresh_token") is None


def test_sso_student_with_existing_enrollment_keeps_it(app_for_token, supabase_env, monkeypatch):
    """已有教师授权 enrollment 的学生 SSO 登录后，正常进入首页且 enrollment 不变。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-has-enroll", "refresh-has-enroll")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="has-enroll",
                    realname="学生甲",
                    metadata={"student_no": "has-enroll-student"},
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course, student = _seed_teacher_course_student(
            db_session(), student_no="has-enroll-student"
        )
        # 教师已预先绑定该学生的超星身份
        student.chaoxing_cxid = "has-enroll"
        db_session().add(Enrollment(course_id=course.id, student_id=student.id))
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert location.startswith("https://app.example.edu.cn/")
    assert "/student/home" in location

    with app_for_token.app_context():
        # 该学生的 enrollment 应保持唯一且不变
        enrollments = (
            db_session().query(Enrollment).where(Enrollment.student_id == student.id).all()
        )
        assert len(enrollments) == 1
        assert enrollments[0].course_id == course.id
        assert enrollments[0].student_id == student.id
        # 不应额外创建独立的 cx_ 账号
        assert (
            db_session().scalar(select(User).where(User.username == "cx_has-enroll")) is None
        )


def test_sso_student_does_not_auto_join_second_course(app_for_token, supabase_env, monkeypatch):
    """学生只被授权加入 course1 时，SSO 登录不得自动加入 course2。"""
    from platform_app.db import db_session
    from platform_app.models import Course, Enrollment, User

    exchange_resp = _make_exchange_response("access-multi", "refresh-multi")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="multi-course",
                    realname="学生甲",
                    metadata={"student_no": "multi-course-student"},
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course1, student = _seed_teacher_course_student(
            db_session(), course_name="课程甲", student_no="multi-course-student"
        )
        # 教师已预先绑定该学生的超星身份
        student.chaoxing_cxid = "multi-course"
        course2 = Course(
            id="course-002",
            teacher_id=teacher.id,
            name="课程乙",
            min_experiments_required=2,
        )
        db_session().add(course2)
        db_session().add(Enrollment(course_id=course1.id, student_id=student.id))
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/student/home" in location

    with app_for_token.app_context():
        enrollments = (
            db_session().query(Enrollment).where(Enrollment.student_id == student.id).all()
        )
        assert len(enrollments) == 1
        assert enrollments[0].course_id == course1.id
        assert enrollments[0].student_id == student.id
        # 不应为 course2 自动创建 enrollment
        assert (
            db_session()
            .query(Enrollment)
            .where(Enrollment.course_id == course2.id, Enrollment.student_id == student.id)
            .count()
            == 0
        )
        assert (
            db_session().scalar(select(User).where(User.username == "cx_multi-course")) is None
        )


def test_sso_pseudo_teacher_metadata_without_enrollment_is_rejected(
    app_for_token, supabase_env, monkeypatch
):
    """user_metadata 含 teacher/admin/单位号 1385 但无 enrollment 时，不得创建 teacher 或登录。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-pseudo-teacher", "refresh-pseudo-teacher")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="pseudo-teacher",
                    realname="伪教师",
                    metadata={
                        "role": "teacher",
                        "type": "administrator",
                        "unitid": "1385",
                        "jobtitle": "教授",
                    },
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        _seed_teacher_and_course(db_session())
        enrollment_count_before = db_session().query(Enrollment).count()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location
    assert "/teacher" not in location

    with app_for_token.app_context():
        # 不得创建任何用户，更不得创建 teacher
        sso_user = db_session().scalar(select(User).where(User.username == "cx_pseudo-teacher"))
        assert sso_user is None
        assert (
            db_session()
            .query(User)
            .where(User.chaoxing_cxid == "pseudo-teacher", User.role == "teacher")
            .count()
            == 0
        )
        # 教师自己的 enrollment 可存在，但不得为伪教师新建任何 enrollment
        assert db_session().query(Enrollment).count() == enrollment_count_before


def test_sso_student_with_teacher_metadata_remains_student(app_for_token, supabase_env, monkeypatch):
    """已有 enrollment 的学生即使元数据被标为 teacher/admin/1385，仍按 student 正常登录。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-student-teacher-meta", "refresh-student-teacher-meta")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="student-teacher-meta",
                    realname="学生甲",
                    metadata={
                        "student_no": "student-teacher-meta",
                        "role": "teacher",
                        "unitid": "1385",
                        "type": "admin",
                    },
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course, student = _seed_teacher_course_student(
            db_session(), student_no="student-teacher-meta"
        )
        # 教师已预先绑定该学生的超星身份
        student.chaoxing_cxid = "student-teacher-meta"
        db_session().add(Enrollment(course_id=course.id, student_id=student.id))
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/student/home" in location
    assert "/teacher/dashboard" not in location

    with app_for_token.app_context():
        refreshed = db_session().get(User, student.id)
        assert refreshed.role == "student"
        assert refreshed.chaoxing_cxid == "student-teacher-meta"
        enrollments = (
            db_session().query(Enrollment).where(Enrollment.student_id == student.id).all()
        )
        assert len(enrollments) == 1


def test_sso_existing_local_teacher_preserved(app_for_token, supabase_env, monkeypatch):
    """本地已授权 active teacher 通过超星 SSO 登录时，保留 teacher 角色并进入教师首页。"""
    from platform_app.db import db_session
    from platform_app.models import User

    exchange_resp = _make_exchange_response("access-local-teacher", "refresh-local-teacher")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="local-teacher",
                    realname="本地教师",
                    metadata={"role": "student", "type": "本科生"},
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher = User(
            id="teacher-local",
            username="cx_local-teacher",
            name="本地教师",
            role="teacher",
            password_hash="!test!",
            active=True,
            must_change_password=False,
            chaoxing_cxid="local-teacher",
        )
        db_session().add(teacher)
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/teacher" in location
    assert "/student/home" not in location

    with app_for_token.app_context():
        refreshed = db_session().get(User, teacher.id)
        assert refreshed.role == "teacher"
        assert refreshed.active is True


def test_sso_forged_student_no_cannot_take_over_roster_user(
    app_for_token, supabase_env, monkeypatch
):
    """攻击者伪造 user_metadata 中学号，不得接管教师已导入的名单学生账号。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    # 攻击者把自己的 verified id 设为 attacker-cxid，但在 user_metadata 中伪造目标学号
    exchange_resp = _make_exchange_response("access-forged-sno", "refresh-forged-sno")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="attacker-cxid",
                    realname="学生甲",
                    metadata={"student_no": "victim-student"},
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course, victim = _seed_teacher_course_student(
            db_session(), student_no="victim-student"
        )
        db_session().add(Enrollment(course_id=course.id, student_id=victim.id))
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location
    assert "/student/home" not in location

    with app_for_token.app_context():
        # 攻击者账号不应被创建
        assert db_session().scalar(select(User).where(User.username == "cx_attacker-cxid")) is None
        # 受害者账号绑定关系不应被修改
        victim_refreshed = db_session().get(User, victim.id)
        assert victim_refreshed.chaoxing_cxid is None
        # 受害者 enrollment 不变
        assert (
            db_session().query(Enrollment).where(Enrollment.student_id == victim.id).count() == 1
        )


def test_sso_forged_realname_cannot_take_over_roster_user(
    app_for_token, supabase_env, monkeypatch
):
    """攻击者伪造 user_metadata 中姓名，不得通过姓名唯一匹配接管他人账号。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-forged-name", "refresh-forged-name")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(
                200,
                _make_verified_user(
                    cxid="attacker-cxid-2",
                    realname="学生甲",  # 伪造姓名，与受害者相同
                    metadata={},
                ),
            )
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course, victim = _seed_teacher_course_student(
            db_session(), student_no="victim-student-2"
        )
        victim.name = "学生甲"
        db_session().add(Enrollment(course_id=course.id, student_id=victim.id))
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location

    with app_for_token.app_context():
        assert db_session().scalar(select(User).where(User.username == "cx_attacker-cxid-2")) is None
        victim_refreshed = db_session().get(User, victim.id)
        assert victim_refreshed.chaoxing_cxid is None


def test_sso_bound_student_with_enrollment_logs_in_normally(
    app_for_token, supabase_env, monkeypatch
):
    """教师预绑定且已入课的学生，SSO 正常登录并保留 enrollment。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-bound", "refresh-bound")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(200, _make_verified_user(cxid="bound-student", realname="学生甲"))
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course, student = _seed_teacher_course_student(
            db_session(), student_no="bound-student-local"
        )
        student.chaoxing_cxid = "bound-student"
        db_session().add(Enrollment(course_id=course.id, student_id=student.id))
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/student/home" in location

    with app_for_token.app_context():
        refreshed = db_session().get(User, student.id)
        assert refreshed.chaoxing_cxid == "bound-student"
        assert refreshed.role == "student"
        assert (
            db_session().query(Enrollment).where(Enrollment.student_id == student.id).count() == 1
        )


def test_sso_identity_conflict_rejects_login(app_for_token, supabase_env, monkeypatch):
    """同一超星身份已被其他本地账号绑定时，当前账号登录应被拒绝。"""
    from platform_app.db import db_session
    from platform_app.models import Enrollment, User

    exchange_resp = _make_exchange_response("access-conflict", "refresh-conflict")

    def fake_post(url, *, json, headers, timeout):
        if "/exchange" in url:
            return _FakeResponse(200, exchange_resp)
        return _FakeResponse(500, {})

    def fake_get(url, *, headers, timeout):
        if "/auth/v1/user" in url:
            return _FakeResponse(200, _make_verified_user(cxid="conflict-identity", realname="学生乙"))
        return _FakeResponse(500, {})

    monkeypatch.setattr("platform_app.blueprints.auth.httpx.post", fake_post)
    monkeypatch.setattr("platform_app.blueprints.auth.httpx.get", fake_get)

    with app_for_token.app_context():
        teacher, course, student_a = _seed_teacher_course_student(
            db_session(), student_no="student-a"
        )
        # 学生 A 已预先绑定该超星身份
        student_a.chaoxing_cxid = "conflict-identity"
        # 学生 B 的 username 与 SSO 自动生成的 cx_<identity> 冲突，但尚未绑定
        student_b = User(
            id="student-b",
            username="cx_conflict-identity",
            name="学生乙",
            role="student",
            password_hash="!test!",
            active=True,
        )
        db_session().add(student_b)
        db_session().add(Enrollment(course_id=course.id, student_id=student_a.id))
        db_session().commit()

    with app_for_token.test_client() as client:
        resp = client.get("/auth/chaoxing/callback?code=fake-code", follow_redirects=False)

    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "/login" in location
    assert "/student/home" not in location

    with app_for_token.app_context():
        # 学生 B 不应被绑定到该超星身份
        student_b_refreshed = db_session().get(User, student_b.id)
        assert student_b_refreshed.chaoxing_cxid is None
        # 学生 A 的绑定保持不变
        student_a_refreshed = db_session().get(User, student_a.id)
        assert student_a_refreshed.chaoxing_cxid == "conflict-identity"
