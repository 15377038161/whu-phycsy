"""Runtime self-attestation endpoint security tests.

Coverage:
  1. /api/diag/runtime requires login and CSRF protection.
  2. Response contains only strict allow-list fields; no secrets, paths,
     hostnames, URLs, JWT claims, user lists, row counts, or raw errors.
  3. backend_type reflects the actually loaded code path.
  4. ai_source enumerates native/legacy/unconfigured without exposing values.
  5. enrollment_status resolves the caller's own users.id mapping first, then
     filters enrollments by student_id and verifies the returned student_id.
  6. manifest output exposes actual loaded/manifest SHA-256 by logical label.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from platform_app.models import User


AUTH_UID = "auth-uuid-12345"
BUSINESS_STUDENT_ID = "biz_student_001"


class _FakeResponse:
    def __init__(self, status_code: int, json_data):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


@pytest.fixture
def diag_app(tmp_path, monkeypatch):
    from platform_app import create_app

    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.edu.cn")
    monkeypatch.setenv("APP_ENV", "preview")
    monkeypatch.delenv("CODER_PROJECTS_DOMAIN", raising=False)
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "diag-runtime-secret",
            "DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'runtime.db'}",
        }
    )


@pytest.fixture
def sample_user(diag_app):
    from platform_app.db import transaction

    with diag_app.app_context():
        with transaction() as db:
            user = User(
                id="cx_123456789",
                username="cx_123456789",
                name="测试用户",
                role="student",
                password_hash="!chaoxing-oauth-no-password!",
                active=True,
                chaoxing_cxid="123456789",
            )
            db.add(user)
    return user


def _login_client(client, user_id: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def _patch_valid_token(monkeypatch, auth_uid: str = AUTH_UID):
    """Bypass the live Supabase Auth call by returning a deterministic user."""
    monkeypatch.setattr(
        "platform_app.blueprints.api._verify_access_token",
        lambda token: ({"id": auth_uid}, None),
    )


def _fake_data_api_request(users_rows, enrollments_rows):
    """Return responses for /users and /enrollments PostgREST calls."""

    def request(method: str, url: str, **kwargs):
        parsed = urlparse(url)
        path = parsed.path + "?" + parsed.query if parsed.query else parsed.path
        if "/rest/v1/users" in path:
            return _FakeResponse(200, users_rows)
        if "/rest/v1/enrollments" in path:
            return _FakeResponse(200, enrollments_rows)
        return _FakeResponse(404, {"message": "not found"})

    return request


def _manifest_for_project(project_root: Path) -> dict:
    watched = [
        "ai_service.py",
        "platform_app/services/progress.py",
        "platform_app/blueprints/student.py",
        "platform_app/blueprints/api.py",
        "scripts/start.sh",
    ]
    return {
        "head": "test-head-abc123",
        "files": {
            rel: hashlib.sha256((project_root / rel).read_bytes()).hexdigest()
            for rel in watched
        },
    }


def _assert_allowlist_only(resp, expected_keys):
    assert resp.status_code == 200
    data = resp.json
    assert set(data.keys()) == set(expected_keys)
    text = resp.get_data(as_text=True)
    assert "secret-access-token" not in text
    assert "secret-refresh-token" not in text
    assert "fake-anon-key" not in text
    assert "fake-api-key" not in text
    assert "cx_123456789" not in text
    assert "123456789" not in text
    assert "测试用户" not in text
    assert AUTH_UID not in text
    assert BUSINESS_STUDENT_ID not in text


# Allow-list keys exposed by runtime_diagnostic_payload().
_ALLOWLIST_KEYS = [
    "app_env",
    "backend_type",
    "ai_native_vars_present",
    "ai_source",
    "enrollment_status",
    "has_visible_enrollment",
    "manifest_head",
    "manifest_match",
    "loaded_sha256",
    "manifest_sha256",
    "module_hashes_match",
]


def test_diag_runtime_rejects_anonymous(diag_app):
    with diag_app.test_client() as client:
        resp = client.post("/api/diag/runtime")
    assert resp.status_code == 401
    assert resp.json["diag_status"] == "unauthenticated"


def test_diag_runtime_rejects_missing_csrf(diag_app, sample_user, raw_client_open):
    """Global protect_state_changes rejects POST without valid CSRF token."""
    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["_csrf_token"] = "real-csrf-token"
        # Use raw_client_open to bypass the global test CSRF injector.
        resp = raw_client_open(
            client,
            "/api/diag/runtime",
            method="POST",
            headers={"X-CSRFToken": "wrong-token"},
        )
    assert resp.status_code == 400
    assert "CSRF token missing or invalid" in resp.get_data(as_text=True)


def test_diag_runtime_returns_allowlist_sqlite_backend(
    diag_app, sample_user, monkeypatch, tmp_path
):
    """When progress.py has no Data API selection functions, backend_type is sqlite_local."""
    import importlib

    from platform_app import diag_runtime

    project_root = Path(diag_app.root_path).parent
    manifest = _manifest_for_project(project_root)
    manifest_path = Path(diag_app.config["DATA_DIR"]) / "build_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest))

    # Point the module to the temp manifest via env var and reload so caches are fresh.
    monkeypatch.setenv("RUNTIME_MANIFEST_PATH", str(manifest_path))
    importlib.reload(diag_runtime)

    # No Supabase env, no AI env.
    for key in (
        "CODER_SUPABASE_URL",
        "CODER_SUPABASE_ANON_KEY",
        "CODER_SUPABASE_TENANT_ID",
        "CODER_CODING_MODEL_BASE_URL",
        "CODER_CODING_MODEL_API_KEY",
        "AI_BASE_URL",
        "AI_API_KEY",
        "AI_TEXT_MODEL",
        "AI_VISION_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["app_env"] == "preview"
    assert resp.json["backend_type"] == "sqlite_local"
    assert resp.json["ai_source"] == "unconfigured"
    assert resp.json["ai_native_vars_present"] is False
    assert resp.json["enrollment_status"] == "missing_env"
    assert resp.json["has_visible_enrollment"] is False
    assert resp.json["manifest_match"] is True
    assert resp.json["manifest_head"] == "unknown"
    for matched in resp.json["module_hashes_match"].values():
        assert matched is True
    for label, sha in resp.json["loaded_sha256"].items():
        assert isinstance(sha, str) and len(sha) == 64
        assert resp.json["manifest_sha256"][label] == sha


def test_diag_runtime_ai_native_source(diag_app, sample_user, monkeypatch):
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_CODING_MODEL_BASE_URL", "https://native.example.com")
    monkeypatch.setenv("CODER_CODING_MODEL_API_KEY", "fake-api-key")
    for key in (
        "CODER_SUPABASE_URL",
        "CODER_SUPABASE_ANON_KEY",
        "CODER_SUPABASE_TENANT_ID",
        "AI_BASE_URL",
        "AI_API_KEY",
        "AI_TEXT_MODEL",
        "AI_VISION_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["ai_source"] == "native"
    assert resp.json["ai_native_vars_present"] is True
    assert resp.json["enrollment_status"] == "missing_env"


def test_diag_runtime_ai_legacy_source(diag_app, sample_user, monkeypatch):
    from platform_app import diag_runtime

    monkeypatch.setenv("AI_BASE_URL", "https://legacy.example.com")
    monkeypatch.setenv("AI_API_KEY", "fake-api-key")
    monkeypatch.setenv("AI_TEXT_MODEL", "legacy-text")
    monkeypatch.setenv("AI_VISION_MODEL", "legacy-vision")
    for key in (
        "CODER_SUPABASE_URL",
        "CODER_SUPABASE_ANON_KEY",
        "CODER_SUPABASE_TENANT_ID",
        "CODER_CODING_MODEL_BASE_URL",
        "CODER_CODING_MODEL_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["ai_source"] == "legacy"
    assert resp.json["ai_native_vars_present"] is False


def test_diag_runtime_enrollment_empty(diag_app, sample_user, monkeypatch):
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")
    monkeypatch.setattr(
        "httpx.request",
        _fake_data_api_request(
            [{"id": BUSINESS_STUDENT_ID, "auth_user_id": AUTH_UID}],
            [],
        ),
    )

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["enrollment_status"] == "empty"
    assert resp.json["has_visible_enrollment"] is False


def test_diag_runtime_enrollment_visible(diag_app, sample_user, monkeypatch):
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")
    monkeypatch.setattr(
        "httpx.request",
        _fake_data_api_request(
            [{"id": BUSINESS_STUDENT_ID, "auth_user_id": AUTH_UID}],
            [{"student_id": BUSINESS_STUDENT_ID}],
        ),
    )

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["enrollment_status"] == "visible"
    assert resp.json["has_visible_enrollment"] is True
    assert BUSINESS_STUDENT_ID not in resp.get_data(as_text=True)


def test_diag_runtime_mapping_missing(diag_app, sample_user, monkeypatch):
    """No users row for the caller's auth_uid -> mapping_missing."""
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")
    monkeypatch.setattr(
        "httpx.request",
        _fake_data_api_request([], []),
    )

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["enrollment_status"] == "mapping_missing"
    assert resp.json["has_visible_enrollment"] is False


