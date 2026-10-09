# 交付验收记录

## 项目：武汉大学量子物理实验报告平台

验收原则：所有结论必须有命令/响应/日志证据；缺少真实令牌时明确标为“未验证”，不伪造数据。

---

## Round 1：超星 OAuth 用户令牌服务端安全存储与校验

### 目标

- 移除“未验签 decode JWT 作为身份依据”。
- exchange 返回的 `access_token` / `refresh_token` 只保存在服务端 `app_sessions`，不进入 URL/浏览器可读票据/日志。
- 实现 Supabase Auth 用户校验、令牌刷新、注销清除。
- 保留所有现有改动与业务数据，不做全量数据库迁移/UI 改动。

### 修改文件

| 文件 | 改动摘要 |
|------|----------|
| `platform_app/blueprints/auth.py` | 新增 `_supabase_env()`、`_verify_access_token()`、`_refresh_access_token()`；`chaoxing_callback` 改用 Supabase Auth `/auth/v1/user` 校验 access_token；令牌写入服务端 session；移除未验签 `_decode_jwt_payload` 的身份用途 |
| `tests/test_chaoxing_token_session.py` | 新增 7 个测试：校验成功/失败/缺环境变量、刷新令牌、回调存令牌、拒绝未校验令牌、注销清除 |
| `.env.preview` | 增加 `APP_PUBLIC_BASE_URL=https://app-a398jfvyx9l6.cxiagents.com` |
| `requirements.txt` | 增加 `pytest>=8.0.0` |
| `docs/CHAOXING_CODER_PLAYBOOK.md` | 新建：架构/运行配置、认证权限边界、部署回滚、常见问题、未验证项 |
| `docs/DELIVERY_ACCEPTANCE.md` | 本文件 |

### 测试结果

```text
$ python3 -m pytest tests/test_chaoxing_token_session.py tests/test_chaoxing_callback.py -v
============================== 12 passed in 4.38s ==============================
```

- `test_verify_access_token_success`：校验请求携带 `Authorization: Bearer <token>`、`apikey` 与 `X-Instance-ID`。
- `test_verify_access_token_invalid`：Supabase Auth 返回 401 时拒绝登录。
- `test_callback_stores_tokens_server_side_only`：确认 `cx_access_token` / `cx_refresh_token` 写入 `app_sessions.data`，响应 Location/body 中无令牌。
- `test_callback_rejects_unverified_token`：令牌校验失败时不创建 `user_id` 会话。
- `test_logout_clears_tokens`：注销后服务端会话中 `user_id` 与令牌被清除。

### 真实环境检查（脱敏）

| 检查项 | 命令/路径 | 结果 |
|--------|-----------|------|
| Supabase 环境变量存在性 | 检查 `CODER_SUPABASE_URL/ANON_KEY/TENANT_ID` | 三项均已设置（长度脱敏） |
| Supabase Auth 端点可达 | `GET {url}/auth/v1/user` with fake token | `403`（端点可达，假令牌被拒绝） |
| Data API 匿名访问 | `GET {url}/rest/v1/users` with anon key only | `401`（说明业务表未对 anon 开放） |
| 真实用户 JWT 的允许/拒绝场景 | — | **未验证**（缺少真实登录后的 access_token） |

### 未验证项

- **Data API 真实用户 JWT 权限边界**：需用真实超星账号完成一次登录，取得 access_token 后，验证能读取授权范围、越权访问被拒绝。本轮无真实令牌，未做。
- **公开环境数据持久化契约**：`runtime/` 是否跨部署保留仍未知，是覆盖线上部署的唯一阻塞。

### 部署状态

- 本 Agent 无原生部署命令（`coder --help` 不含 `deploy`）。
- 已准备可部署 commit，提交 hash 见下一条交付记录。
- 部署方式：通过 Coder 面板选择该 commit 部署；部署前请确认平台已配置持久卷或已备份 `runtime/platform.db` 与 `runtime/` 下上传文件。

---

## 历史修复（已包含在当前工作区，待随本轮 commit 一起进入部署）

| 修复 | 证据 |
|------|------|
| 超星回调 URL 跳沙箱 | `auth.py::_app_public_base()` 与 `tests/test_chaoxing_callback.py` 5 项测试通过 |
| 首页登录 405 | `login.html` 表单显式 `action="{{ url_for('auth.login') }}"` |
| 400 CSRF token missing | `base.html` 改用 `<meta name="sid">` 传递 `_sid`，`sid.js` 从 meta 读取 |

---

## 已知阻塞（需用户/平台确认）

1. **公开实例 SQLite/上传目录跨部署是否持久化**——确认前不应覆盖线上。
2. **真实超星教师 + 两名学生账号**——用于下一轮真实角色权限验收；若无法提供，相关测试标记为未验证。
