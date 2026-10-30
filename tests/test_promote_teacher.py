"""教师预授权与“输入超星 uid 提升教师”功能测试。

覆盖:
  1. promote_member_to_teacher 服务：新建占位教师、提升已有账号、幂等、输入校验、审计。
  2. ensure_initial_teachers：默认名单幂等预置；TEACHER_CXIDS 环境变量覆盖。
  3. POST /teacher/students/promote-teacher：教师可用、非教师被拦截、CSRF 生效、成功后重定向。
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from platform_app.db import db_session
from platform_app.models import AuditEvent, User


@pytest.fixture
def promote_app(tmp_path, monkeypatch):
    monkeypatch.delenv("TEACHER_CXIDS", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "testing")
    from platform_app import create_app

    return create_app({
        "TESTING": True,
        "APP_ENV": "testing",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'promote.db'}",
        "DATA_DIR": str(tmp_path / "files"),
        "SECRET_KEY": "promote-test",
    })


def _login(client, user_id: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_promote_creates_placeholder_teacher(promote_app):
    with promote_app.app_context():
        from platform_app.services.accounts import promote_member_to_teacher

        user = promote_member_to_teacher("T001", "90000001")
        assert user.role == "teacher"
        assert user.active is True
        assert user.chaoxing_cxid == "90000001"
        assert user.username == "cx_90000001"
        assert user.must_change_password is False
        audit = db_session().scalar(select(AuditEvent).where(AuditEvent.action == "member.promote_teacher"))
        assert audit is not None
        assert audit.detail["created"] is True


def test_promote_existing_student_and_reactivate(promote_app):
    with promote_app.app_context():
        from platform_app.services.accounts import promote_member_to_teacher
        from platform_app.db import transaction

        with transaction() as session:
            session.add(User(id="S900", username="S900", name="临时学生", role="student", password_hash="x", active=False, chaoxing_cxid="90000002"))
        user = promote_member_to_teacher("T001", "90000002")
        assert user.id == "S900"
        assert user.role == "teacher"
        assert user.active is True


def test_promote_is_idempotent(promote_app):
    with promote_app.app_context():
        from platform_app.services.accounts import promote_member_to_teacher

        promote_member_to_teacher("T001", "90000003")
        second = promote_member_to_teacher("T001", "90000003")
        count = db_session().scalar(select(func.count()).select_from(User).where(User.chaoxing_cxid == "90000003"))
        assert count == 1
        assert second.role == "teacher"


def test_promote_rejects_invalid_uid(promote_app):
    with promote_app.app_context():
        from platform_app.services.accounts import promote_member_to_teacher

        for bad in ("", "abc", "12", "9" * 33, "-90001"):
            with pytest.raises(ValueError):
                promote_member_to_teacher("T001", bad)


def test_ensure_initial_teachers_idempotent(promote_app, monkeypatch):
    monkeypatch.setenv("TEACHER_CXIDS", "238792026,167050732")
    with promote_app.app_context():
        from platform_app.services.accounts import ensure_initial_teachers

        first = ensure_initial_teachers()
        assert first == ["238792026", "167050732"]
        second = ensure_initial_teachers()
        assert second == []
        for xcid in ("238792026", "167050732"):
            user = db_session().scalar(select(User).where(User.chaoxing_cxid == xcid))
            assert user is not None and user.role == "teacher" and user.active is True
        untouched = db_session().scalar(select(User).where(User.chaoxing_cxid == "54837690"))
        assert untouched is None


def test_teacher_can_promote_via_route(promote_app):
    client = promote_app.test_client()
    _login(client, "T001")
    resp = client.post("/teacher/students/promote-teacher", data={"xcid": "88001122"}, follow_redirects=False)
    assert resp.status_code == 302
    with promote_app.app_context():
        user = db_session().scalar(select(User).where(User.chaoxing_cxid == "88001122"))
        assert user is not None and user.role == "teacher" and user.active is True


def test_student_cannot_promote_via_route(promote_app):
    client = promote_app.test_client()
    _login(client, "S001")
    resp = client.post("/teacher/students/promote-teacher", data={"xcid": "88003344"}, follow_redirects=False)
    assert resp.status_code == 302
    with promote_app.app_context():
        assert db_session().scalar(select(User).where(User.chaoxing_cxid == "88003344")) is None


def test_promote_route_without_csrf_rejected(promote_app, raw_client_open):
    client = promote_app.test_client()
    _login(client, "T001")
    resp = raw_client_open(client, "/teacher/students/promote-teacher", method="POST", data={"xcid": "88005566"})
    assert resp.status_code == 400
    with promote_app.app_context():
        assert db_session().scalar(select(User).where(User.chaoxing_cxid == "88005566")) is None


def test_promote_route_invalid_uid_flashes_error(promote_app):
    client = promote_app.test_client()
    _login(client, "T001")
    resp = client.post("/teacher/students/promote-teacher", data={"xcid": "not-a-number"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "3～32 位数字" in resp.data.decode()
