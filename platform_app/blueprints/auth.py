from __future__ import annotations

import json
import os
import time
from functools import wraps

import httpx
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import or_, select
from werkzeug.security import check_password_hash

from ..db import db_session, transaction
from ..models import AuditEvent, Course, Enrollment, FileAsset, User
from ..services.accounts import change_password
from ..session_store import current_sid

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
    """认证代理基地址：服务端到服务端调用超星 authorize/exchange 端点。

    开发模式读 CODER_AUTH_PROXY_URL（隧道地址）；否则退化为 request.url_root。
    该地址用于后端直连平台认证代理，公开部署中沙箱内部即可达，无需对浏览器可见。
    严禁硬编码绝对 URL。"""
    base = os.getenv("CODER_AUTH_PROXY_URL", "").strip()
    if base:
        return base.rstrip("/")
    return request.url_root.rstrip("/")


def _app_public_base() -> str:
    """应用对外公开 base URL（用于超星 OAuth 回跳 redirect_uri，浏览器可见）。

    与认证代理地址严格区分：这里必须指向用户浏览器可访问的公开域名，而非
    后端内部地址。公开部署的代理会把 X-Forwarded-Host 写成内部沙箱地址
    （如 sandbox-xxx-8080.cxiagents.com），ProxyFix 的 x_host=1 会信任该头，
    导致 url_for(_external=True) 生成沙箱回跳地址、浏览器跳回沙箱而非公开域名。

    因此这里绝不依赖 request.url_root，而是按优先级取受信任配置：
      1. APP_PUBLIC_BASE_URL  —— 显式配置的公开域名（公开部署必填），
      2. CODER_PROJECTS_DOMAIN —— 平台注入的对外访问域名，
      3. request.url_root      —— 仅本地开发（无任何配置）兜底。
    严禁硬编码任何域名。"""
    base = os.getenv("APP_PUBLIC_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    base = os.getenv("CODER_PROJECTS_DOMAIN", "").strip()
    if base:
        return base.rstrip("/")
    return request.url_root.rstrip("/")


def _chaoxing_project_id() -> str:
    return os.getenv("CODER_PROJECTS_ID") or os.getenv("NEXT_PUBLIC_CODER_PROJECTS_ID") or ""


def _supabase_env() -> tuple[str, str, str] | None:
    """返回内置 Supabase Data API 环境变量三元组 (url, anon_key, tenant_id)。

    未配置时返回 None，此时无法通过 Supabase Auth 端点校验 access_token
    或调用 Data API。严禁在任何地方输出 anon_key。"""
    url = os.getenv("CODER_SUPABASE_URL", "").strip()
    anon_key = os.getenv("CODER_SUPABASE_ANON_KEY", "").strip()
    tenant_id = os.getenv("CODER_SUPABASE_TENANT_ID", "").strip()
    if not url or not anon_key or not tenant_id:
        return None
    return url.rstrip("/"), anon_key, tenant_id


def _verify_access_token(access_token: str) -> tuple[dict | None, str | None]:
    """通过 Supabase Auth /auth/v1/user 端点校验 access_token，返回可信用户对象。

    这是平台认可的用户校验方式：verify-session.md 中 createSupabaseServer(token)
    .auth.getUser() 的 REST 等价实现。不本地 decode JWT，不输出令牌内容到日志。
    """
    env = _supabase_env()
    if env is None:
        return None, "Supabase 环境变量不完整，无法校验令牌"
    url, anon_key, tenant_id = env
    try:
        resp = httpx.get(
            f"{url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": anon_key,
                "X-Instance-ID": tenant_id,
            },
            timeout=_CHAOXING_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return None, f"Supabase Auth 校验请求失败: {exc}"
    if resp.status_code != 200:
        return None, f"Supabase Auth 校验失败 ({resp.status_code})"
    return resp.json(), None


def _refresh_access_token(refresh_token: str) -> tuple[dict | None, str | None]:
    """用 refresh_token 换取新的 Supabase session（access_token/refresh_token）。"""
    env = _supabase_env()
    if env is None:
        return None, "Supabase 环境变量不完整，无法刷新令牌"
    url, anon_key, tenant_id = env
    try:
        resp = httpx.post(
            f"{url}/auth/v1/token?grant_type=refresh_token",
            json={"refresh_token": refresh_token},
            headers={
                "apikey": anon_key,
                "X-Instance-ID": tenant_id,
                "Content-Type": "application/json",
            },
            timeout=_CHAOXING_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return None, f"令牌刷新请求失败: {exc}"
    if resp.status_code != 200:
        return None, f"令牌刷新失败 ({resp.status_code})"
    return resp.json(), None


# 教师身份自动识别：从超星用户元数据中提取「身份类型 / 单位号」判定角色。
# 超星 token 的 user_metadata 字段命名不稳定，这里做多字段兼容 + 关键词匹配。
_TEACHER_UNIT_CODES = {"1385"}  # 武汉大学单位号（教师类）
# 教师/管理员类关键词：覆盖「教师」与「管理员/admin」两类身份，避免管理员被误判为学生。
_TEACHER_IDENTITY_KEYWORDS = (
    "teacher", "教师", "老师", "讲师", "教授", "助教", "职工", "教职工",
    "admin", "administrator", "管理员", "教务", "教学管理", "辅导员",
)
# 学生类反向关键词：命中则排除教师判定（优先于教师关键词）。
_STUDENT_IDENTITY_KEYWORDS = ("student", "学生", "本科生", "研究生", "博士生", "硕士生")


def _detect_chaoxing_role(metadata: dict, claims: dict) -> str:
    """判定超星用户角色：命中教师/管理员身份特征返回 'teacher'，否则 'student'。

    兼容多种可能的字段名（unitid/schoolid/type/role/identity/position/jobtitle 等），
    命中任一「教师/管理员类关键词」或「单位号在教师白名单」即判为教师；若同时命中
    学生关键词则保留学生判定，避免将「学生干部/助教学生」误判为教师。
    """
    merged = {**claims, **metadata}

    # 1) 单位号白名单：超星教师单位号 1385
    for key in ("unitid", "unit_id", "unitId", "schoolid", "school_id", "schoolId", "fid", "orgid"):
        value = str(merged.get(key) or "").strip()
        if value and value in _TEACHER_UNIT_CODES:
            return "teacher"

    # 2) 身份类型字段关键词：teacher / 教师 / 管理员 / admin 等
    identity_keys = (
        "type", "usertype", "user_type", "role", "roles", "identity", "identity_type",
        "identityType", "position", "position_name", "jobtitle", "job_title", "jobTitle",
        "duty", "title", "category", "group", "usertype_name", "role_name",
    )
    hit_teacher = False
    hit_student = False
    for key in identity_keys:
        value = merged.get(key)
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        lowered = text.casefold()
        if any(keyword.casefold() in lowered for keyword in _STUDENT_IDENTITY_KEYWORDS):
            hit_student = True
        if any(keyword.casefold() in lowered for keyword in _TEACHER_IDENTITY_KEYWORDS):
            hit_teacher = True
    if hit_teacher and not hit_student:
        return "teacher"

    return "student"


_IDENTITY_LOG_KEYS = (
    "unitid", "unit_id", "unitId", "schoolid", "school_id", "schoolId", "fid", "orgid",
    "type", "usertype", "user_type", "role", "roles", "identity", "identity_type",
    "identityType", "position", "position_name", "jobtitle", "job_title", "jobTitle",
    "duty", "title", "category", "group", "usertype_name", "role_name",
    "realname", "name", "student_no", "studentno", "sno", "student_id", "studentid",
)


def _mask_value(value: str) -> str:
    """脱敏：保留首尾各 1 字符，中间以 * 覆盖；过短/空值原样返回。"""
    if not value:
        return ""
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}{'*' * max(1, len(value) - 2)}{value[-1]}"


def _identity_diagnostic(metadata: dict, claims: dict) -> dict:
    """提取身份相关字段用于脱敏日志（不记录 cxid/手机号等敏感主键）。"""
    merged = {**claims, **metadata}
    result: dict = {}
    for key in _IDENTITY_LOG_KEYS:
        value = merged.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, str):
            result[key] = _mask_value(value)
        else:
            result[key] = value
    return result


