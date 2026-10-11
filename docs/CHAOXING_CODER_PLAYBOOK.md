# 超星/Coder 平台接入与运维手册

> 本手册记录项目与超星、Coder 平台交互的**已验证规则、未验证能力与已知阻塞**。
> 来源：官方技能文档（`supabase-auth`、`supabase`） + 沙箱/公开环境实测。

## 1. 架构与运行配置

### 1.1 应用入口

- `app.py` 读取 `DEPLOY_RUN_PORT` 启动 Flask。
- `.coder` 部署脚本：
  - `scripts/build.sh`：重建 `.venv`（如可用）并安装 `requirements.txt`。
  - `scripts/start.sh`：强制 `APP_ENV=preview`，执行 `python3 app.py`。
- 因此**当前公开部署实际使用 `.env.preview`** 与 SQLite（`runtime/platform.db`）。

### 1.2 受信任公开域名

- 超星 OAuth 回跳地址（`redirect_uri`）必须指向浏览器可访问的公开域名。
- 配置优先级（代码见 `platform_app/blueprints/auth.py::_app_public_base`）：
  1. `APP_PUBLIC_BASE_URL`（显式公开域名，公开部署必填）
  2. `CODER_PROJECTS_DOMAIN`（平台注入域名，拒绝沙箱/内部地址）
  3. `request.url_root`（仅本地兜底）
- fail closed：`APP_PUBLIC_BASE_URL` 或 `CODER_PROJECTS_DOMAIN` 为沙箱、`internal`、`localhost`、带端口地址时直接抛异常，避免把沙箱地址作为公开回跳。
- 当前 `.env.preview` 已设置：`APP_PUBLIC_BASE_URL=https://app-a398jfvyx9l6.cxiagents.com`。

### 1.3 会话机制

- 平台代理会剥离 `Set-Cookie` 与 `Cookie`，因此使用 URL 票据 `_sid`。
- `_sid` 本身不是 JWT，只是指向 `app_sessions` 表行的随机 id。
- `TicketSessionInterface` 把 session 数据（包括超星 access/refresh token）存在服务端 SQLite，浏览器只持有 `_sid`。
- 平台公开/预览代理可能把沙箱路由前缀写入 WSGI `SCRIPT_NAME`；`_SandboxProxyPrefixStripper` 会同时清空 `SCRIPT_NAME` 与 `PATH_INFO` 中的 `/sandboxes/<id>/proxy/<port>`，确保 `url_for()` 生成的重定向与页面链接保持根路径。
- 为避免平台网关把根相对 `Location` 重写为沙箱前缀，应用内部重定向使用 `_public_redirect()` 生成同源绝对 URL（`https://APP_PUBLIC_BASE_URL/...`）。
- `propagate_sid` 仅对根相对 URL 或与 `APP_PUBLIC_BASE_URL` 同源的绝对 URL 附加 `_sid`；用 `urlsplit` 校验 scheme/hostname/port，拒绝 userinfo、外站、同名前缀恶意域名。外站 OAuth 跳转不附加 `_sid`。

## 2. 认证与权限边界

### 2.1 超星 OAuth 服务端流程

| 步骤 | 端点 | 说明 |
|------|------|------|
| authorize | `GET /v1/api/coder/proxy/auth/chaoxing-oauth/authorize-url` | 后端调，返回 `authorizeUrl`，浏览器顶层跳转 |
| exchange | `POST /v1/api/coder/proxy/auth/chaoxing-oauth/exchange` | 后端用 `code` + `projectId` 换取 Supabase session JSON |
| 用户校验 | `GET {CODER_SUPABASE_URL}/auth/v1/user` | 后端用 access_token 调 Supabase Auth 端点校验身份 |

- 身份认定**不再依赖本地未验签 decode JWT**，改由 Supabase Auth `/auth/v1/user` 返回的 `user_metadata.cxid` / `realname`。
- `access_token` / `refresh_token` 只写入服务端 `app_sessions.data`，不进入 URL、不写入浏览器可读 cookie、不输出日志。
- 学生课程成员关系（`enrollments`）必须由教师通过学生管理/名单导入显式授权；超星 SSO 不再自动加入任何默认课程。
  - 无 enrollment 的学生首次登录时，系统提示“你尚未被加入任何课程”并跳转回登录页，不建立已登录会话。
  - 已存在 enrollment 的学生 SSO 登录后正常进入学生首页，且 enrollment 不会被修改或扩展。
