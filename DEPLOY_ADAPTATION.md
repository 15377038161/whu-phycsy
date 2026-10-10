# 部署适配与运维手册 (Deployment Adaptation & Ops)

本文档记录本仓库（武大量子实验平台，Flask）在当前 coder/托管沙箱平台上的部署适配要点、
运行方式、运维手段与常见问题。核心业务规则以 `AGENTS.md`、`ARCHITECTURE.md` 为准。

## 1. 技术栈与依赖兼容性（已验证）

- 运行环境：Python 3.11（沙箱系统 `python3.11.2`；Dockerfile 使用 `python:3.11-slim`）
- 关键依赖（Python 3.11 下已全部 import 通过）：
  Flask≥3.0、gunicorn≥23（实测 26.2.0）、SQLAlchemy≥2.0、psycopg[binary]≥3.2、
  python-docx、openpyxl、xlrd、pypdf、reportlab、httpx、python-dotenv。
- 配置载体：`.coder`（TOML，平台启动依据）在仓库根 `/workspace/projects/`，指向 Flask 子项目 `projects/`。

## 2. 运行方式（平台）

- 端口：一律从 `DEPLOY_RUN_PORT` 读取，禁止硬编码 `5000`。`app.py` 与 `scripts/http_run.sh` 已支持。
- 多环境 dotenv：应用按 `APP_ENV` 自动加载 `.env` → `.env.<APP_ENV>` → `.env.local`
  （`platform_app/__init__.py::_load_env_files`）。平台注入的环境变量优先级最高（override=False）。

### 2.1 超星 OAuth 回跳地址（公开部署必配）

超星一键登录的回跳 `redirect_uri` 由 `platform_app/blueprints/auth.py::_app_public_base()` 生成，
用于浏览器授权后跳回应用，必须指向**用户浏览器可访问的公开域名**，与后端直连超星认证代理的
`_chaoxing_auth_base()`（走 `CODER_AUTH_PROXY_URL` 或 `request.url_root`）严格区分。

公开部署的代理会把 `X-Forwarded-Host` 写成内部沙箱地址（如 `sandbox-xxx-8080.cxiagents.com`），
而 `ProxyFix` 配置了 `x_host=1` 会信任该头，导致 `url_for(_external=True)` 生成沙箱回跳地址、
浏览器授权后跳进沙箱而非公开域名。因此回跳地址**绝不依赖 `request.url_root`**，按以下优先级取值：

1. `APP_PUBLIC_BASE_URL` —— 显式配置的公开域名（公开部署必填，如 `https://app-xxx.cxiagents.com`）；
2. `CODER_PROJECTS_DOMAIN` —— 平台注入的对外访问域名；
3. `request.url_root` —— 仅本地开发（无任何配置）兜底。

启动阶段会解析一次并缓存到 `app.config["APP_PUBLIC_BASE_URL"]`：
- 生产环境（`APP_ENV=production`）必须显式配置合法公开域名，否则启动即失败；
- 预览/开发环境若遇到沙箱/内部域名，会回退到 `http://localhost:5000`，保证非 OAuth 页面可正常启动；
- 实际发起超星 OAuth 时，请求上下文会再次严格校验，非法域名仍会直接报错，防止把内部地址泄露给浏览器。

严禁在代码中硬编码任何域名，也严禁把开发/预览沙箱地址写入 `.env.production`。
- 预览：`APP_ENV=preview` + SQLite（`runtime/platform.db`），无需外部数据库即可启动。
- 生产：`APP_ENV=production` + `DATABASE_URL=postgresql+psycopg://...`（生产强制 PostgreSQL）。

启动/停止（平台由 `.coder` 的 `[dev]/[deploy].run` 拉起，无需手工执行）：
```bash
python3 -m flask run --host=0.0.0.0 --port="${DEPLOY_RUN_PORT:-5000}"   # dev
python3 -m gunicorn --bind 0.0.0.0:"${DEPLOY_RUN_PORT:-5000}" --workers 2 --timeout 120 app:app  # prod
```

## 3. 健康检查

- `GET /health` → `{"status":"ok"}`（进程存活，200）。
- `GET /ready` → `{"status":"ready","checks":{database,files,ai}}`；任一不满足返回 `503`。
  - `database`：`SELECT 1` 探活；
  - `files`：`DATA_DIR` 可写；
  - `ai`：AI 端点连通（未配置 `AI_*` 时为 `false`，不影响页面，但 `/ready` 会 `503`）。
