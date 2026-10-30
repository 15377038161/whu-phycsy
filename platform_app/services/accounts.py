from __future__ import annotations

import os
import secrets
import uuid

from sqlalchemy import select
from werkzeug.security import check_password_hash

from auth_service import password_hash
from ..db import transaction
from ..models import AuditEvent, User

# 初始教师超星 uid 名单：可通过 TEACHER_CXIDS 环境变量覆盖（逗号分隔）。
# 这些账号在首次超星 SSO 登录前以占位记录存在（role=teacher + active），
# 登录时按 chaoxing_cxid 匹配到占位记录并同步真实姓名/头像。
DEFAULT_TEACHER_CXIDS = "238792026,167050732,54837690"


def promote_member_to_teacher(actor_id: str | None, xcid: str) -> User:
    """按超星 uid 将成员设为教师并激活；不存在时创建绑定该 uid 的占位教师账号。

    - 已存在绑定该 uid 的账号（无论原角色）：直接 role=teacher + active=True；
    - 仅用户名匹配 cx_<uid> 但未绑定 cxid：补绑定并提升；
    - 完全不存在：创建 username=cx_<uid> 的占位教师，首次 SSO 登录自动补全资料。
    全程写审计事件；输入校验失败抛 ValueError。
    """
    xcid = (xcid or "").strip()
    if not xcid.isdigit() or not 3 <= len(xcid) <= 32:
        raise ValueError("超星 uid 必须是 3～32 位数字")
    with transaction() as session:
        user = session.scalar(select(User).where(User.chaoxing_cxid == xcid))
        created = False
        if user is None:
            user = session.scalar(select(User).where(User.username == f"cx_{xcid}"))
        if user is None:
            user = User(
                id=str(uuid.uuid4()),
                username=f"cx_{xcid}",
                name=f"教师{xcid}",
                role="teacher",
                active=True,
                password_hash=password_hash(secrets.token_urlsafe(24)),
                chaoxing_cxid=xcid,
            )
            session.add(user)
            session.flush()
            created = True
        else:
            user.role = "teacher"
            user.active = True
            if not user.chaoxing_cxid:
                user.chaoxing_cxid = xcid
        session.add(AuditEvent(
            actor_id=actor_id,
            action="member.promote_teacher",
            entity_type="user",
            entity_id=user.id,
            detail={"xcid": xcid, "username": user.username, "created": created},
        ))
        return user


def ensure_initial_teachers() -> list[str]:
    """幂等预置初始教师名单（preview/production 启动时调用）。

    重复启动不会重复创建；TEACHER_CXIDS 可覆盖默认名单，留空则跳过。
    返回本次实际新创建的 uid 列表。
    """
    raw = os.getenv("TEACHER_CXIDS", DEFAULT_TEACHER_CXIDS)
    created: list[str] = []
    for part in raw.split(","):
        xcid = part.strip()
        if not xcid:
            continue
        with transaction() as session:
            exists = session.scalar(select(User).where(User.chaoxing_cxid == xcid))
            if exists:
                continue
        try:
            promote_member_to_teacher(None, xcid)
            created.append(xcid)
        except ValueError:
            continue
    return created


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