# 学生身份自动匹配：超星元数据中提取学号（字段命名不稳定，做多字段兼容）。
_STUDENT_NO_KEYS = (
    "student_no", "studentno", "sno", "student_id", "studentid", "userno",
    "user_no", "job_number", "jobnumber", "xh", "number", "code", "学号",
)


def _extract_student_no(metadata: dict, claims: dict) -> str:
    merged = {**claims, **metadata}
    for key in _STUDENT_NO_KEYS:
        value = str(merged.get(key) or "").strip()
        if value:
            return value[:64]
    return ""


def _match_roster_student(session, student_no: str, realname: str):
    """在学生名单账号中匹配超星身份：优先学号精确匹配，其次姓名唯一匹配。

    名单账号由教师导入创建（username 为学号、非 cx_ 前缀），这里只在这些账号中
    匹配，避免与超星自动创建的 cx_ 账号混淆。返回唯一匹配的 User 或 None。
    """
    if not student_no and not realname:
        return None
    # 学号精确匹配：id 或 username 均可能为学号
    if student_no:
        matched = session.scalar(
            select(User).where(
                User.role == "student",
                User.active.is_(True),
                or_(User.id == student_no, User.username == student_no),
            )
        )
        if matched is not None:
            return matched
    if not realname:
        return None
    # 姓名唯一匹配：仅限教师导入的名单账号（username 非 cx_ 前缀）
    candidates = session.scalars(
        select(User).where(
            User.role == "student",
            User.active.is_(True),
            User.name == realname,
            ~User.username.like("cx_%"),
        )
    ).all()
    if len(candidates) == 1:
        return candidates[0]
    return None


