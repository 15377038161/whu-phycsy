from __future__ import annotations

import time
from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import select
from werkzeug.security import check_password_hash

from ..db import db_session, transaction
from ..models import AuditEvent, FileAsset, User
from ..services.accounts import change_password

bp = Blueprint("auth", __name__)
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_SECONDS = 5 * 60
INLINE_MEDIA_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/webm", "video/quicktime",
    "application/pdf",
}


def _login_key(username: str) -> tuple[str, str]:
    return username.casefold(), request.remote_addr or "unknown"


def _recent_login_failures(key: tuple[str, str]) -> list[float]:
    now = time.monotonic()
    attempts = current_app.extensions["login_attempts"]
    with current_app.extensions["login_attempts_lock"]:
        recent = [value for value in attempts.get(key, []) if now - value < LOGIN_LOCK_SECONDS]
        if recent:
            attempts[key] = recent
        else:
            attempts.pop(key, None)
        return recent


def _record_login_failure(key: tuple[str, str]) -> int:
    recent = _recent_login_failures(key)
    with current_app.extensions["login_attempts_lock"]:
        current_app.extensions["login_attempts"][key] = [*recent, time.monotonic()]
        return len(recent) + 1


def _clear_login_failures(key: tuple[str, str]) -> None:
    with current_app.extensions["login_attempts_lock"]:
        current_app.extensions["login_attempts"].pop(key, None)


def _audit_login(action: str, username: str, user: User | None, attempts: int) -> None:
    with transaction() as db:
        db.add(AuditEvent(
            actor_id=user.id if user else None,
            action=action,
            entity_type="user",
            entity_id=(user.id if user else username[:64]) or "unknown",
            detail={"username": username[:120], "ip": request.remote_addr or "unknown", "attempts": attempts},
        ))


def current_user():
    user_id = session.get("user_id")
    return db_session().get(User, user_id) if user_id else None


def role_required(role):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user or user.role != role:
                return redirect(url_for("auth.login"))
            if user.must_change_password and request.endpoint != "auth.first_password":
                return redirect(url_for("auth.first_password"))
            return fn(*args, **kwargs)
        return wrapped
    return decorator


@bp.get("/")
def index():
    user = current_user()
    if user:
        return redirect(url_for("teacher.dashboard" if user.role == "teacher" else "student.home"))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        key = _login_key(username)
        user = db_session().scalar(select(User).where(User.username == username, User.active.is_(True)))
        recent = _recent_login_failures(key)
        if len(recent) >= LOGIN_FAILURE_LIMIT:
            _audit_login("login.locked", username, user, len(recent))
            flash("尝试过于频繁，请稍后再试。", "error")
            return render_template("login.html"), 429
        if user and check_password_hash(user.password_hash, request.form.get("password", "")):
            _clear_login_failures(key)
            session.clear()
            session["user_id"] = user.id
            if user.must_change_password:
                return redirect(url_for("auth.first_password"))
            return redirect(url_for("teacher.dashboard" if user.role == "teacher" else "student.home"))
        attempts = _record_login_failure(key)
        _audit_login("login.fail", username, user, attempts)
        flash("账号或密码错误。", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.post("/account/password")
def account_password():
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))
    try:
        change_password(user.id, request.form.get("current_password", ""), request.form.get("new_password", ""), request.form.get("confirm_password", ""))
        session.clear()
        flash("密码已更新，请使用新密码继续登录。", "success")
        return redirect(url_for("auth.login"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("teacher.dashboard" if user.role == "teacher" else "student.home"))


@bp.route("/account/first-password", methods=["GET", "POST"])
def first_password():
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))
    if not user.must_change_password:
        return redirect(url_for("teacher.dashboard" if user.role == "teacher" else "student.home"))
    if request.method == "POST":
        try:
            change_password(
                user.id,
                request.form.get("current_password", ""),
                request.form.get("new_password", ""),
                request.form.get("confirm_password", ""),
            )
            flash("新密码设置成功，欢迎进入实验平台。", "success")
            return redirect(url_for("student.home"))
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("first_password.html", user=user)


@bp.get("/media/<sha256>")
def media(sha256):
    if not current_user():
        return redirect(url_for("auth.login"))
    asset = db_session().get(FileAsset, sha256)
    if not asset or not (asset.content_type.startswith(("video/", "image/")) or asset.content_type in {"application/pdf", "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation"}):
        return "媒体文件不存在", 404
    path = __import__('pathlib').Path(current_app.config["DATA_DIR"]) / asset.object_key
    if not path.is_file():
        return "媒体文件缺失", 404
    inline = asset.content_type.lower() in INLINE_MEDIA_TYPES
    return send_file(
        path,
        mimetype=asset.content_type,
        conditional=True,
        as_attachment=not inline,
        download_name=asset.original_name,
    )
