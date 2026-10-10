"""超星 OAuth 回跳 URL 构造与公开基址校验的回归测试。

覆盖场景：
  1. 显式 APP_PUBLIC_BASE_URL 优先（公开部署）
  2. CODER_PROJECTS_DOMAIN 回退（预览/平台注入域名）
  3. 不可信 X-Forwarded-Host / Host 不得污染回跳地址
  4. 无任何配置时回退 request.url_root（本地开发）
  5. 非法/沙箱域名时 /auth/chaoxing 实际路由必须拒绝，不能产生 localhost/内部 redirect_uri
  6. 生产启动在缺配置/非 https/无 hostname/userinfo/异常端口时明确失败

核心约束：回跳地址（浏览器可见）绝不依赖 request.url_root 中被代理注入的沙箱地址；
OAuth 场景必须重新严格解析环境变量，不能直接使用内部重定向缓存。
"""

from __future__ import annotations

import pytest

from platform_app import create_app
from platform_app.blueprints.auth import (
    _app_public_base,
    _resolve_app_public_base,
    _strict_app_public_base,
    check_app_public_base_at_startup,
)


@pytest.fixture
def app_for_callback(tmp_path):
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


def _clear_cached_public_base(app):
    """清除启动阶段缓存的公开基址，强制 _app_public_base 重新解析环境变量。"""
    app.config.pop("APP_PUBLIC_BASE_URL", None)


def test_public_base_prefers_explicit_app_public_base_url(app_for_callback, monkeypatch):
    _clear_cached_public_base(app_for_callback)
    _public_base(monkeypatch, public="https://app-a398jfvyx9l6.cxiagents.com")
    with app_for_callback.test_request_context(
        "/auth/chaoxing",
        base_url="http://sandbox-internal-8080.cxiagents.com",
        headers={"X-Forwarded-Host": "sandbox-internal-8080.cxiagents.com"},
    ):
        assert _strict_app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"


def test_public_base_falls_back_to_projects_domain(app_for_callback, monkeypatch):
    _clear_cached_public_base(app_for_callback)
    _public_base(monkeypatch, projects_domain="https://app-a398jfvyx9l6.cxiagents.com")
    with app_for_callback.test_request_context("/auth/chaoxing"):
        assert _strict_app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"


def test_public_base_ignores_untrusted_forwarded_host(app_for_callback, monkeypatch):
    """即使代理注入沙箱 X-Forwarded-Host，只要配了公开域名就绝不受污染。"""
    _clear_cached_public_base(app_for_callback)
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
        assert _strict_app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"


def test_public_base_falls_back_to_request_root_only_locally(app_for_callback, monkeypatch):
    _clear_cached_public_base(app_for_callback)
    _public_base(monkeypatch)
    with app_for_callback.test_request_context("/auth/chaoxing", base_url="http://localhost:5000"):
        assert _strict_app_public_base() == "http://localhost:5000"


def test_public_base_strips_trailing_slash(app_for_callback, monkeypatch):
    _clear_cached_public_base(app_for_callback)
    _public_base(monkeypatch, public="https://app-a398jfvyx9l6.cxiagents.com/")
    with app_for_callback.test_request_context("/auth/chaoxing"):
        assert _strict_app_public_base() == "https://app-a398jfvyx9l6.cxiagents.com"


def test_strict_public_base_rejects_sandbox_domain(app_for_callback, monkeypatch):
    """未配置 APP_PUBLIC_BASE_URL 且 CODER_PROJECTS_DOMAIN 为沙箱地址时，严格解析必须失败。"""
    _clear_cached_public_base(app_for_callback)
    _public_base(monkeypatch, projects_domain="https://sandbox-abc-8080.cxiagents.com")
    with app_for_callback.test_request_context("/auth/chaoxing"):
        with pytest.raises(RuntimeError):
            _strict_app_public_base()


def test_strict_public_base_rejects_invalid_app_public_base(app_for_callback, monkeypatch):
    """APP_PUBLIC_BASE_URL 被配成非 https/无 hostname/userinfo/异常端口时必须失败。"""
    _clear_cached_public_base(app_for_callback)
    _public_base(monkeypatch, public="http://app-a398jfvyx9l6.cxiagents.com")
    with app_for_callback.test_request_context("/auth/chaoxing"):
        with pytest.raises(RuntimeError):
            _strict_app_public_base()


