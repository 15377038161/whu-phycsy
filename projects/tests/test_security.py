from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from platform_app import create_app
from platform_app.db import db_session, transaction
from platform_app.models import AuditEvent, FileAsset
from platform_app.services.files import STUDENT_ATTACHMENT_UPLOADS, save_upload


@pytest.fixture
def security_app(tmp_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "security-test-secret",
        "DATA_DIR": str(tmp_path / "data"),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'security.db'}",
    })


def test_csrf_rejects_missing_token_and_accepts_session_token(security_app, raw_client_open):
    client = security_app.test_client()
    client.get("/login")
    missing = raw_client_open(
        client,
        "/login",
        method="POST",
        data={"username": "admin", "password": "admin123"},
    )
    assert missing.status_code == 400
    with client.session_transaction() as test_session:
        token = test_session["_csrf_token"]
    valid = raw_client_open(
        client,
        "/login",
        method="POST",
        data={"username": "admin", "password": "admin123", "csrf_token": token},
    )
    assert valid.status_code == 302


def test_every_post_form_declares_csrf_field():
    template_dir = Path(__file__).resolve().parents[1] / "templates"
    post_form = re.compile(r'<form\b(?=[^>]*method=["\']post["\'])[^>]*>(.*?)</form>', re.I | re.S)
    missing = []
    for template in template_dir.glob("*.html"):
        for match in post_form.finditer(template.read_text(encoding="utf-8")):
            if not re.search(r'name=["\']csrf_token["\']', match.group(1), re.I):
                missing.append(template.name)
    assert not missing


def test_upload_policy_rejects_svg(security_app):
    upload = FileStorage(
        stream=io.BytesIO(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
        filename="payload.svg",
        content_type="image/svg+xml",
    )
    with security_app.app_context(), pytest.raises(ValueError, match="不支持"):
        save_upload(upload, STUDENT_ATTACHMENT_UPLOADS)


def test_media_uses_nosniff_and_downloads_non_inline_image(security_app):
    client = security_app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin123"})
    payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    digest = "a" * 64
    relative = Path("files") / "aa" / f"{digest}.svg"
    target = Path(security_app.config["DATA_DIR"]) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    with security_app.app_context(), transaction() as database:
        database.add(FileAsset(
            sha256=digest,
            object_key=relative.as_posix(),
            original_name="payload.svg",
            content_type="image/svg+xml",
            size=len(payload),
        ))
    response = client.get(f"/media/{digest}")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Disposition"].startswith("attachment;")


def test_login_locks_after_five_failures_and_audits(security_app):
    client = security_app.test_client()
    for _ in range(5):
        assert client.post("/login", data={"username": "admin", "password": "wrong"}).status_code == 200
    locked = client.post("/login", data={"username": "admin", "password": "admin123"})
    assert locked.status_code == 429
    assert "尝试过于频繁" in locked.get_data(as_text=True)
    with security_app.app_context():
        actions = [event.action for event in db_session().query(AuditEvent).all()]
    assert actions.count("login.fail") == 5
    assert actions.count("login.locked") == 1


def test_security_headers_and_production_hsts(security_app):
    client = security_app.test_client()
    response = client.get("/login")
    # Development mode allows the preview platform to embed the app in an iframe.
    assert "X-Frame-Options" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors *" in response.headers["Content-Security-Policy"]
    security_app.config["APP_ENV"] = "production"
    prod_response = client.get("/login")
    assert prod_response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in prod_response.headers["Content-Security-Policy"]
    assert prod_response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