- 注销（`/logout`）执行 `session.clear()`，一并清除令牌。

### 2.2 下游 Data API 契约

- Data API（PostgREST）需要 `Authorization: Bearer <user JWT>` + `apikey: <anon key>` + `X-Instance-ID: <tenant id>`。
- 当前代码已实现 `_verify_access_token()` 与 `_refresh_access_token()` 两个 helper，用于在服务端校验/刷新用户 JWT。
- **尚未实现**业务代码通过 Data API 读写内置 Supabase 表；当前业务 CRUD 仍走 SQLAlchemy + SQLite。

### 2.3 安全限制

- 不使用 `SERVICE_ROLE_KEY`。
- 不放宽 `anon` 对业务表的权限。
- 不在日志/响应中输出 access_token / refresh_token / anon_key / tenant_id。

## 3. 知识库与模型

### 3.1 知识库

- `list_knowledge_base` 此前返回 `[]`；用户提到新知识库 ID 3848918 已可用，但**本轮未接入业务逻辑**。
- 接入方式待后续按 `knowledge` skill 实现。

### 3.2 Storage

- `storage` skill 目录为空，**私有对象/签名下载能力未确认**。

### 3.3 内置模型

- 当前 AI 服务走 `AI_BASE_URL/AI_API_KEY`（OpenAI 兼容端点），尚未迁移到平台内置模型。

## 4. 部署与回滚

### 4.1 部署工具

- `coder --help` 无 `deploy` 命令；公开部署需通过界面面板完成。
- 本 Agent 无法直接执行公开部署。

### 4.2 数据保留风险

- `scripts/build.sh` / `scripts/start.sh` 不删除 `runtime/`。
- `create_app()` 使用 `Base.metadata.create_all()`（幂等建表），不会 drop 旧表。
- **但未确认**：公开实例 `runtime/` 是否挂载持久卷、部署新版本时是否复制/复用该目录。
- 在持久卷契约确认前，**不应覆盖公开实例**，否则存在 SQLite 与上传文件丢失风险。

### 4.3 回滚版本

- 当前可部署 commit：见 `DELIVERY_ACCEPTANCE.md` 最新一轮记录。
- 线上当前版本：`fb7cccfe`（由用户面板显示）。

## 5. 常见问题

| 现象 | 根因 | 处理 |
|------|------|------|
| 超星授权后跳进沙箱地址 | `request.url_root` 被代理注入的 `X-Forwarded-Host` 污染 | 配置 `APP_PUBLIC_BASE_URL` 为公开域名 |
| 405 Method Not Allowed | 首页 `/` 表单调到当前 URL `/`，而 `/` 只接受 GET | 表单显式 `action="/login"` |
| 400 CSRF token missing | CSP 拦截内联 `window.__SID`，`_sid` 未回传 | 改用 `<meta name="sid">` 传递票据 |
| 教师被识别为学生 | 超星元数据缺少教师关键词/单位号 | 检查 `_identity_diagnostic` 脱敏日志后补充判定规则 |

## 6. 未验证与阻塞

| 项 | 状态 | 说明 |
|----|------|------|
| Data API 真实用户 JWT 允许/拒绝场景 | **未验证** | 需要完成一次真实超星登录，获取 access_token 后测试 RLS |
| 公开环境持久卷/跨部署数据复制 | **未知** | 平台未提供官方契约，是覆盖公开部署的唯一阻塞 |
| Storage 私有对象/签名下载 | **未确认** | `storage` skill 目录为空，无官方模板 |
| 内置模型调用 | **未接入** | 当前仍用外部 OpenAI 兼容端点 |
| 全量数据迁移到内置 Supabase | **未开始** | 需先确认认证桥接、RLS、Storage 方案 |