def test_public_base_validation_by_urlsplit(monkeypatch):
    """urlsplit 完整校验：非 https、无 hostname、userinfo、path、query、fragment、异常端口均失败。"""
    invalid_bases = [
        "http://app.example.com",                 # 非 https
        "https:///path",                          # 无 hostname
        "https://user:pass@app.example.com",      # userinfo
        "https://app.example.com:8443",           # 异常端口
        "https://app.example.com/path",           # path
        "https://app.example.com?x=1",            # query
        "https://app.example.com#frag",           # fragment
    ]
    for base in invalid_bases:
        monkeypatch.setenv("APP_PUBLIC_BASE_URL", base)
        with pytest.raises(RuntimeError):
            _resolve_app_public_base(fail_closed=False, allow_local=False)

    # 合法配置应通过
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app-a398jfvyx9l6.cxiagents.com")
    assert _resolve_app_public_base(fail_closed=False, allow_local=False) == "https://app-a398jfvyx9l6.cxiagents.com"


def test_internal_redirect_uses_cached_base_even_with_invalid_env(app_for_callback, monkeypatch):
    """内部重定向缓存路径：即使环境变量已配成非法域名，登录后跳转仍使用启动缓存的 localhost。"""
    # app_for_callback 在沙箱 CODER_PROJECTS_DOMAIN 下启动，缓存已被设为 localhost
    _public_base(monkeypatch, public="http://invalid.example.com")
    with app_for_callback.test_request_context("/login", base_url="http://localhost:5000"):
        # 不清缓存，_app_public_base 直接返回缓存值，保证非 OAuth 页面可用
        assert _app_public_base() == "http://localhost:5000"


def test_chaoxing_route_rejects_invalid_projects_domain_without_clearing_cache(app_for_callback, monkeypatch):
    """不清缓存：CODER_PROJECTS_DOMAIN 为沙箱地址时，实际 /auth/chaoxing 路由必须拒绝。"""
    _public_base(monkeypatch, projects_domain="https://sandbox-abc-8080.cxiagents.com")
    client = app_for_callback.test_client()
    with pytest.raises(RuntimeError):
        client.get("/auth/chaoxing", base_url="http://localhost:5000")


def test_chaoxing_route_rejects_http_public_base_without_clearing_cache(app_for_callback, monkeypatch):
    """不清缓存：APP_PUBLIC_BASE_URL 为非 https 时，实际 /auth/chaoxing 路由必须拒绝。"""
    _public_base(monkeypatch, public="http://app.example.com")
    client = app_for_callback.test_client()
    with pytest.raises(RuntimeError):
        client.get("/auth/chaoxing", base_url="http://localhost:5000")


def test_chaoxing_route_allows_localhost_in_development_without_config(app_for_callback, monkeypatch):
    """不清缓存：开发环境无配置时，/auth/chaoxing 允许回退到 localhost。"""
    _public_base(monkeypatch)
    client = app_for_callback.test_client()
    # 无配置时回退 localhost，不会触发公开基址校验异常；外部认证代理调用失败会降级跳转登录页
    response = client.get("/auth/chaoxing", base_url="http://localhost:5000")
    assert response.status_code == 302


def test_production_startup_fails_without_config(monkeypatch):
    monkeypatch.delenv("APP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("CODER_PROJECTS_DOMAIN", raising=False)
    with pytest.raises(RuntimeError, match="APP_PUBLIC_BASE_URL 未配置"):
        check_app_public_base_at_startup(env="production")


def test_production_startup_fails_with_invalid_config(monkeypatch):
    invalid_values = [
        "http://app.example.com",
        "https://user:pass@app.example.com",
        "https://app.example.com:8443",
        "https:///path",
        "app.example.com/path",
    ]
    for value in invalid_values:
        monkeypatch.setenv("APP_PUBLIC_BASE_URL", value)
        with pytest.raises(RuntimeError):
            check_app_public_base_at_startup(env="production")


def test_production_startup_succeeds_with_valid_https_config(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app-a398jfvyx9l6.cxiagents.com")
    assert check_app_public_base_at_startup(env="production") == "https://app-a398jfvyx9l6.cxiagents.com"


def test_development_startup_allows_localhost_fallback_with_invalid_config(monkeypatch):
    monkeypatch.setenv("CODER_PROJECTS_DOMAIN", "https://sandbox-abc-8080.cxiagents.com")
    assert check_app_public_base_at_startup(env="development") == "http://localhost:5000"


def test_proxy_prefix_stripper_also_clears_script_name():
    """SCRIPT_NAME 被平台代理设成沙箱前缀时，stripper 必须清空它，防止 url_for 泄露。"""
    from platform_app import _SandboxProxyPrefixStripper

    class App:
        def __call__(self, environ, start_response):
            self.captured = environ
            return [b"ok"]

    inner = App()
    stripper = _SandboxProxyPrefixStripper(inner)
    environ = {
        "SCRIPT_NAME": "/sandboxes/80230478-ac1d-4e99-b8a6-e662006441cc/proxy/8080",
        "PATH_INFO": "/student/home",
    }
    list(stripper(environ, lambda status, headers: None))
    assert inner.captured["SCRIPT_NAME"] == ""
    assert inner.captured["PATH_INFO"] == "/student/home"