- 探活建议：部署流水线用 `/ready`；纯存活检测用 `/health`。

## 4. 日志规范

- 结构化 stdout/stderr 日志，级别由 `LOG_LEVEL` 控制（默认 `debug`）。
- 每个请求一条访问日志（`platform_app/logging_utils.py`）：
  `request_id=… method=GET path=/health status=200 duration_ms=0.2`，不记录认证头/敏感参数。
- 响应头返回 `X-Request-ID` 便于日志关联；异常请求记录完整堆栈到 stderr。
- 生产建议 `LOG_LEVEL=info`；SDK/集中采集直接消费 stdout。

## 5. 优雅关闭

- gunicorn 收到 `SIGINT/SIGTERM` 后先停止接收新连接、等待在途请求完成再退出，天然支持滚动/无停机部署。
- 每次请求的 DB 会话经 `teardown_appcontext` 自动 `remove()`，无连接泄漏。

## 6. 安全加固（已启用）

- 强制 HTTPS 安全头：`Strict-Transport-Security`（production）、`X-Content-Type-Options: nosniff`、
  `Referrer-Policy`、`Permissions-Policy`、`X-Permitted-Cross-Domain-Policies`、CSP（含 Pyodide 源白名单）；移除 `Server` 头。
- iframe 嵌入策略：默认 `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`；
  需要被平台/门户嵌入时，显式设置环境变量 `PLATFORM_FRAME_ANCESTORS=https://portal.example.com,https://lms.example.edu`（逗号分隔），
  此时切换为 `X-Frame-Options: SAMEORIGIN` 并将合法父源加入 `frame-ancestors`。沙箱/内部/本地地址会被过滤，不会自动授权。
- 会话：`HttpOnly`、`SameSite=Lax`、production 下 `Secure`。
- 认证：scrypt 密码哈希、全局 CSRF 校验、登录失败 5 次/5 分钟锁定（返回 429）与审计日志。
- 生产 `DEBUG` 恒为 False（`APP_ENV=production`），不暴露调试信息。

## 7. 数据库：预览 → 生产切换

1. 预览（沙箱）：保持 `APP_ENV=preview`，自动使用 SQLite（`runtime/platform.db`），`create_app` 幂等建表并 seed 演示账号。
2. 生产接入真实 PostgreSQL：
   - 将 `.env.production.example` 复制为 `.env.production`；
   - 设置 `APP_ENV=production` 与 `DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:5432/wuda_quantum`；
   - 配置 `FLASK_SECRET_KEY`（≥32 随机字节）与 `AI_*` 等；
   - 首次启动 `create_app` 会自动执行幂等 schema migration（`Base.metadata.create_all` + `migrate_schema`）。
3. 应用启动 `APP_ENV=production` 且 `DATABASE_URL` 非 PostgreSQL 时会直接拒绝启动（防误用 SQLite 上线）。

## 8. 部署关键节点检查清单

- [ ] Python 3.11 可用、`requirements.txt` 安装成功（`python3 -m pip install --user --break-system-packages -r requirements.txt` 沙箱内）
- [ ] 根目录 `.coder` 存在，`[deploy].run` 读取 `DEPLOY_RUN_PORT`
- [ ] 生产 `DATABASE_URL` 为 PostgreSQL，`APP_ENV=production`，`FLASK_SECRET_KEY` 强随机
- [ ] 生产 `APP_PUBLIC_BASE_URL` 为合法公开域名（如 `https://app-xxx.cxiagents.com`），非沙箱/内部地址
- [ ] 需要 iframe 嵌入时，已配置 `PLATFORM_FRAME_ANCESTORS` 并验证 `frame-ancestors` 响应头
- [ ] `curl /health` = 200；`curl /ready` = 200（AI 已配置时）
- [ ] 演示账号登录/首密码修改流程通过
- [ ] 登录页/首页在 HTTPS 下 `Secure` Cookie 生效，响应无 CSP 违规
- [ ] `python scripts/verify_project.py` 与 `pytest -q` 通过
- [ ] 日志无敏感信息（无 Key/Secret/上传文件/真实报告）
- [ ] 反向代理将真实协议与客户端地址传给应用（可信代理场景）

