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
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)
    setup_logging(app)
    app.before_request(before_request_log)
    app.after_request(after_request_log)
    app.teardown_request(teardown_request_log)
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
        response.headers["X-Frame-Options"] = "DENY"
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
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
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
