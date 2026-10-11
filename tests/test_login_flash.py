"""登录页 flash 消息渲染与 HTML 转义回归测试。"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """提供已配置公开基址的测试客户端。"""
    from platform_app import create_app

    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.edu.cn")
    monkeypatch.delenv("CODER_PROJECTS_DOMAIN", raising=False)

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "flash-test-secret",
            "DATA_DIR": str(tmp_path / "data"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'flash.db'}",
        }
    )
    return app.test_client()


def test_login_renders_real_error_flash_after_failed_login(app_client):
    """真实登录失败后，login.html 应渲染 error 类别 flash。"""
    with app_client as client:
        resp = client.post(
            "/login",
            data={"username": "not-exist", "password": "wrong"},
            follow_redirects=False,
        )

    assert resp.status_code == 200
    html = resp.data.decode()
    assert "账号或密码错误。" in html
    assert "flash-error" in html


def test_login_renders_success_flash(app_client):
    """login.html 应渲染 success 类别 flash。"""
    with app_client as client:
        with client.session_transaction() as sess:
            sess["_flashes"] = [("success", "密码已更新，请重新登录。")]
        resp = client.get("/login")

    assert resp.status_code == 200
    html = resp.data.decode()
    assert "密码已更新，请重新登录。" in html
    assert "flash-success" in html


def test_login_escapes_html_in_flash(app_client):
    """flash 内容中的 HTML 必须被 Jinja 默认转义，不能形成 XSS。"""
    payload = '<script>alert("xss")</script>'

    with app_client as client:
        with client.session_transaction() as sess:
            sess["_flashes"] = [("error", payload)]
        resp = client.get("/login")

    assert resp.status_code == 200
    html = resp.data.decode()
    # 原始脚本不得原样出现
    assert payload not in html
    # 必须被转义为实体
    assert "&lt;script&gt;" in html or "&lt;script&gt;alert" in html
    assert "flash-error" in html
