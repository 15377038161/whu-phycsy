from __future__ import annotations

import os
import secrets
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, abort, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from .db import init_database
from .logging_utils import after_request_log, before_request_log, setup_logging, teardown_request_log


def _load_env_files() -> str:
    """Load dotenv files for the current APP_ENV.

    Platform-injected environment variables always take precedence (override=False),
    so operator/CI values are never shadowed by a checked-in file. Load order:
    .env <- .env.<APP_ENV> (preview/production) <- .env.local (local overrides).
    """
    env = os.getenv("APP_ENV", "development")
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env", override=False)
    if env and env != "development":
        load_dotenv(root / f".env.{env}", override=False)
    load_dotenv(root / ".env.local", override=False)
    return env


class _SandboxProxyPrefixStripper:
    """Strip the platform sandbox proxy prefix (/sandboxes/<id>/proxy/<port>) from PATH_INFO and SCRIPT_NAME.

    The platform preview/public proxy forwards requests without stripping its routing
    prefix, so Flask sees /sandboxes/.../proxy/5173/login and 404s. It may also set
    SCRIPT_NAME to the same prefix, which causes url_for()/redirect Location URLs to
    leak /sandboxes/.../proxy/<port> into browser-visible addresses. This middleware
    rewrites PATH_INFO and resets SCRIPT_NAME for the sandbox prefix so all browser-
    facing URLs stay root-relative on the subdomain.
    """

    def __init__(self, app):
        import re

        self.app = app
        self._prefix_re = re.compile(r"^/sandboxes/[^/]+/proxy/\d+")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        match = self._prefix_re.match(path)
        if match:
            environ["PATH_INFO"] = path[match.end():] or "/"
        script_name = environ.get("SCRIPT_NAME", "")
        if self._prefix_re.match(script_name):
            environ["SCRIPT_NAME"] = ""
        return self.app(environ, start_response)


def _is_unsafe_frame_origin(origin: str) -> bool:
    """Reject sandbox/internal/local origins for frame embedding."""
    lowered = origin.casefold()
    return any(
        marker in lowered
        for marker in ("sandbox", "internal", "/sandboxes/", "localhost", "127.0.0.1", ":5000", ":8080", ":5173")
    )


def _platform_frame_ancestors() -> list[str]:
    """Return trusted parent origins allowed to embed this app in an iframe.

    Reads PLATFORM_FRAME_ANCESTORS (comma-separated origins) first, then falls
    back to CODER_PROJECTS_DOMAIN. Only public/production-looking origins are
    kept; sandbox/internal/local addresses are rejected so the app does not leak
    into untrusted preview contexts. An empty list means default-deny
    (X-Frame-Options: DENY, frame-ancestors 'none').
    """
    raw = os.getenv("PLATFORM_FRAME_ANCESTORS", "").strip()
    if not raw:
        domain = os.getenv("CODER_PROJECTS_DOMAIN", "").strip()
        if domain:
            raw = domain if "://" in domain else f"https://{domain}"
    ancestors: list[str] = []
    for item in raw.split(","):
        origin = item.strip()
        if not origin:
            continue
        if "://" not in origin:
            origin = f"https://{origin}"
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not parsed.netloc:
            continue
        if _is_unsafe_frame_origin(origin):
            continue
        ancestors.append(f"{parsed.scheme}://{parsed.netloc}")
    return ancestors


