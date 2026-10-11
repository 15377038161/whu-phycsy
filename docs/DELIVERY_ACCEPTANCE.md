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

## Round 2：修正公开部署后 URL 中泄露沙箱代理前缀

### 目标

- 修复 f7fbcc9 部署后公开站登录成功，但浏览器地址出现 `/sandboxes/<id>/proxy/8080/student/home` 的问题。
- 让 `url_for()` 生成的重定向与页面导航保持根路径 `/student/*`、`/teacher/*`。
- 公开地址配置缺失或非法时 fail closed，不把沙箱/内部地址当作公开回跳地址。

### 根因

平台公开部署代理把沙箱路由前缀同时写入了 WSGI `SCRIPT_NAME`。`_SandboxProxyPrefixStripper` 之前只剥离 `PATH_INFO`，未清空 `SCRIPT_NAME`，导致 Flask `url_for()` 与 redirect `Location` 把沙箱前缀输出到浏览器地址栏。

### 修改文件

| 文件 | 改动摘要 |
|------|----------|
| `platform_app/__init__.py` | `_SandboxProxyPrefixStripper` 同时清空匹配的 `SCRIPT_NAME`；更新注释 |
| `platform_app/blueprints/auth.py` | `_app_public_base` 增加 `_is_trusted_public_domain`；对沙箱/内部/本地地址 fail closed |
| `tests/test_chaoxing_callback.py` | 新增 3 个回归测试：沙箱域名回退失败、非法 APP_PUBLIC_BASE_URL 失败、SCRIPT_NAME 被清空 |
| `docs/CHAOXING_CODER_PLAYBOOK.md` | 补充代理前缀剥离说明与 fail closed 规则 |
| `docs/DELIVERY_ACCEPTANCE.md` | 本文件 |

### 测试结果

```text
$ python3 -m pytest tests/test_chaoxing_callback.py tests/test_chaoxing_token_session.py -v
============================== 15 passed in 4.83s ==============================
```

新增关键测试：
- `test_proxy_prefix_stripper_also_clears_script_name`：模拟平台把 `SCRIPT_NAME` 设成 `/sandboxes/<id>/proxy/8080`，确认 stripper 清空后 `PATH_INFO` 仍为 `/student/home`。
- `test_public_base_fail_closed_on_sandbox_domain`：未配置 `APP_PUBLIC_BASE_URL` 且 `CODER_PROJECTS_DOMAIN` 为沙箱地址时直接抛异常。
- `test_public_base_fail_closed_on_invalid_app_public_base`：`APP_PUBLIC_BASE_URL` 被配成沙箱地址时直接抛异常。

### 真实环境检查

| 检查项 | 结果 |
|--------|------|
| f7fbcc9 面板部署 | 用户确认 18:38:26 成功 |
| 公开站超星一键登录 | 成功进入 student/home |
| 当前问题 | URL 携带 `/sandboxes/<id>/proxy/8080/` 前缀；修复后需重新部署验证 |
| 代码中 `next` 参数来源 | 未找到；当前重定向不依赖 `next` 查询参数 |

### 未验证项

- 修复后的公开部署端到端验证：需重新部署当前 commit 后，确认地址栏为 `https://app-a398jfvyx9l6.cxiagents.com/student/home`。

---

## Round 3：修复公开部署后重定向 Location 被网关重写为沙箱前缀

### 目标

- 解决 `fbada33` 部署后，超星登录成功但浏览器地址仍为 `https://app-a398.../sandboxes/<id>/proxy/8080/student/home` 的问题。
- 用真实请求定位根因，不凭模拟测试断言修复成功。

### 真实证据

- `GET /auth/chaoxing/callback?code=invalid` 实际响应：
  - `location: /sandboxes/7ea65307-1b49-4bf4-bc59-742e79d7207e/proxy/8080/login?_sid=...`
- `GET /auth/chaoxing` 实际响应：
  - `location: https://auth.chaoxing.com/connect/oauth2/authorize?...redirect_uri=https%3A%2F%2Fapp-a398jfvyx9l6.cxiagents.com%2Fauth%2Fchaoxing%2Fcallback...`
- 根因判定：应用返回的根相对 `Location: /login` / `/student/home` 被平台网关重写为沙箱前缀；外部绝对 URL 未被重写。因此改为返回同源绝对 URL。

### 修改文件

| 文件 | 改动摘要 |
|------|----------|
| `platform_app/blueprints/auth.py` | 新增 `_public_redirect(endpoint)`：所有内部重定向生成 `https://APP_PUBLIC_BASE_URL/...` 同源绝对 URL；外站 OAuth 跳转仍使用普通 `redirect()` |
| `platform_app/__init__.py` | `propagate_sid` 改为用 `urlsplit` 严格校验 scheme/hostname/port，仅对根相对或同源绝对 URL 附加 `_sid`；拒绝 userinfo、外站、同名前缀恶意域名 |
| `tests/test_chaoxing_token_session.py` | 新增/更新 3 个测试：同源绝对附加 `_sid`、外站不附加、恶意域名不附加；所有 callback 测试断言 Location 为绝对 URL |
| `docs/DELIVERY_ACCEPTANCE.md` | 本文件 |

