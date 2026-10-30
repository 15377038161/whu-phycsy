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
- 平台部署构建/运行镜像是 Node 基底（`node:24-bookworm-slim`，由 `.coder` 的 `requires` 决定），无系统 Python；部署运行时走 nextjs-v3 profile 的 Next.js standalone 契约（`.next/standalone`+`node server.js`，非 root `node` 用户）。`scripts/build.sh` 构建期组装自包含 payload（vendored CPython + vendor-py 依赖 + Flask 源码 + server.js），`scripts/standalone-server.js` 为运行时入口，`scripts/start.sh` 为备选入口，详见 `DEPLOY_ADAPTATION.md` FAQ。
- payload 运行时（`standalone-server.js`/`start.sh`）**无条件强制 `APP_ENV=preview`**：平台部署环境常注入 `APP_ENV=production`，会触发 `create_app` 的生产门控（无 PostgreSQL 即 `RuntimeError`、生产必须显式合法公开域名）导致容器启动即失败；payload 为自包含 SQLite，preview 是唯一可用模式。健康探针除 `/health`、`/ready` 外提供 K8s 常用别名 `/healthz`、`/readyz`（同响应）。
- 交付/排障见 `DEPLOY_ADAPTATION.md`。

## 内置数据库接入契约（Supabase / Data API）

- 数据访问必须走平台内置库的 REST/Data API（PostgREST），**禁止 SQLAlchemy/psycopg 直连内置库**；
  现有 `db.py` 的 SQLAlchemy 直连暂仅服务 SQLite/外部 PostgreSQL 预览。
- 建表即迁移：schema 定义在 `db-schema/src/schema.ts`（勿手写 SQL），生成后 `db_execute` 执行；
  执行前必须移除外键 `REFERENCES "public".` 前缀，并在同文件末尾追加最小 `REVOKE/GRANT`。
- 所有业务表必须 `ENABLE ROW LEVEL SECURITY`；Data API 客户端必须带 `X-Instance-ID` 头，只用 anon key，
  禁止 service role。已建服务端封装：`platform_app/supabase_client.py` 提供 `auth_get_user(jwt)`、
  `refresh_access_token(refresh_token)`、`data_api_request(method, path, jwt)`，均通过 `httpx`
  直接调用 Supabase Auth/Data API，不持有 service role，不本地 decode JWT。
- 身份映射：超星 OAuth 登录成功后，服务端把 Supabase `access_token` / `refresh_token` 存入服务端
  `app_sessions` 表（不在 URL/前端/日志中暴露），并通过 `auth_get_user()` 实时校验；本地 `User` 的
  查找只使用 Supabase Auth 已验证顶层身份键（`verified_user.id`/`sub`），匹配 `cx_<identity>` 用户名
  或教师预先授权的 `User.chaoxing_cxid`。`user_metadata` 中的姓名、学号、自由关键词不再用于匹配或
  绑定名单用户，防止用户通过可编辑元数据接管他人账号。
- 同一超星身份键若同时命中多个本地账号（如 `cx_<identity>` 用户名与另一账号的 `chaoxing_cxid`
  同时匹配），SSO 登录会被拒绝并提示绑定冲突，避免 OR 查询顺序带来的不确定性。
- `chaoxing_cxid` 是**不可由学生自行编辑的身份绑定键**。若账号已绑定非空 `chaoxing_cxid` 且与
  当前 SSO 身份不一致，登录会被拒绝，防止重绑到其他身份。展示资料（姓名/头像/手机号/学号）在
  SSO 返回非空值时以超星数据为准覆盖（含名单账号，见 `test_sso_roster_profile_synced_from_sso_metadata`）；
  学号/手机号/姓名仅作展示字段，不参与身份匹配或绑定。
- 学生课程成员关系（`enrollments`）**必须由教师通过学生管理/名单导入显式授权**；超星 SSO 首次登录
  自动注册为学生账号（`cx_<identity>`，随机密码，仅可经 SSO 登录）并完成绑定（写审计
  `login.chaoxing_auto_register` + `login.chaoxing`），但**不自动加入任何课程**，学生端空态展示。
  自动注册仍不依据 `user_metadata` 匹配既有名单账号（防接管不变）：元数据中的姓名/头像/学号/手机号
  仅作展示字段同步到新账号（头像未返回时按 cxid 派生 `photo.chaoxing.com/p/<cxid>_80`）。教师预导入的名单学生（用户名非 `cx_` 开头）若无 enrollment，仍提示
  “你尚未被加入任何课程”并拒绝登录；自动注册的新学生不受此限制。
- 教师身份（`users.role='teacher'`）**仅由本地数据库的合法授权记录决定**。超星 SSO 登录时，
  `user_metadata`、单位号、自由关键词均不得用于授予或升级教师角色；`platform_app/blueprints/auth.py`
  中的 `_detect_chaoxing_role()` 固定返回 `student`，首次登录自动注册的新账号也恒为 `student`。
  已有本地 active teacher 通过 SSO 登录时保留原角色并进入教师首页；未授权用户即使元数据含
  `teacher`/`admin`/单位号 `1385` 等字段，也仅自动注册为学生账号（绝不创建 teacher），可登录
  学生端但看不到任何课程，直到教师将其导入名单。
- 教师授权的两条合法路径（均写审计事件 `member.promote_teacher`，幂等）：
  1. 启动预置：`create_app` 在 `APP_ENV ∈ {preview, production}` 且非测试时调用
     `services/accounts.ensure_initial_teachers()`，按 `TEACHER_CXIDS` 环境变量（逗号分隔，
     默认 `238792026,167050732,54837690`）创建 `username=cx_<uid>`、`chaoxing_cxid=<uid>`、
     `role=teacher`、`active=True` 的占位教师；本人首次 SSO 登录自动补全实名/头像。
  2. 教师自助：教师端“班级与学生”页“添加教师”弹窗（`POST /teacher/students/promote-teacher`，
     受 `@role_required('teacher')` + CSRF 保护）调用 `services/accounts.promote_member_to_teacher()`；
     已存在绑定账号直接提升+激活，不存在则创建占位教师。
- 服务端诊断端点（仅已登录用户可访问，受全局 CSRF 保护）：
  - `POST /api/diag/auth`：使用当前会话中的用户 JWT 调用 `/auth/v1/user`，返回环境状态、认证状态、
    脱敏后的 `auth.uid()` 与本地用户映射关系，不返回 token 或完整 JWT。
  - `POST /api/diag/data`：使用用户 JWT 查询 Data API 中 `cxid = 当前用户` 的行，验证 RLS 与权限，
    仅返回脱敏字段与状态。
- SECURITY DEFINER 审计结论：租户内存在 `app_admin_set_role` 等 SECURITY DEFINER 函数，已授权
  `authenticated` 执行；该函数内部强制 `current_user = 'admin'` 且先校验调用者角色为 admin，
  不存在普通用户通过 EXECUTE 越权提权的风险。后续新增 SECURITY DEFINER 函数必须遵循同样模式：
  最小权限、内部角色校验、仅授权必要角色 EXECUTE。