## 9. 常见问题（FAQ）

- `/ready` 返回 `503`：通常是 `ai:false`（未配置 `AI_*`）或无 DB；页面功能不受 `ai` 影响。
- 生产启动即报 `Production requires PostgreSQL`：`DATABASE_URL` 未指向 PostgreSQL，请配置后重启。
- `PEP 668 externally-managed-environment`：沙箱需加 `--break-system-packages --user`；生产走 Docker 不受影响。
- 依赖更新失败：先看 `LOG_LEVEL` 对应的运行日志；`gunicorn` 日志在 stdout。
- 端口被占：确认 `DEPLOY_RUN_PORT` 对应进程，`ss -lptn 'sport = :<port>'` 定位后按需重启。

## 10. 内置数据库接入（Supabase / Data API）

平台内置数据库为 PolarDB Supabase 多租户形态，**不支持 SQLAlchemy/psycopg 直连**，只通过
REST/Data API（PostgREST）读写。接入信息由平台注入到沙箱进程环境：

| 变量 | 用途 |
|------|------|
| `CODER_SUPABASE_URL` | REST/Data API 基址（如 `https://supabase-api.cxiagents.com`） |
| `CODER_SUPABASE_ANON_KEY` | 低权限 anon key（公开，安全性依赖 RLS） |
| `CODER_SUPABASE_TENANT_ID` | 租户路由，必须放入 `X-Instance-ID` 头 |

### 当前完成状态

- **建表迁移已执行**：全部 17 张业务表已在内置库创建（`db-schema/drizzle/0000_sour_bedlam.sql`，
  由 Drizzle 生成并在执行前移除外键 `"public".` 前缀）。
- **RLS 审计通过**：系统表审计返回空，`users`、`reviews`、`submission_revisions` 等所有业务表均
  `ENABLE ROW LEVEL SECURITY`；暂未开放的表默认拒绝（deny-by-default）。
- **最小 GRANT**：`REVOKE ALL` 后仅 `authenticated` 获得最小读写权限，`anon` 一律不授予业务表
  （Data API 用真实 anon key 访问 `users`/`experiments` 已实测返回 `42501 permission denied`）。
- **数据访问脚手架**：新增 `platform_app/supabase_client.py`（httpx + `X-Instance-ID` + JWT 透传，
  仅用 anon key，禁止 service role），供认证接入后替换 `db.py` 的 SQLAlchemy 直连使用。

### 认证前置要求（未完成，待工具可用）

平台 RLS 行级安全依赖 **Supabase Auth 签发的用户 JWT**（`auth.uid()`）。本仓库当前仍是 Flask 自建
登录（`users` 表 + Flask `session`），**不产生 Supabase JWT**；故「authenticated 允许场景」的
Data API 验证与 `services`/`blueprints` 迁移必须等认证接入后才可完成。接入认证需要
`npx coder-coding-ai supabase auth get-config`（该 CLI 在现沙箱缺失，详见下文「堵点」）。

### 接入路线（认证工具恢复后按序执行）

1. 运行 `npx coder-coding-ai supabase auth get-config`，确认启用的登录方式；
2. 将 Flask 登录/会话改造为 Supabase Auth，登录后请求携带 `Authorization: Bearer <JWT>`；
   （OpenSandbox 边界已重命名为 `x-sandbox-authorization`，后端从该头解析）
3. 用真实用户 JWT 通过 Data API 验证 RLS「允许」与「拒绝」场景；
4. 将 `services/` 与 `blueprints/` 的 SQLAlchemy 会话替换为 `supabase_client.get_supabase(jwt)`；
5. 用 Drizzle 为 RLS 设计具体 Policy（现状为默认拒绝），再生成新迁移执行。

### 建表迁移维护

- Schema 定义：`projects/db-schema/src/schema.ts`；配置：`drizzle.config.ts`。
- 重新生成：`cd projects/db-schema && pnpm drizzle-kit generate`，核对外键前缀后追加 GRANT 再执行。
- 已执行迁移不可修改；RLS/GRANT 变更必须生成新迁移文件。
- 该目录仅用于生成建表 SQL，不参与 Flask 运行与交付包。