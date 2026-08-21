from __future__ import annotations

import os
import secrets
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, has_request_context, abort, request, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix

from .db import init_database


def _on_coze_platform() -> bool:
    """True when running inside the Coze platform.

    Detection is layered: (1) platform-injected env vars, (2) the FaaS
    deployment path /opt/bytefaas/. Either signal is sufficient.
    """
    if os.getenv("PGDATABASE_URL") or os.getenv("COZE_SUPABASE_URL"):
        return True
    return "/opt/bytefaas/" in str(Path(__file__).resolve())


def _in_coze_sandbox() -> bool:
    """The dev sandbox preview is also embedded as a cross-origin iframe."""
    return bool(os.getenv("COZE_DEVBOX_ENV") or os.getenv("COZE_WORKSPACE_PATH"))


class _PreviewSessionInterface(SecureCookieSessionInterface):
    """Session cookie that survives cross-origin preview iframes.

    The Coze platform preview is a cross-origin iframe; SameSite=Lax silently
    drops the session cookie on iframe subrequests, breaking CSRF and auth.
    We emit SameSite=None; Secure whenever the request is HTTPS (detected via
    X-Forwarded-Proto) OR platform env vars are present (the user-facing
    connection is always HTTPS even if the internal hop is HTTP). Over plain
    HTTP local dev we keep the safer Lax default.
    """

    def get_cookie_secure(self, app):
        if (has_request_context() and request.is_secure) or _on_coze_platform() or _in_coze_sandbox():
            return True
        return app.config.get("SESSION_COOKIE_SECURE", False)

    def get_cookie_samesite(self, app):
        if (has_request_context() and request.is_secure) or _on_coze_platform() or _in_coze_sandbox():
            return "None"
        return app.config.get("SESSION_COOKIE_SAMESITE", "Lax")


def create_app(test_config: dict | None = None) -> Flask:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env.local", override=False)
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    env = os.getenv("APP_ENV", "development")
    _data_dir = os.getenv("DATA_DIR") or (
        "/tmp/whu-quantum-lab" if _on_coze_platform() else str(root / "runtime")
    )
    app.config.update(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-secret-change-me"),
        APP_ENV=env,
        DEBUG=env == "development",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=env == "production",
        MAX_CONTENT_LENGTH=max(20, int(os.getenv("MAX_UPLOAD_MB", "500"))) * 1024 * 1024,
        DATA_DIR=_data_dir,
        DATABASE_URL=os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL") or f"sqlite:///{Path(_data_dir) / 'platform.db'}",
        PYODIDE_BASE_URL=os.getenv("PYODIDE_BASE_URL", "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/"),
    )
    if test_config:
        app.config.update(test_config)
    if app.config["APP_ENV"] == "production" and not app.config["DATABASE_URL"].startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Production requires PostgreSQL DATABASE_URL")
    try:
        Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    except OSError:
        app.config["DATA_DIR"] = "/tmp/whu-quantum-lab"
        app.config["DATABASE_URL"] = (
            os.getenv("DATABASE_URL") or os.getenv("PGDATABASE_URL")
            or f"sqlite:///{Path(app.config['DATA_DIR']) / 'platform.db'}"
        )
        Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    _url = app.config["DATABASE_URL"]
    if _url.startswith("postgresql://"):
        app.config["DATABASE_URL"] = "postgresql+psycopg://" + _url[len("postgresql://"):]
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)
    app.session_interface = _PreviewSessionInterface()
    init_database(app)
    app.extensions["login_attempts"] = {}
    app.extensions["login_attempts_lock"] = Lock()

    from .blueprints.api import bp as api_bp
    from .blueprints.auth import bp as auth_bp
    from .blueprints.student import bp as student_bp
    from .blueprints.teacher import bp as teacher_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(api_bp)

    def csrf_token() -> str:
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": csrf_token}

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
        is_prod = app.config["APP_ENV"] == "production"
        frame_ancestors = "'none'" if is_prod else "*"
        if is_prod:
            response.headers["X-Frame-Options"] = "DENY"
        else:
            response.headers.pop("X-Frame-Options", None)
        response.headers["X-Content-Type-Options"] = "nosniff"
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
        if is_prod:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    from auth_service import password_hash
    from .services.experiments import seed_defaults
    with app.app_context():
        seed_defaults(password_hash)
    return app
