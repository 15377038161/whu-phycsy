from __future__ import annotations

from werkzeug.security import check_password_hash

from auth_service import password_hash
from ..db import transaction
from ..models import AuditEvent, User


def _validate_new_password(password: str, confirmation: str) -> str:
    if password != confirmation:
        raise ValueError("两次输入的新密码不一致")
    if len(password) < 8:
        raise ValueError("新密码至少需要 8 个字符")
    if password.isdigit() or password.isalpha():
        raise ValueError("新密码必须同时包含字母和数字")
    return password


def change_password(user_id: str, current_password: str, new_password: str, confirmation: str) -> None:
    with transaction() as session:
        user = session.get(User, user_id)
        if not user or not check_password_hash(user.password_hash, current_password):
            raise ValueError("当前密码不正确")
        password = _validate_new_password(new_password, confirmation)
        if check_password_hash(user.password_hash, password):
            raise ValueError("新密码不能与当前密码相同")
        user.password_hash = password_hash(password)
        user.must_change_password = False
        session.add(AuditEvent(actor_id=user.id, action="account.password.change", entity_type="user", entity_id=user.id, detail={}))


def reset_student_password(actor_id: str, student_id: str, new_password: str, confirmation: str) -> None:
    password = _validate_new_password(new_password, confirmation)
    with transaction() as session:
        student = session.get(User, student_id)
        if not student or student.role != "student":
            raise ValueError("学生账号不存在")
        student.password_hash = password_hash(password)
        student.must_change_password = True
        session.add(AuditEvent(actor_id=actor_id, action="student.password.reset", entity_type="user", entity_id=student.id, detail={}))