def test_diag_runtime_enrollment_others_row_rejected(diag_app, sample_user, monkeypatch):
    """If enrollments returns a row for a different student_id, reject it."""
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")
    monkeypatch.setattr(
        "httpx.request",
        _fake_data_api_request(
            [{"id": BUSINESS_STUDENT_ID, "auth_user_id": AUTH_UID}],
            [{"student_id": "other_student_id"}],
        ),
    )

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["enrollment_status"] == "forbidden"
    assert resp.json["has_visible_enrollment"] is False
    assert "other_student_id" not in resp.get_data(as_text=True)


def test_diag_runtime_enrollment_forbidden(diag_app, sample_user, monkeypatch):
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")

    def request(method: str, url: str, **kwargs):
        if "/rest/v1/users" in url:
            return _FakeResponse(403, {"message": "Access denied by RLS"})
        return _FakeResponse(404, {})

    monkeypatch.setattr("httpx.request", request)

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["enrollment_status"] == "forbidden"
    assert resp.json["has_visible_enrollment"] is False
    assert "Access denied by RLS" not in resp.get_data(as_text=True)


def test_diag_runtime_enrollment_unreachable(diag_app, sample_user, monkeypatch):
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("CODER_SUPABASE_ANON_KEY", "fake-anon-key")
    monkeypatch.setenv("CODER_SUPABASE_TENANT_ID", "fake-tenant-id")

    def boom(*args, **kwargs):
        raise RuntimeError("network failure must not leak")

    monkeypatch.setattr("httpx.request", boom)

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["enrollment_status"] == "unreachable"
    assert resp.json["has_visible_enrollment"] is False
    assert "network failure" not in resp.get_data(as_text=True)