def create_app(test_config: dict | None = None) -> Flask:
    root = Path(__file__).resolve().parent.parent
    env = _load_env_files()
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    env = os.getenv("APP_ENV", "development")
    app.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-secret-change-me"),
        APP_ENV=env,
        DEBUG=env == "development",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env == "production",
        MAX_CONTENT_LENGTH=max(20, int(os.getenv("MAX_UPLOAD_MB", "500"))) * 1024 * 1024,
        DATA_DIR=os.getenv("DATA_DIR", str(root / "runtime")),
        DATABASE_URL=os.getenv("DATABASE_URL", f"sqlite:///{root / 'runtime' / 'platform.db'}"),
        PYODIDE_BASE_URL=os.getenv("PYODIDE_BASE_URL", "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/"),
    )
    if test_config:
        app.config.update(test_config)
    if app.config["APP_ENV"] == "production" and not app.config["DATABASE_URL"].startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Production requires PostgreSQL DATABASE_URL")
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    # 启动阶段明确检查公开基址配置；错误配置在这里 fail closed，避免普通业务请求在 after_request 中抛异常。
    from .blueprints.auth import check_app_public_base_at_startup
    app.config["APP_PUBLIC_BASE_URL"] = check_app_public_base_at_startup(env=app.config["APP_ENV"])
    # 只信任 X-Forwarded-Proto/Host（用于正确生成 https scheme 与外部 Host），
    # 绝不能启用 x_prefix：平台预览网关会在 X-Forwarded-Prefix 里带上内部路由
    # 前缀 /sandboxes/<id>/proxy/<port>，x_prefix=1 会把它注入 SCRIPT_NAME，
    # 导致 url_for() 生成的重定向 Location 泄露该内部前缀，浏览器跟随跳转后
    # 网关直接拦截，预览表现为「拒绝连接」。
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=0)
    app.wsgi_app = _SandboxProxyPrefixStripper(app.wsgi_app)
    setup_logging(app)
    app.before_request(before_request_log)
    app.after_request(after_request_log)
    app.teardown_request(teardown_request_log)
    init_database(app)
    app.extensions["login_attempts"] = {}
    app.extensions["login_attempts_lock"] = Lock()

    from .health_monitor import attach_monitor

    attach_monitor(app)

    from .blueprints.api import bp as api_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.student import bp as student_bp
    from .blueprints.teacher import bp as teacher_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(api_bp)

    from .session_store import TicketSessionInterface, current_sid

    app.session_interface = TicketSessionInterface()

    def csrf_token() -> str:
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
            session.modified = True
        return token

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": csrf_token, "_sid": current_sid()}

    def _default_port(scheme: str) -> int | None:
        return 443 if scheme == "https" else 80 if scheme == "http" else None

    def _is_app_origin(location: str, public_base: str) -> bool:
        """严格校验 location 与 public_base 同源（scheme/hostname/port），拒绝 userinfo/外站/协议相对 URL。"""
        parsed = urlsplit(location)
        if parsed.username is not None or parsed.password is not None:
            return False
        if not parsed.scheme or not parsed.netloc:
            return False
        base = urlsplit(public_base)
        if parsed.scheme != base.scheme:
            return False
        if (parsed.hostname or "").casefold() != (base.hostname or "").casefold():
            return False
        if (parsed.port or _default_port(parsed.scheme)) != (base.port or _default_port(base.scheme)):
            return False
        return True

    @app.after_request
    def propagate_sid(response):
        """Keep the session ticket alive across redirects and page URLs.

        The proxy strips cookies, so the _sid ticket must travel in the URL.
        Redirects get the ticket appended to Location; page propagation for
        links/forms is handled client-side by static/sid.js.

        安全：仅对根相对 URL 或与 APP_PUBLIC_BASE_URL 同源的绝对 URL 附加 _sid；
        外站 OAuth 等绝对跳转不附加，防止票据泄露。

        注意：普通业务请求（非重定向）直接返回，不在 after_request 中解析公开基址，
        避免 OAuth 基址配置错误污染正常页面响应。
        """
        sid = current_sid()
        if not sid or response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location", "")
        if not location or location.startswith("//") or "_sid=" in location:
            return response
        # 使用启动时解析并缓存的公开基址，避免在请求周期再次解析并抛异常。
        public_base = app.config.get("APP_PUBLIC_BASE_URL", "")
        root_relative = location.startswith("/")
        if root_relative or (public_base and _is_app_origin(location, public_base)):
            sep = "&" if "?" in location else "?"
            response.headers["Location"] = f"{location}{sep}_sid={sid}"
        return response

    @app.before_request
    def protect_state_changes():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if request.path in {"/health", "/ready"}:
            return None
        expected = session.get("_csrf_token")
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        if not expected or not supplied or not compare_digest(str(expected), str(supplied)):
            abort(400, description="CSRF token missing or invalid")
        return None

    @app.after_request
    def add_security_headers(response):
        pyodide_url = urlsplit(app.config["PYODIDE_BASE_URL"])
        pyodide_origin = f"{pyodide_url.scheme}://{pyodide_url.netloc}" if pyodide_url.scheme in {"http", "https"} and pyodide_url.netloc else ""
        external = f" {pyodide_origin}" if pyodide_origin else ""
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 平台原生嵌入契约：只有明确配置了可信父源（CODER_PROJECTS_DOMAIN 或
        # PLATFORM_FRAME_ANCESTORS）时才授权 frame-ancestors；否则默认严格拒绝
        # 任何 iframe 嵌入（X-Frame-Options: DENY + frame-ancestors 'none'）。
        # 平台环境中 X-Frame-Options 仍保持 SAMEORIGIN，由 CSP frame-ancestors 做最终授权。
        platform_ancestors = _platform_frame_ancestors()
        if platform_ancestors:
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            frame_ancestors = " ".join(["'self'", *platform_ancestors])
        else:
            response.headers["X-Frame-Options"] = "DENY"
            frame_ancestors = "'none'"

        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            f"script-src 'self' 'wasm-unsafe-eval'{external}; "
            "font-src 'self' data:; "
            "media-src 'self' blob:; "
            f"connect-src 'self'{external}; "
            f"worker-src 'self' blob:{external}; "
            f"frame-ancestors {frame_ancestors}; base-uri 'self'; form-action 'self'"
        )
        # 动态页面/重定向禁止缓存：平台代理会缓存 302，导致会话票据过期后仍跳旧地址
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = "no-store"
        if app.config["APP_ENV"] == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers.pop("Server", None)
        return response

    from auth_service import password_hash
    from .services.experiments import seed_defaults
    with app.app_context():
        seed_defaults(password_hash)
    return app
