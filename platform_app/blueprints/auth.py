from __future__ import annotations

import base64
import json
import os
import time
from functools import wraps

import httpx
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
    """首页：匿名用户直接渲染登录页（200），已登录用户跳角色首页。

    不用 302 跳 /login 的原因：平台代理会缓存 GET / 的 302 响应（含旧会话
    票据与内部代理前缀），后续访客会拿到过期缓存导致预览打不开。
    """
    user = current_user()
    if user:
        return redirect(url_for("teacher.dashboard" if user.role == "teacher" else "student.home"))
    return render_template("login.html")


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


# ── 超星学习通 OAuth2.0 单点登录（服务端编排）────────────────────
# 契约（平台代理端点，appid/secret 均在服务端，前端不持有任何凭证）：
#   1. GET  {AUTH_BASE}/v1/api/coder/proxy/auth/chaoxing-oauth/authorize-url?redirect_uri=...
#      → { authorizeUrl }，浏览器顶层跳转至超星授权页（snsapi_base 静默授权）
#   2. 超星 302 回 <callback>?code=xxx
#   3. POST {AUTH_BASE}/v1/api/coder/proxy/auth/chaoxing-oauth/exchange
#      请求体 { code, projectId } → 返回 session JSON（含 access_token JWT）
#   4. 从 JWT payload 读取用户身份（cxid/realname），映射本地用户并建立服务端会话
# 说明：本应用不调用超星业务接口，故省略 checklogin 中转（该环节仅用于暂存业务凭证）。

_CHAOXING_AUTHORIZE_PATH = "/v1/api/coder/proxy/auth/chaoxing-oauth/authorize-url"
_CHAOXING_EXCHANGE_PATH = "/v1/api/coder/proxy/auth/chaoxing-oauth/exchange"
_CHAOXING_TIMEOUT = 10.0


def _chaoxing_auth_base() -> str:
    """认证代理基地址：开发模式读环境变量（隧道地址），生产退化为当前站点源（Nginx 转发）。
    严禁硬编码绝对 URL。"""
    base = os.getenv("CODER_AUTH_PROXY_URL", "").strip()
    if base:
        return base.rstrip("/")
    return request.url_root.rstrip("/")


def _chaoxing_project_id() -> str:
    return os.getenv("CODER_PROJECTS_ID") or os.getenv("NEXT_PUBLIC_CODER_PROJECTS_ID") or ""


def _decode_jwt_payload(token: str) -> dict:
    """解析 JWT payload（仅读取声明，签名校验已由签发方服务端完成）。"""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:
        return {}


@bp.get("/auth/chaoxing")
def chaoxing_login():
    """发起超星一键登录：换取授权地址并顶层跳转。"""
    callback = url_for("auth.chaoxing_callback", _external=True)
    base = _chaoxing_auth_base()
    try:
        resp = httpx.get(
            f"{base}{_CHAOXING_AUTHORIZE_PATH}",
            params={"redirect_uri": callback},
            headers={"ngrok-skip-browser-warning": "true"},
            timeout=_CHAOXING_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        current_app.logger.warning("chaoxing authorize-url request failed: %s", exc)
        flash("超星登录服务暂时不可用，请稍后再试或使用账号密码登录。", "error")
        return redirect(url_for("auth.login"))
    if resp.status_code != 200:
        current_app.logger.warning("chaoxing authorize-url -> %s", resp.status_code)
        flash("超星登录服务暂时不可用，请稍后再试或使用账号密码登录。", "error")
        return redirect(url_for("auth.login"))
    authorize_url = (resp.json() or {}).get("authorizeUrl")
    if not authorize_url:
        flash("超星登录服务返回异常，请稍后再试。", "error")
        return redirect(url_for("auth.login"))
    return redirect(authorize_url)


@bp.get("/auth/chaoxing/callback")
def chaoxing_callback():
    """超星授权回跳：code 换取身份，映射本地用户并建立会话。"""
    code = request.args.get("code", "").strip()
    if not code:
        flash("超星授权已取消或已过期，请重新登录。", "error")
        return redirect(url_for("auth.login"))

    base = _chaoxing_auth_base()
    try:
        resp = httpx.post(
            f"{base}{_CHAOXING_EXCHANGE_PATH}",
            json={"code": code, "projectId": _chaoxing_project_id()},
            headers={"ngrok-skip-browser-warning": "true"},
            timeout=_CHAOXING_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        current_app.logger.warning("chaoxing exchange request failed: %s", exc)
        flash("超星登录服务暂时不可用，请稍后再试。", "error")
        return redirect(url_for("auth.login"))
    if resp.status_code != 200:
        current_app.logger.warning("chaoxing exchange -> %s", resp.status_code)
        flash("登录链接已失效，请重新登录。", "error")
        return redirect(url_for("auth.login"))

    payload = resp.json() or {}
    claims = _decode_jwt_payload(payload.get("access_token", ""))
    metadata = claims.get("user_metadata") or {}
    cxid = str(metadata.get("cxid") or claims.get("sub") or "").strip()
    realname = str(metadata.get("realname") or metadata.get("name") or "").strip()
    if not cxid:
        current_app.logger.warning("chaoxing exchange: no cxid in token claims")
        flash("未能获取超星身份信息，请联系管理员。", "error")
        return redirect(url_for("auth.login"))

    # 映射本地用户：按超星 cxid 作为用户名查找，不存在则自动创建学生账号
    username = f"cx_{cxid}"
    with transaction() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(
                id=f"cx_{cxid}"[:64],
                username=username,
                name=realname or f"超星用户{cxid[-4:]}",
                role="student",
                password_hash="!chaoxing-oauth-no-password!",
                active=True,
                must_change_password=False,
            )
            db.add(user)
        elif not user.active:
            flash("账号已被停用，请联系管理员。", "error")
            return redirect(url_for("auth.login"))
        elif realname and user.name != realname:
            user.name = realname
        db.add(AuditEvent(
            actor_id=user.id,
            action="login.chaoxing",
            entity_type="user",
            entity_id=user.id,
            detail={"cxid": cxid[:64], "ip": request.remote_addr or "unknown"},
        ))

    session.clear()
    session["user_id"] = user.id
    session["chaoxing_cxid"] = cxid
    session.modified = True
    return redirect(url_for("teacher.dashboard" if user.role == "teacher" else "student.home"))


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
