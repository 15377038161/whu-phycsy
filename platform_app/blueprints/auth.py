from __future__ import annotations

import os
import time
from functools import wraps
from urllib.parse import urlsplit

import httpx
from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import select
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


def _public_redirect(endpoint: str, **values):
    """生成同源绝对 URL 重定向，避免平台网关把根相对 Location 重写为沙箱前缀。

    仅用于应用内部路由；外站跳转必须直接使用 redirect(authorize_url) 等。"""
    return redirect(f"{_app_public_base()}{url_for(endpoint, **values)}")


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
                return _public_redirect("auth.login")
            if user.must_change_password and request.endpoint != "auth.first_password":
                return _public_redirect("auth.first_password")
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
        return _public_redirect("teacher.dashboard" if user.role == "teacher" else "student.home")
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
                return _public_redirect("auth.first_password")
            return _public_redirect("teacher.dashboard" if user.role == "teacher" else "student.home")
        attempts = _record_login_failure(key)
        _audit_login("login.fail", username, user, attempts)
        flash("账号或密码错误。", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return _public_redirect("auth.login")


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


def _is_sandbox_or_internal_domain(base: str) -> bool:
    """识别沙箱/内部/本地地址；合法公开域名返回 False。

    作为 urlsplit 结构校验之外的策略层：即使形式合法，沙箱/内部/本地地址
    也不得作为浏览器可见的 OAuth 回跳域名。
    """
    lowered = base.casefold()
    return any(
        marker in lowered
        for marker in ("sandbox", "internal", "/sandboxes/", "localhost", "127.0.0.1", ":5000", ":8080", ":5173")
    )


def _is_valid_public_base(base: str) -> tuple[bool, str]:
    """使用 urlsplit 做完整结构校验公开 base URL。

    要求：https 协议、有 hostname、无 userinfo、无 path/query/fragment、
    端口要么省略（默认 443）要么显式 443。不满足时返回 (False, reason)。
    """
    parsed = urlsplit(base)
    if parsed.scheme != "https":
        return False, "必须使用 https 协议"
    if not parsed.hostname:
        return False, "缺少 hostname"
    if parsed.username is not None or parsed.password is not None:
        return False, "不允许 userinfo"
    if parsed.path not in ("", "/"):
        return False, "不允许 path"
    if parsed.query or parsed.fragment:
        return False, "不允许 query 或 fragment"
    if parsed.port is not None and parsed.port != 443:
        return False, "异常端口"
    if _is_sandbox_or_internal_domain(base):
        return False, "沙箱/内部/本地地址不可作为公开域名"
    return True, ""


def _resolve_app_public_base(
    *,
    fail_closed: bool = False,
    allow_local: bool = False,
    request_url_root: str = "",
) -> str:
    """解析应用对外公开 base URL（用于超星 OAuth 回跳 redirect_uri，浏览器可见）。

    与认证代理地址严格区分：这里必须指向用户浏览器可访问的域名，而非后端
    内部地址。公开部署的代理会把 X-Forwarded-Host 写成内部沙箱地址，导致
    url_for(_external=True) 生成沙箱回跳地址，浏览器跳回沙箱而非公开域名。

    解析优先级：
      1. APP_PUBLIC_BASE_URL  —— 显式配置（公开部署必填）
      2. CODER_PROJECTS_DOMAIN —— 平台注入的对外访问域名
      3. request.url_root      —— 仅本地开发/测试兜底（需 allow_local=True）

    参数：
      fail_closed: 为 True 时，缺失或非法公开地址直接抛 RuntimeError（用于
                   启动检查，让错误配置在启动阶段明确失败）。
      allow_local: 为 True 时，允许回退到 request.url_root；否则本地地址也被拒绝。
      request_url_root: 可选的外部传入 request.url_root，避免在启动上下文调用 request。
    """
    base = os.getenv("APP_PUBLIC_BASE_URL", "").strip()
    source = "APP_PUBLIC_BASE_URL"
    if not base:
        base = os.getenv("CODER_PROJECTS_DOMAIN", "").strip()
        source = "CODER_PROJECTS_DOMAIN"
    if base:
        # 没有 scheme 时按公开部署约定补 https，随后做完整 urlsplit 校验。
        if "://" not in base:
            base = f"https://{base}"
        valid, reason = _is_valid_public_base(base)
        if not valid:
            raise RuntimeError(
                f"{source} 无效，无法构造公开 OAuth 回跳地址: {reason}: {base}"
            )
        return base.rstrip("/")
    # 未配置任何公开地址时，仅允许本地开发/测试回退到 request.url_root。
    if fail_closed:
        raise RuntimeError(
            "APP_PUBLIC_BASE_URL 未配置：公开部署必须显式设置合法公开域名。"
        )
    if allow_local and request_url_root:
        return request_url_root.rstrip("/")
    raise RuntimeError(
        "APP_PUBLIC_BASE_URL 与 CODER_PROJECTS_DOMAIN 均未配置，无法构造公开 OAuth 回跳地址。"
    )


def _app_public_base() -> str:
    """内部重定向用公开 base URL：优先使用启动时缓存值，保证非 OAuth 页面可用。"""
    configured = current_app.config.get("APP_PUBLIC_BASE_URL", "")
    if configured:
        return configured.rstrip("/")
    return _resolve_app_public_base(allow_local=True, request_url_root=request.url_root.rstrip("/"))


def _strict_app_public_base() -> str:
    """OAuth 回跳用公开 base URL：每次重新严格解析环境变量，非法配置直接失败。

    开发/预览无配置时允许回退到 request.url_root；生产环境无配置或配置非法均失败。
    """
    env = current_app.config.get("APP_ENV", "development")
    return _resolve_app_public_base(
        fail_closed=(env == "production"),
        allow_local=(env != "production"),
        request_url_root=request.url_root.rstrip("/"),
    )


def check_app_public_base_at_startup(*, env: str) -> str:
    """启动时检查公开 base URL 配置；生产必须显式合法，预览/开发允许本地兜底。

    返回解析后的 base URL 供应用缓存到 app.config["APP_PUBLIC_BASE_URL"]。
    预览/沙箱场景下 CODER_PROJECTS_DOMAIN 常为内部地址，这里捕获异常并回退到
    localhost，保证非 OAuth 页面仍可正常启动和预览；OAuth 回跳在请求时再严格校验。
    """
    # 生产环境必须显式配置合法公开域名，禁止依赖 request.url_root 或沙箱地址
    if env == "production":
        return _resolve_app_public_base(fail_closed=True)
    # 预览/开发/测试：允许本地地址兜底，已配置但非法的地址不阻塞启动
    try:
        return _resolve_app_public_base(fail_closed=False, allow_local=True, request_url_root="http://localhost:5000")
    except RuntimeError:
        return "http://localhost:5000"


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


def _detect_chaoxing_role(metadata: dict, claims: dict) -> str:
    """超星 SSO 默认角色固定为 'student'。

    教师身份仅由本地数据库的合法授权记录决定（users.role='teacher' 且 active=True）。
    user_metadata、单位号、自由关键词均不可用于授予或升级教师角色，防止用户通过
    可编辑元数据越权获得教师权限。后续若引入官方不可用户编辑的 app_metadata 角色
    源，需有明确契约证据并单独评审后再扩展此处。
    """
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


@bp.get("/auth/chaoxing")
def chaoxing_login():
    """发起超星一键登录：换取授权地址并顶层跳转。"""
    # 回跳地址必须用浏览器可见的公开域名（_strict_app_public_base），而非 url_for(_external=True)
    # 依赖的 request.url_root：公开部署代理会把 X-Forwarded-Host 写成沙箱地址，导致
    # 回跳进沙箱而非公开域名。OAuth 场景必须每次严格解析，不能直接使用内部重定向缓存。
    callback = f"{_strict_app_public_base()}{url_for('auth.chaoxing_callback')}"
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
        return _public_redirect("auth.login")
    if resp.status_code != 200:
        current_app.logger.warning("chaoxing authorize-url -> %s", resp.status_code)
        flash("超星登录服务暂时不可用，请稍后再试或使用账号密码登录。", "error")
        return _public_redirect("auth.login")
    authorize_url = (resp.json() or {}).get("authorizeUrl")
    if not authorize_url:
        flash("超星登录服务返回异常，请稍后再试。", "error")
        return _public_redirect("auth.login")
    return redirect(authorize_url)


@bp.get("/auth/chaoxing/callback")
def chaoxing_callback():
    """超星授权回跳：code 换取身份，映射本地用户并建立会话。"""
    code = request.args.get("code", "").strip()
    if not code:
        flash("超星授权已取消或已过期，请重新登录。", "error")
        return _public_redirect("auth.login")

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
        return _public_redirect("auth.login")
    if resp.status_code != 200:
        current_app.logger.warning("chaoxing exchange -> %s", resp.status_code)
        flash("登录链接已失效，请重新登录。", "error")
        return _public_redirect("auth.login")

    payload = resp.json() or {}
    access_token = payload.get("access_token", "")
    refresh_token = payload.get("refresh_token", "")
    if not access_token:
        current_app.logger.warning("chaoxing exchange: no access_token in session response")
        flash("登录服务返回异常，请重新登录。", "error")
        return _public_redirect("auth.login")

    # 用 Supabase Auth 端点校验 access_token，不以未验签 decode 作为身份依据。
    verified_user, verify_error = _verify_access_token(access_token)
    if verify_error:
        current_app.logger.warning("chaoxing access_token verification failed: %s", verify_error)
        flash("身份信息校验失败，请重新登录。", "error")
        return _public_redirect("auth.login")

    # 身份键只从 Supabase Auth 已验证顶层获取，不采用用户可编辑的 user_metadata。
    # 后续若平台提供 app_metadata 等不可用户编辑的官方契约字段，可在此白名单扩展。
    identity_key = str(verified_user.get("id") or verified_user.get("sub") or "").strip()
    metadata = verified_user.get("user_metadata") or {}
    realname = str(metadata.get("realname") or metadata.get("name") or "").strip()
    # 空身份键：强制清理所有会话
    if not identity_key:
        current_app.logger.warning("chaoxing exchange: no verified identity in user")
        session.clear()
        flash("未能获取可信身份信息，请联系管理员绑定账号后再登录。", "error")
        return _public_redirect("auth.login")

    # 超星 SSO 默认按学生处理；教师身份只能来自本地已授权记录，不由元数据决定。
    sso_role = _detect_chaoxing_role(metadata, verified_user)
    current_app.logger.info(
        "chaoxing identity: sso_role=%s identity=%s fields=%s",
        sso_role,
        _mask_value(identity_key),
        _identity_diagnostic(metadata, verified_user),
    )

    # 映射本地用户：仅允许已存在的 cx_<identity> 账号或教师预授权绑定的 chaoxing_cxid。
    # 禁止通过 user_metadata 中的姓名/学号匹配、重绑他人名单用户，防止账号接管。
    username = f"cx_{identity_key}"
    db = db_session()
    # 统一查询所有匹配项，避免 OR 查询在不同数据库/执行计划下返回随机结果。
    username_matches = db.scalars(select(User).where(User.username == username)).all()
    cxid_matches = db.scalars(select(User).where(User.chaoxing_cxid == identity_key)).all()
    all_matches = list({u.id: u for u in list(username_matches) + list(cxid_matches)}.values())

    # 多候选匹配：拒绝冲突绑定
    if len(all_matches) > 1:
        session.clear()
        flash("该超星身份存在多个平台账号绑定冲突，请联系管理员处理。", "error")
        return _public_redirect("auth.login")

    # 唯一候选匹配：检查绑定一致性
    user = all_matches[0] if all_matches else None
    if user is not None:
        # 拒绝重绑：已有非空绑定且与当前身份不一致
        if user.chaoxing_cxid and user.chaoxing_cxid != identity_key:
            session.clear()
            flash("该账号已绑定其他超星身份，请联系管理员处理。", "error")
            return _public_redirect("auth.login")
        # 禁止用元数据覆盖教师导入的姓名（非 cx_ 用户名为教师/管理员导入的名单账号）
        if not user.username.startswith("cx_") and realname and user.name != realname:
            realname = user.name

    # 教师身份仅由本地数据库的合法授权记录决定；超星 SSO 不会创建或升级教师。
    if user is not None and user.role == "teacher" and user.active:
        final_role = "teacher"
    else:
        final_role = "student"

    # 账号停用时，先清除可能存在的旧登录会话与令牌，再拒绝。
    if user is not None and not user.active:
        session.clear()
        flash("账号已被停用，请联系管理员。", "error")
        return _public_redirect("auth.login")

    # 学生必须已有合法本地账号及 enrollment；无预绑定账号时 fail closed。
    if user is None:
        session.clear()
        flash(
            "该超星账号尚未绑定实验平台账号，请联系任课教师或管理员导入/绑定后再登录。",
            "error",
        )
        return _public_redirect("auth.login")

    if final_role == "student" and (
        db.scalar(select(Enrollment).where(Enrollment.student_id == user.id)) is None
    ):
        session.clear()
        flash("你尚未被加入任何课程，请联系任课教师导入名单后再登录。", "error")
        return _public_redirect("auth.login")

    with transaction() as db:
        if realname and user.name != realname:
            user.name = realname
        if user.chaoxing_cxid != identity_key:
            user.chaoxing_cxid = identity_key
        db.add(AuditEvent(
            actor_id=user.id,
            action="login.chaoxing",
            entity_type="user",
            entity_id=user.id,
            detail={"identity": identity_key[:64], "ip": request.remote_addr or "unknown"},
        ))

    session.clear()
    session["user_id"] = user.id
    session["chaoxing_cxid"] = identity_key
    # access_token / refresh_token 只保存在服务端 app_sessions 表，
    # 不进入 URL 的 _sid、不写入浏览器可读 cookie、不输出到日志。
    session["cx_access_token"] = access_token
    session["cx_refresh_token"] = refresh_token
    session.modified = True
    return _public_redirect("teacher.dashboard" if user.role == "teacher" else "student.home")


@bp.post("/account/password")
def account_password():
    user = current_user()
    if not user:
        return _public_redirect("auth.login")
    try:
        change_password(user.id, request.form.get("current_password", ""), request.form.get("new_password", ""), request.form.get("confirm_password", ""))
        session.clear()
        flash("密码已更新，请使用新密码继续登录。", "success")
        return _public_redirect("auth.login")
    except ValueError as exc:
        flash(str(exc), "error")
        return _public_redirect("teacher.dashboard" if user.role == "teacher" else "student.home")


@bp.route("/account/first-password", methods=["GET", "POST"])
def first_password():
    user = current_user()
    if not user:
        return _public_redirect("auth.login")
    if not user.must_change_password:
        return _public_redirect("teacher.dashboard" if user.role == "teacher" else "student.home")
    if request.method == "POST":
        try:
            change_password(
                user.id,
                request.form.get("current_password", ""),
                request.form.get("new_password", ""),
                request.form.get("confirm_password", ""),
            )
            flash("新密码设置成功，欢迎进入实验平台。", "success")
            return _public_redirect("student.home")
        except ValueError as exc:
            flash(str(exc), "error")
    return render_template("first_password.html", user=user)


@bp.get("/media/<sha256>")
def media(sha256):
    if not current_user():
        return _public_redirect("auth.login")
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