def test_diag_runtime_missing_manifest(diag_app, sample_user, monkeypatch, tmp_path):
    """When the manifest is absent, head is unknown and manifest_sha256 is null."""
    import importlib

    from platform_app import diag_runtime

    missing_manifest = tmp_path / "missing_manifest.json"
    monkeypatch.setenv("RUNTIME_MANIFEST_PATH", str(missing_manifest))
    importlib.reload(diag_runtime)

    for key in (
        "CODER_SUPABASE_URL",
        "CODER_SUPABASE_ANON_KEY",
        "CODER_SUPABASE_TENANT_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["manifest_head"] == "unknown"
    assert resp.json["manifest_match"] is False
    for sha in resp.json["manifest_sha256"].values():
        assert sha is None
    for label, sha in resp.json["loaded_sha256"].items():
        assert isinstance(sha, str) and len(sha) == 64
        assert resp.json["module_hashes_match"][label] is False


def test_diag_runtime_html_response_uses_template(diag_app, sample_user, monkeypatch):
    """HTML rendering goes through Jinja auto-escaping, not f-string interpolation."""
    from platform_app import diag_runtime

    monkeypatch.setenv("CODER_CODING_MODEL_BASE_URL", "https://native.example.com")
    monkeypatch.setenv("CODER_CODING_MODEL_API_KEY", "fake-api-key")

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post(
            "/api/diag/runtime",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )

    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    text = resp.get_data(as_text=True)
    assert "运行版本诊断" in text
    assert "secret-access-token" not in text
    assert "fake-api-key" not in text
    assert "native.example.com" not in text


def test_diag_runtime_backend_type_postgrest_when_rpc_present(
    diag_app, sample_user, monkeypatch
):
    """If progress.py exposes student_selection_summary, backend_type reports postgrest_remote."""
    from platform_app import diag_runtime
    from platform_app.services import progress as progress_module

    monkeypatch.setattr(
        progress_module,
        "student_selection_summary",
        lambda *a, **k: None,
        raising=False,
    )

    _patch_valid_token(monkeypatch)

    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        with client.session_transaction() as sess:
            sess["cx_access_token"] = "secret-access-token"
        resp = client.post("/api/diag/runtime")

    _assert_allowlist_only(resp, _ALLOWLIST_KEYS)
    assert resp.json["backend_type"] == "postgrest_remote"


def test_diag_index_requires_login(diag_app):
    with diag_app.test_client() as client:
        resp = client.get("/diag")
    assert resp.status_code == 401
    assert resp.json["diag_status"] == "unauthenticated"


def test_diag_index_renders_for_logged_in_user(diag_app, sample_user):
    with diag_app.test_client() as client:
        _login_client(client, sample_user.id)
        resp = client.get("/diag")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    text = resp.get_data(as_text=True)
    assert "运行版本与后端诊断" in text
    assert "/api/diag/runtime" in text
    assert "csrf_token" in text
    assert "secret-access-token" not in text


def test_build_manifest_contains_no_secrets(tmp_path, monkeypatch):
    """The generated manifest must contain only hashes and head; no env values."""
    import scripts.build_manifest as bm

    project_root = Path(__file__).resolve().parent.parent
    monkeypatch.setattr(bm, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(bm, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(bm, "MANIFEST_PATH", tmp_path / "build_manifest.json")

    # Set fake secrets in env; they must not leak into manifest.
    monkeypatch.setenv("AI_API_KEY", "super-secret-key")
    monkeypatch.setenv("CODER_CODING_MODEL_API_KEY", "another-secret")

    bm.main()

    manifest_text = (tmp_path / "build_manifest.json").read_text()
    assert "super-secret-key" not in manifest_text
    assert "another-secret" not in manifest_text
    assert "head" in manifest_text
    assert "files" in manifest_text
    data = json.loads(manifest_text)
    assert set(data.keys()) == {"head", "generated_at", "files"}