@bp.get("/auth/chaoxing")
def chaoxing_login():
    """发起超星一键登录：换取授权地址并顶层跳转。"""
    # 回跳地址必须用浏览器可见的公开域名（_app_public_base），而非 url_for(_external=True)
    # 依赖的 request.url_root：公开部署代理会把 X-Forwarded-Host 写成沙箱地址，导致
    # 回跳进沙箱而非公开域名。
    callback = f"{_app_public_base()}{url_for('auth.chaoxing_callback')}"
    # 超星是顶层跳转（浏览器整页离开预览 iframe，再跳回），中途会丢失 Cookie
    # 与 URL 里的 _sid 票据。把当前会话票据随 redirect_uri 带回，授权回跳后
    # open_session 才能复用同一会话，避免平台判定“未登录”并弹出拦截页。
    sid = current_sid()
    if sid:
        callback = f"{callback}{'&' if '?' in callback else '?'}_sid={sid}"
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
    access_token = payload.get("access_token", "")
    refresh_token = payload.get("refresh_token", "")
    if not access_token:
        current_app.logger.warning("chaoxing exchange: no access_token in session response")
        flash("登录服务返回异常，请重新登录。", "error")
        return redirect(url_for("auth.login"))

    # 用 Supabase Auth 端点校验 access_token，不以未验签 decode 作为身份依据。
    verified_user, verify_error = _verify_access_token(access_token)
    if verify_error:
        current_app.logger.warning("chaoxing access_token verification failed: %s", verify_error)
        flash("身份信息校验失败，请重新登录。", "error")
        return redirect(url_for("auth.login"))

    metadata = verified_user.get("user_metadata") or {}
    cxid = str(metadata.get("cxid") or verified_user.get("id") or "").strip()
    realname = str(metadata.get("realname") or metadata.get("name") or "").strip()
    if not cxid:
        current_app.logger.warning("chaoxing exchange: no cxid in verified user metadata")
        flash("未能获取超星身份信息，请联系管理员。", "error")
        return redirect(url_for("auth.login"))

    # 教师身份自动识别：从超星元数据判定角色（教师类身份 / 单位号 1385 → teacher）
    detected_role = _detect_chaoxing_role(metadata, verified_user)
    current_app.logger.info(
        "chaoxing identity: detected_role=%s cxid=%s fields=%s",
        detected_role,
        _mask_value(cxid),
        _identity_diagnostic(metadata, verified_user),
    )

    # 学生身份自动匹配：优先用超星元数据中的学号/姓名匹配教师已导入的名单账号，
    # 命中后复用名单账号（学号为 id/username），从而自动完成班级绑定，避免为同一
    # 学生重复创建 cx_ 账号导致名单与超星账号割裂。
    student_no = _extract_student_no(metadata, verified_user)

    # 映射本地用户：按超星 cxid 作为用户名查找，不存在则按识别到的角色创建账号
    username = f"cx_{cxid}"
    with transaction() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None and detected_role == "student":
            matched = _match_roster_student(db, student_no, realname)
            if matched is not None:
                user = matched
                # 建立超星绑定关系，后续可直接凭 cxid 定位该名单账号
                if user.chaoxing_cxid != cxid:
                    user.chaoxing_cxid = cxid
        if user is None:
            user = User(
                id=f"cx_{cxid}"[:64],
                username=username,
                name=realname or f"超星用户{cxid[-4:]}",
                role=detected_role,
                password_hash="!chaoxing-oauth-no-password!",
                active=True,
                must_change_password=False,
                chaoxing_cxid=cxid,
            )
            db.add(user)
        elif not user.active:
            flash("账号已被停用，请联系管理员。", "error")
            return redirect(url_for("auth.login"))
        else:
            if realname and user.name != realname:
                user.name = realname
            if not user.chaoxing_cxid:
                user.chaoxing_cxid = cxid
            # 存量账号若此前被识别为学生、而超星元数据已确认为教师，自动升级角色
            if user.role == "student" and detected_role == "teacher":
                user.role = "teacher"
        # 超星 SSO 学生默认加入系统课程：确保登录后能正常选关、进入实验。
        # 仅当该学生尚未加入任何课程时自动补一条选课记录，避免与教师手动导入冲突。
        if user.role == "student":
            existing = db.scalar(select(Enrollment).where(Enrollment.student_id == user.id))
            if existing is None:
                default_course = db.scalar(select(Course).order_by(Course.created_at, Course.id))
                if default_course is not None:
                    db.add(Enrollment(course_id=default_course.id, student_id=user.id))
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
    # access_token / refresh_token 只保存在服务端 app_sessions 表，
    # 不进入 URL 的 _sid、不写入浏览器可读 cookie、不输出到日志。
    session["cx_access_token"] = access_token
    session["cx_refresh_token"] = refresh_token
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