### 测试结果

```text
$ python3 -m pytest tests/test_chaoxing_callback.py tests/test_chaoxing_token_session.py -v
============================== 18 passed in 6.18s ==============================
```

### 未修复（记录，后续轮次处理）

- 部署前学生 QKD/NV 选关保存成功，部署后重登选关变 0：确认 SQLite 数据跨部署丢失；后续必须迁移到原生数据库持久化。
- AI 在 QKD 页问公开原理返回“服务不可用”，否定句被误拦截：AI 服务与提示词策略需后续修复。

### 部署状态

- 本 Agent 无原生部署命令。
- 已准备可部署 commit，提交 hash 见下一条交付记录。
- 部署后真实复测：确认登录后地址栏为 `https://app-a398jfvyx9l6.cxiagents.com/student/home`。

---

## 历史修复（已包含在当前工作区，待随本轮 commit 一起进入部署）

| 修复 | 证据 |
|------|------|
| 超星回调 URL 跳沙箱 | `auth.py::_app_public_base()` 与 `tests/test_chaoxing_callback.py` 5 项测试通过 |
| 首页登录 405 | `login.html` 表单显式 `action="{{ url_for('auth.login') }}"` |
| 400 CSRF token missing | `base.html` 改用 `<meta name="sid">` 传递 `_sid`，`sid.js` 从 meta 读取 |

---

## Round 4：移除超星 SSO 学生默认自动入课，修复未授权访问边界

### 目标

- 移除 `chaoxing_callback` 中学生首次登录无 enrollment 时自动加入最早课程的逻辑。
- 学生课程成员关系必须仅由教师通过学生管理/名单导入显式授权。
- 保留正常登录流程：已有 enrollment 的学生/教师 SSO 登录后仍可进入对应首页。
- 不修改远端 RLS、角色、已有业务数据；仅做 `auth.py` 局部安全修复。

### 根因

原代码在 `chaoxing_callback` 中判断学生无 enrollment 时，自动查询最早课程并写入一条 `Enrollment` 记录。这会导致任何首次通过超星 SSO 登录的学生默认进入系统课程，绕过教师授权，存在跨课程/未授权访问风险。

### 修改文件

| 文件 | 改动摘要 |
|------|----------|
| `platform_app/blueprints/auth.py` | 删除自动加入最早课程的 `Enrollment` 创建逻辑；改为：学生无 enrollment 时 flash 提示并跳转回登录页，不建立已登录会话 |
| `tests/test_chaoxing_token_session.py` | 新增/调整 3 个回归测试：无 enrollment 学生被拒绝且不写入 enrollment、已有 enrollment 学生正常登录且关系不变、仅授权 course1 时不会自动加入 course2；token 存储与注销测试改用教师身份，避免受 enrollment 规则影响 |
| `AGENTS.md` | 补充“学生课程成员关系必须由教师显式授权；超星 SSO 不再自动加入默认课程” |
| `docs/CHAOXING_CODER_PLAYBOOK.md` | 在“认证与权限边界”中记录 enrollment 授权规则与无 enrollment 登录行为 |
| `TEACHER_LOCAL_DEPLOYMENT_GUIDE.md` | `enrollments` 表“正常修改方式”增加“超星 SSO 不会自动创建” |
| `docs/DELIVERY_ACCEPTANCE.md` | 本文件 |

### 测试结果

```text
$ python3 -m pytest tests/test_chaoxing_token_session.py tests/test_chaoxing_callback.py -v
============================== 30 passed in 8.29s ==============================
```

新增/调整关键测试：
- `test_sso_student_without_enrollment_is_rejected`：无 enrollment 学生 SSO 登录后跳转 `/login`，不建立 `user_id` 会话，不为该 SSO 用户创建 enrollment。
- `test_sso_student_with_existing_enrollment_keeps_it`：通过学号元数据匹配到已导入名单的学生，已有 enrollment 正常登录，enrollment 不变，不额外创建 `cx_` 账号。
- `test_sso_student_does_not_auto_join_second_course`：学生仅被授权加入 course1 时，SSO 登录不会自动加入 course2。

### 部署状态

- 本变更仅涉及本地 SQLite 业务逻辑，不修改 Supabase RLS/角色/已有数据。
- 建议部署前确认：公开实例 `runtime/` 持久化契约；否则 SQLite 数据仍可能跨部署丢失。

---

## 已知阻塞（需用户/平台确认）

1. **公开实例 SQLite/上传目录跨部署是否持久化**——确认前不应覆盖线上。
2. **真实超星教师 + 两名学生账号**——用于下一轮真实角色权限验收；若无法提供，相关测试标记为未验证。
