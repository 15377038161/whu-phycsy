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

- 强制 HTTPS 安全头：`Strict-Transport-Security`（production）、`X-Frame-Options: DENY`、
  `X-Content-Type-Options: nosniff`、`Referrer-Policy`、`Permissions-Policy`、
  `X-Permitted-Cross-Domain-Policies`、CSP（含 Pyodide 源白名单）；移除 `Server` 头。
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