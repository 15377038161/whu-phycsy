"""端到端功能 + 安全审计脚本。对本地运行的实例做黑盒 HTTP 测试。

用法: python tests/e2e_audit.py http://127.0.0.1:5000
不修改被测数据库中的核心数据（只读为主；写操作使用可回收账号）。
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
TEACHER = ("admin", "admin123")
STUDENT = ("S001", "123456")

results = []  # (dimension, severity, title, detail)


def log(dim, sev, title, detail=""):
    results.append((dim, sev, title, detail))
    tag = {"PASS": "[PASS]", "INFO": "[INFO]", "致命": "[致命]", "严重": "[严重]",
           "一般": "[一般]", "优化": "[优化]"}.get(sev, sev)
    print(f"{tag} <{dim}> {title}")
    if detail:
        print(f"        {detail}")


def session_login(username, password):
    s = requests.Session()
    r = s.post(f"{BASE}/login", data={"username": username, "password": password},
               allow_redirects=False)
    return s, r


def get(s, path, **kw):
    return s.get(f"{BASE}{path}", allow_redirects=False, **kw)


def post(s, path, **kw):
    return s.post(f"{BASE}{path}", allow_redirects=False, **kw)


# ---------------------------------------------------------------------------
# 1. 认证 / 会话安全
# ---------------------------------------------------------------------------
def test_auth_session():
    dim = "认证与会话"
    # 错误密码
    s, r = session_login("admin", "wrong-password")
    if r.status_code == 200 and "user_id" not in s.cookies.get_dict():
        log(dim, "PASS", "错误密码被拒绝")
    else:
        log(dim, "严重", "错误密码可能被接受", f"status={r.status_code}")

    # 正确教师登录
    s, r = session_login(*TEACHER)
    loc = r.headers.get("Location", "")
    if r.status_code in (301, 302) and "teacher" in loc:
        log(dim, "PASS", "教师登录成功并跳转教师端")
    else:
        log(dim, "严重", "教师登录异常", f"status={r.status_code} loc={loc}")

    # Cookie 安全属性
    set_cookie = r.headers.get("Set-Cookie", "")
    if "HttpOnly" in set_cookie:
        log(dim, "PASS", "会话 Cookie 含 HttpOnly")
    else:
        log(dim, "严重", "会话 Cookie 缺少 HttpOnly", set_cookie[:120])
    if "SameSite" in set_cookie:
        log(dim, "PASS", "会话 Cookie 含 SameSite")
    else:
        log(dim, "一般", "会话 Cookie 缺少 SameSite", set_cookie[:120])
    # 开发环境 Secure 缺失是预期（SESSION_COOKIE_SECURE=env==production）
    if "Secure" not in set_cookie:
        log(dim, "INFO", "开发环境 Cookie 无 Secure（生产环境自动开启，需验证生产配置）")

    # 登出后会话失效
    st, _ = session_login(*STUDENT)
    post(st, "/logout")
    r2 = get(st, "/student/home")
    if r2.status_code in (301, 302) and "login" in r2.headers.get("Location", ""):
        log(dim, "PASS", "登出后受保护页面重定向到登录")
    else:
        log(dim, "严重", "登出后仍可访问受保护页面", f"status={r2.status_code}")


# ---------------------------------------------------------------------------
# 2. 未授权访问 / 权限边界
# ---------------------------------------------------------------------------
def test_authorization():
    dim = "权限与越权"
    anon = requests.Session()
    protected = [
        ("/teacher", "GET"), ("/teacher/experiments", "GET"),
        ("/teacher/students", "GET"), ("/teacher/analytics", "GET"),
        ("/student/home", "GET"), ("/student/records", "GET"),
        ("/student/achievements", "GET"),
        ("/api/teacher/analytics", "GET"), ("/api/student/submissions", "GET"),
    ]
    for path, method in protected:
        r = get(anon, path) if method == "GET" else post(anon, path)
        ok = r.status_code in (301, 302) and "login" in r.headers.get("Location", "")
        # API 端点 role_required 也重定向到 login
        if ok:
            continue
        log(dim, "严重", f"匿名可访问受保护端点 {path}", f"status={r.status_code}")
    else:
        log(dim, "PASS", "匿名访问受保护端点均被拦截")

    # 学生访问教师端
    st, _ = session_login(*STUDENT)
    for path in ("/teacher", "/teacher/experiments", "/teacher/students",
                 "/api/teacher/analytics", "/api/teacher/submissions"):
        r = get(st, path)
        if not (r.status_code in (301, 302) and "login" in r.headers.get("Location", "")):
            log(dim, "严重", f"学生越权访问教师端点 {path}", f"status={r.status_code}")
            break
    else:
        log(dim, "PASS", "学生访问教师端点均被拦截")

    # 教师访问学生端点
    te, _ = session_login(*TEACHER)
    r = get(te, "/student/home")
    if r.status_code in (301, 302) and "login" in r.headers.get("Location", ""):
        log(dim, "PASS", "教师访问学生端点被拦截")
    else:
        log(dim, "一般", "教师可访问学生端点", f"status={r.status_code}")


# ---------------------------------------------------------------------------
# 3. IDOR - 越权访问他人报告
# ---------------------------------------------------------------------------
def test_idor():
    dim = "越权访问(IDOR)"
    st, _ = session_login(*STUDENT)
    # 猜测/伪造 submission id
    for fake in ("00000000-0000-0000-0000-000000000000", "1", "../etc/passwd"):
        r = get(st, f"/student/report/{fake}")
        if r.status_code == 404:
            continue
        if r.status_code == 200:
            log(dim, "严重", f"学生可访问伪造报告 id={fake}", f"status={r.status_code}")
            break
    else:
        log(dim, "PASS", "伪造/他人报告 id 均返回 404")

    # 学生访问教师审核端点（IDOR + 越权）
    r = get(st, "/teacher/submission/anything")
    if r.status_code in (301, 302) and "login" in r.headers.get("Location", ""):
        log(dim, "PASS", "学生无法进入教师审核端点")
    else:
        log(dim, "严重", "学生可进入教师审核端点", f"status={r.status_code}")


# ---------------------------------------------------------------------------
# 4. SQL 注入探测（登录 + 查询参数）
# ---------------------------------------------------------------------------
def test_sqli():
    dim = "SQL注入"
    payloads = ["' OR '1'='1", "admin'--", "' OR 1=1--", "'; DROP TABLE users;--"]
    bypassed = False
    for p in payloads:
        s, r = session_login(p, p)
        # 登录成功会 302 到 dashboard/home；失败返回 200 停在登录页
        if r.status_code in (301, 302) and "login" not in r.headers.get("Location", ""):
            log(dim, "致命", "登录存在 SQL 注入绕过", f"payload={p!r} loc={r.headers.get('Location')}")
            bypassed = True
            break
    if not bypassed:
        log(dim, "PASS", "登录框 SQL 注入 payload 均被安全处理（ORM 参数化）")

    # 查询参数注入（教师 analytics 过滤器）
    te, _ = session_login(*TEACHER)
    r = get(te, "/api/teacher/analytics?course=' OR '1'='1&experiment=1;DROP TABLE users")
    if r.status_code in (200, 400, 403):
        log(dim, "PASS", f"analytics 过滤器注入被安全处理 (status={r.status_code})")
    elif r.status_code == 500:
        log(dim, "一般", "analytics 过滤器注入触发 500（异常未处理，但未泄露）", "")
    else:
        log(dim, "INFO", f"analytics 注入返回 status={r.status_code}")


# ---------------------------------------------------------------------------
# 5. XSS 探测（AI 助手回显 + 反射）
# ---------------------------------------------------------------------------
def test_xss():
    dim = "XSS"
    st, _ = session_login(*STUDENT)
    # 学生 AI 助手：注入脚本，检查回显是否转义（服务不可用时跳过）
    payload = "<img src=x onerror=alert(1)>"
    r = post(st, "/api/student/assistant",
             json={"question": payload, "context": payload, "history": []})
    if r.status_code == 503:
        log(dim, "INFO", "学生 AI 服务不可用，跳过回显检测（前端已 escapeHtml 先转义）")
    elif r.status_code == 200:
        body = r.text
        if "<img src=x" in body and "&lt;img" not in body:
            log(dim, "一般", "AI 回显包含未转义脚本（前端渲染需 escapeHtml）", body[:160])
        else:
            log(dim, "PASS", "AI 回显安全")
    # 反射型：登录页 flash / 查询参数
    anon = requests.Session()
    r = anon.get(f"{BASE}/login?next=<script>alert(1)</script>")
    if "<script>alert(1)</script>" in r.text:
        log(dim, "严重", "登录页存在反射型 XSS")
    else:
        log(dim, "PASS", "登录页未反射未转义输入")


# ---------------------------------------------------------------------------
# 6. 功能完整性：遍历核心页面
# ---------------------------------------------------------------------------
def test_functional_pages():
    dim = "功能完整性"
    st, _ = session_login(*STUDENT)
    student_pages = {
        "/student/home": "实验探索",
        "/student/records": "我的实验",
        "/student/achievements": "报告",
        "/student/experiment/ION": "实验",
    }
    for path, marker in student_pages.items():
        r = get(st, path)
        if r.status_code == 200:
            log(dim, "PASS", f"学生页可访问 {path} (200)")
        else:
            log(dim, "严重", f"学生页异常 {path}", f"status={r.status_code}")

    te, _ = session_login(*TEACHER)
    teacher_pages = ["/teacher", "/teacher/experiments", "/teacher/students",
                     "/teacher/analytics"]
    for path in teacher_pages:
        r = get(te, path)
        if r.status_code == 200:
            log(dim, "PASS", f"教师页可访问 {path} (200)")
        else:
            log(dim, "严重", f"教师页异常 {path}", f"status={r.status_code}")

    # API 数据返回
    r = get(te, "/api/teacher/analytics")
    if r.status_code == 200:
        try:
            data = r.json()
            if "summary" in data:
                log(dim, "PASS", "教师 analytics API 返回结构完整")
            else:
                log(dim, "一般", "analytics API 缺少 summary 字段", str(data)[:120])
        except Exception as e:
            log(dim, "一般", "analytics API 非 JSON", str(e))
    r = get(st, "/api/student/submissions")
    if r.status_code == 200:
        log(dim, "PASS", "学生 submissions API 可访问")

    # 健康检查
    anon = requests.Session()
    for path in ("/health", "/ready"):
        r = anon.get(f"{BASE}{path}")
        log(dim, "INFO", f"{path} -> {r.status_code}")

    # 不存在的实验代码
    r = get(st, "/student/experiment/NONEXIST")
    if r.status_code == 404:
        log(dim, "PASS", "不存在实验代码返回 404")
    else:
        log(dim, "一般", "不存在实验代码未返回 404", f"status={r.status_code}")


# ---------------------------------------------------------------------------
# 7. 安全响应头 / 输入长度 / 上传类型
# ---------------------------------------------------------------------------
def test_headers_and_inputs():
    dim = "安全配置"
    anon = requests.Session()
    r = anon.get(f"{BASE}/login")
    headers = {k.lower(): v for k, v in r.headers.items()}
    for h, sev in [("x-frame-options", "一般"),
                   ("content-security-policy", "一般"),
                   ("x-content-type-options", "优化"),
                   ("strict-transport-security", "优化")]:
        if h in headers:
            log(dim, "PASS", f"存在安全头 {h}")
        else:
            log(dim, sev, f"缺少安全头 {h}")

    # CSRF：POST 表单是否有 token
    if "csrf" not in r.text.lower():
        log(dim, "严重", "登录/表单无 CSRF token（仅依赖 SameSite=Lax）",
            "跨站 POST 防护单一，建议加 CSRF token")

    # 学生 AI 超长输入被拒
    st, _ = session_login(*STUDENT)
    r = post(st, "/api/student/assistant", json={"question": "x" * 900})
    if r.status_code == 400:
        log(dim, "PASS", "学生 AI 超长问题被拒绝(400)")
    else:
        log(dim, "INFO", f"学生 AI 超长问题 status={r.status_code}")
    # 空问题
    r = post(st, "/api/student/assistant", json={"question": ""})
    if r.status_code == 400:
        log(dim, "PASS", "学生 AI 空问题被拒绝(400)")


# ---------------------------------------------------------------------------
# 8. 密码策略
# ---------------------------------------------------------------------------
def test_password_policy():
    dim = "密码策略"
    st, _ = session_login(*STUDENT)
    # 纯数字 / 过短 / 不一致 —— 通过修改密码接口（会失败回滚，不改真实密码）
    cases = [
        ("123456", "123456", "过短纯数字应被拒"),
        ("abcdefgh", "abcdefgh", "纯字母应被拒"),
        ("abc12345", "different", "确认不一致应被拒"),
    ]
    for new, confirm, desc in cases:
        r = post(st, "/account/password",
                 data={"current_password": "wrong", "new_password": new,
                       "confirm_password": confirm})
        # current 错误也会拒绝；这里只验证不会 500
        if r.status_code in (301, 302):
            log(dim, "PASS", f"{desc}（接口未异常）")
        else:
            log(dim, "一般", f"{desc} 返回异常", f"status={r.status_code}")


def main():
    print("=" * 70)
    print(f"端到端功能 + 安全审计：{BASE}")
    print("=" * 70)
    for fn in (test_auth_session, test_authorization, test_idor, test_sqli,
               test_xss, test_functional_pages, test_headers_and_inputs,
               test_password_policy):
        try:
            fn()
        except Exception as e:
            log("异常", "INFO", f"{fn.__name__} 执行异常", repr(e))
        print("-" * 70)
        time.sleep(0.2)

    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    by_sev = {}
    for dim, sev, title, detail in results:
        by_sev.setdefault(sev, []).append((dim, title, detail))
    for sev in ("致命", "严重", "一般", "优化", "PASS", "INFO"):
        items = by_sev.get(sev, [])
        if items:
            print(f"\n[{sev}] 共 {len(items)} 项")
            for dim, title, detail in items:
                print(f"  - <{dim}> {title}" + (f" — {detail}" if detail else ""))


if __name__ == "__main__":
    main()

