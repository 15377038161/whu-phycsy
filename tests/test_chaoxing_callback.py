"""超星 OAuth 回跳 URL 构造的回归测试。

覆盖场景：
  1. 显式 APP_PUBLIC_BASE_URL 优先（公开部署）
  2. CODER_PROJECTS_DOMAIN 回退（预览/平台注入域名）
  3. 不可信 X-Forwarded-Host / Host 不得污染回跳地址
  4. 无任何配置时回退 request.url_root（本地开发）

核心约束：回跳地址（浏览器可见）绝不依赖 request.url_root 中被代理注入的沙箱地址。
"""

from __future__ import annotations

import pytest

from platform_app.blueprints.auth import _app_public_base


@pytest.fixture
def app_for_callback(tmp_path):
    from platform_app import create_app

    return create_app({
        "TESTING": True,
        "SECRET_KEY": "callback-test-secret",
        "DATA_DIR": str(tmp_path / "data"),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'callback.db'}",
    })


def _public_base(monkeypatch, public=None, projects_domain=None):
    if public is None:
        monkeypatch.delenv("APP_PUBLIC_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("APP_PUBLIC_BASE_URL", public)
    if projects_domain is None:
        monkeypatch.delenv("CODER_PROJECTS_DOMAIN", raising=False)
    else:
        monkeypatch.setenv("CODER_PROJECTS_DOMAIN", projects_domain)


def test_public_base_prefers_explicit_app_public_base_url(app_for_callback, monkeypatch):
    _public_base(monkeypatch, public="https://app-a398jfvyx9l6.cxiagents.com")
    with app_for_callback.test_request_context(
        "/auth/chaoxing",
        base_url="http://sandbox-internal-8080.cxiagents.com",
        headers={"X-Forwarded-Host": "sandbox-internal-8080.cxiagents.com"},
    ):
        assert _app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"


def test_public_base_falls_back_to_projects_domain(app_for_callback, monkeypatch):
    _public_base(monkeypatch, projects_domain="https://app-a398jfvyx9l6.cxiagents.com")
    with app_for_callback.test_request_context("/auth/chaoxing"):
        assert _app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"


def test_public_base_ignores_untrusted_forwarded_host(app_for_callback, monkeypatch):
    """即使代理注入沙箱 X-Forwarded-Host，只要配了公开域名就绝不受污染。"""
    _public_base(
        monkeypatch,
        public="https://app-a398jfvyx9l6.cxiagents.com",
        projects_domain="https://sandbox-preview.cxiagents.com",
    )
    with app_for_callback.test_request_context(
        "/auth/chaoxing",
        base_url="http://sandbox-1af8850a-8080.cxiagents.com",
        headers={
            "Host": "sandbox-1af8850a-8080.cxiagents.com",
            "X-Forwarded-Host": "sandbox-1af8850a-8080.cxiagents.com",
        },
    ):
        assert _app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"


def test_public_base_falls_back_to_request_root_only_locally(app_for_callback, monkeypatch):
    _public_base(monkeypatch)
    with app_for_callback.test_request_context("/auth/chaoxing", base_url="http://localhost:5000"):
        assert _app_public_base() == "http://localhost:5000"


def test_public_base_strips_trailing_slash(app_for_callback, monkeypatch):
    _public_base(monkeypatch, public="https://app-a398jfvyx9l6.cxiagents.com/")
    with app_for_callback.test_request_context("/auth/chaoxing"):
        assert _app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"
