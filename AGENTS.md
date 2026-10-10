# AI 修改规则

修改任何代码前，必须完整阅读 `ARCHITECTURE.md`。

1. 唯一 UI 是 `templates/` + `static/quantum-platform.css`；禁止恢复旧页面、旧 CSS 或并行 UI。
2. 唯一正式实验是离子阱、量子密钥分发、量子纠缠、金刚石量子计算机、单像素光子成像。
3. 生产业务数据只使用 PostgreSQL；禁止回退到 `data.json`、SQLite 或 Supabase。
4. 发布版本、提交修订、AI 评估、教师审核和文件均不可原地覆盖。
5. 教师评分和内部评语不得进入任何学生响应或学生报告。
6. 学生代码只在浏览器 Pyodide 中运行，服务器绝不执行。
7. AI 客户端必须懒加载；不得恢复 Coze 或其它平台专有 SDK。
8. 不得删除 `source_docs/`、`static/fonts/simhei.ttf` 或报告依赖。
9. `.env.local`、Key CSV、真实报告、旧数据和上传文件不得进入交付包。
10. 修改后至少运行 `python scripts/verify_project.py` 和 `pytest -q`。

## 部署适配要点（平台）

- 部署入口为仓库根 `.coder`；对外端口一律读 `DEPLOY_RUN_PORT`，禁止硬编码 5000。
- 应用按 `APP_ENV` 加载 `.env` / `.env.<APP_ENV>` / `.env.local`，平台注入环境变量优先。
- 预览用 `APP_ENV=preview` + SQLite；生产必须 `APP_ENV=production` + PostgreSQL `DATABASE_URL`。
- 新增了 `platform_app/logging_utils.py`（结构化访问日志 + request_id），级别受 `LOG_LEVEL` 控制。
- 新增了 `platform_app/health_monitor.py`（启动自检 + 后台连接监控）：`create_app` 启动时同步校验核心依赖可导入、数据库可达、数据目录存在；随后守护线程周期性复查 database/files（`HEALTH_CHECK_INTERVAL_SECONDS`，默认 60s）与可选 AI（`HEALTH_AI_INTERVAL_SECONDS`，默认 300s）。快照经 `/health` 暴露，`/ready` 仅由 database+files 决定（AI 为可选增强，未配置不影响就绪，避免平台探针误判连接被拒）。
- 公开基址：启动时按 `APP_PUBLIC_BASE_URL` → `CODER_PROJECTS_DOMAIN` → `localhost` 解析并缓存到 `app.config["APP_PUBLIC_BASE_URL"]`；生产环境必须配置合法公开域名，预览/开发遇到沙箱/内部/本地域名会回退到 `http://localhost:5000` 以保证非 OAuth 页面可启动。校验使用 urlsplit（协议/hostname/端口/userinfo/path/query/fragment），并额外拒绝沙箱/内部/本地地址；超星 OAuth 回跳在请求时再次严格解析，非法域名直接报错，不会使用缓存的 localhost 生成 redirect_uri。
- iframe 嵌入：默认拒绝（`X-Frame-Options: DENY`，`frame-ancestors 'none'`）；只读取显式 `PLATFORM_FRAME_ANCESTORS`（逗号分隔），`CODER_PROJECTS_DOMAIN` 是应用自身域名，不会自动作为父源授权，也不擅自加入 `'self'`。每个父源必须是无 userinfo/path/query/fragment/通配符的 http(s) origin。
- 交付/排障见 `DEPLOY_ADAPTATION.md`。

## 内置数据库接入契约（Supabase / Data API）

- 数据访问必须走平台内置库的 REST/Data API（PostgREST），**禁止 SQLAlchemy/psycopg 直连内置库**；
  现有 `db.py` 的 SQLAlchemy 直连暂仅服务 SQLite/外部 PostgreSQL 预览。
- 建表即迁移：schema 定义在 `db-schema/src/schema.ts`（勿手写 SQL），生成后 `db_execute` 执行；
  执行前必须移除外键 `REFERENCES "public".` 前缀，并在同文件末尾追加最小 `REVOKE/GRANT`。
- 所有业务表必须 `ENABLE ROW LEVEL SECURITY`；Data API 客户端必须带 `X-Instance-ID` 头，只用 anon key，
  禁止 service role。已建脚手架：`platform_app/supabase_client.py`（`get_supabase(jwt)`，支持用户 JWT 透传）。
- 生产 RLS 行级安全依赖 Supabase Auth 的用户 JWT（`auth.uid()`）。本仓库仍为 Flask 自建登录，
  认证未接入前不得宣称完成数据迁移；接入需 `npx coder-coding-ai supabase auth get-config`（见 DEPLOY_ADAPTATION.md §10）。
