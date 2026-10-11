# 线上部署诊断报告

> 范围：AI/UI 安全修复版本 `da1d69e`（`codex/ai-ui-registered`）在线上环境的真实表现。
> 原则：只诊断、不改业务代码、不补数据、不输出密钥/令牌；所有结论标出证据来源或假设等级。

---

## 1. 版本对齐声明

| 项 | 值 | 证据 |
|---|---|---|
| 当前工作区 HEAD | `da1d69e` | `git log --oneline -1` |
| 线上登记可部署分支 | `codex/ai-ui-deploy` / `codex/ai-ui-registered` 均指向 `da1d69e` | `git branch -a --contains da1d69e` |
| 数据库候选分支 | `codex/db-candidate-d648d50` 指向 `d648d50` | 历史交付记录 |
| `.coder` 部署入口 | `[deploy] run = ["bash", "./scripts/start.sh"]` | `.coder/config.toml` |

本次诊断基于 `da1d69e` 的源码；`d648d50` 仅作为 Data API / RPC 改造的前瞻基线参与差异分析。

---

## 2. course_for_student / Supabase 调用路径差异（da1d69e vs d648d50）

### 2.1 共同未变部分

- `platform_app/services/experiments.py::course_for_student(session, student_id)` 在两个版本中**完全一致**：它只查询本地 SQLite 的 `Enrollment` 表，返回学生所属 `Course`。
- 因此首页、实验页、记录页等用于判断“有没有本地课程”的逻辑不受两个版本差异影响。

### 2.2 da1d69e 的选关路径

- `platform_app/services/progress.py` 提供旧的 `selection_summary(session, course, student_id, versions)`：
  - 读/写全部落在本地 SQLite `StudentExperimentProgress` 表；
  - 不依赖 Supabase Data API / PostgREST；
  - 也**不依赖** `users.auth_user_id`、`courses.external_ref`、`enrollments` 等远程表。
- `platform_app/blueprints/student.py` 在首页、选关页调用 `selection_summary(...)`。

### 2.3 d648d50 的选关路径（仅作前瞻性参考，尚未部署）

- `progress.py` 新增 `student_selection_summary` / `save_student_level_selection`：
  - 通过 `supabase_client.current_valid_token()` 取服务端 session 中的 `cx_access_token`；
  - 通过 `get_data_api_user_id(token, expected_auth_user_id=user.auth_user_id)` 把 JWT UUID 映射到远端 `users.id`；
  - 查询远端 `/enrollments?select=course_id&student_id=eq.{business_id}`；
  - 再按 `courses.external_ref` 匹配本地课程；
  - 写操作调用 `/rpc/app_atomic_set_student_selection`。
- 若该版本未来上线，空 `enrollments` 会直接触发 `missing_initialization: 学生未加入任何课程`。

### 2.4 关键结论

- **当前线上 `da1d69e` 的“课程映射缺失”提示，如果出现在选关或首页，只能来自本地 SQLite `Enrollment` 表为空**，与 Supabase Data API 无关。
- 如果线上页面提示的是 `missing_initialization` 字样，则说明线上实际部署的版本**不是** `da1d69e`，而是更接近 `d648d50` 或包含 Data API 选关改动的中间版本。
- 因此，**线上版本与登记版本不一致**是当前最高优先级的根因假设。

---

## 3. APP_ENV / start.sh 如何路由 SQLite vs PostgREST 后端

### 3.1 启动脚本

`scripts/start.sh`（.coder deploy 入口）：

```bash
export APP_ENV=preview
exec python3 app.py
```

它**强制**把 `APP_ENV` 设为 `preview`，无视外部 `.env` 中的 `APP_ENV=production`。

### 3.2 create_app 中的数据库路由

`platform_app/__init__.py::create_app`：

- `DATABASE_URL` 默认值：`sqlite:///{root}/runtime/platform.db`
- 仅当 `APP_ENV == "production"` 时强制要求 `DATABASE_URL` 以 `postgresql://` 或 `postgresql+psycopg://` 开头；否则启动失败。
- 由于 `start.sh` 强制 `preview`，线上容器一定走 **SQLite + `runtime/platform.db`**。

### 3.3 PostgREST / Data API 是否启用

Data API 调用在 `da1d69e` 中仅出现在 `platform_app/supabase_client.py` 封装层以及 `platform_app/blueprints/api.py` 的诊断端点 `/api/diag/auth`、 `/api/diag/data`。它们是否生效取决于平台是否注入了 `CODER_SUPABASE_URL`、`CODER_SUPABASE_ANON_KEY`、`CODER_SUPABASE_TENANT_ID`：

- 若注入完整：诊断端点可以与 Supabase Auth / PostgREST 通信；
- 若未注入：`_env_ok()` 返回 `False`，诊断端点返回 `missing_env`。

### 3.4 关键结论

- 线上 coder 部署默认是 **SQLite 本地数据库 + 可选 Supabase 诊断能力**。
- 若期望线上使用 PostgreSQL / 持久化课程映射，需要平台显式提供 `DATABASE_URL` 或持久卷；当前 `start.sh` 未配置。
- `runtime/platform.db` 是临时文件系统还是持久卷，决定学生课程映射、上传文件、报告草稿能否跨部署保留。**这仍是未验证项**。

---

## 4. 空 enrollments / 课程映射缺失诊断方案

### 4.1 需要回答的问题

1. 线上实际运行的版本到底是 `da1d69e` 还是包含 Data API 选关改动的版本？
2. 学生通过超星 SSO 登录后，本地 SQLite 是否写入了 `Enrollment` 行？
3. 若实际走的是 Data API 路径，远端 `enrollments` 为空是 RLS 过滤还是真无数据？

### 4.2 根因假设与验证方法（不改代码、不输出秘密）

#### 假设 A：线上部署版本 ≠ `da1d69e`

- **判断依据**：页面提示中出现 `missing_initialization` 或 `/api/level_selection` 返回 `error: "selection_unavailable"`。
- **验证**：
  1. 访问线上 `/static/quantum-platform.css` 或任意静态文件，通过响应头/ETag 与本地 `da1d69e` 构建产物比对（若平台提供版本头则更佳）。
  2. 调用 `/api/diag/auth` 与 `/api/diag/data`（需先登录），观察返回状态是否与 `da1d69e` 的 `_current_valid_token` 行为一致。
  3. 检查线上运行日志中 `chaoxing_callback` 后是否调用 `selection_summary` 还是 `student_selection_summary`。

#### 假设 B：线上是 `da1d69e`，但 SQLite `Enrollment` 表在每次部署后被重置

- **判断依据**：学生昨天能看课程，新部署后变成“未加入任何课程”。
- **验证**：
  1. 平台侧检查最近一次部署前后 `runtime/platform.db` 的 mtime / 文件哈希是否变化。
  2. 检查线上 `app.log` 中 `init_database` 或 `seed_defaults` 是否每次启动都打印“creating default admin/demo student”。
  3. 教师端重新导入一次班级名单后，学生再次登录，观察问题是否暂时消失。

#### 假设 C：走的是 Data API 路径，远端 `enrollments` 真无行

- **判断依据**：日志中出现 `GET /rest/v1/enrollments?...` 返回 `200 []`。
- **验证**：
  1. 线上日志搜索 `enrollments` 请求与响应体长度；
  2. 教师端确认已在 Supabase 侧完成“班级学生名单导入”或学生已加入课程；
  3. 通过平台 PolarDB 控制台（只读查询，不修改）执行：
     ```sql
     SELECT student_id, course_id FROM enrollments WHERE student_id = '<business_id>';
     ```
     注意：business_id 需从已登录用户的 JWT 经 `users.auth_user_id` 映射后取得，不可在诊断文档中记录真实值。

#### 假设 D：走的是 Data API 路径，RLS 策略过滤了 `enrollments`

- **判断依据**：同一业务 ID 用 service role 能查到行，用用户 JWT 查不到。
- **验证**：
  1. 线上仅能通过 Data API + 用户 JWT 测试；service role 不进入 Agent/应用。
  2. 平台运维可在 PolarDB 控制台执行：
     ```sql
     SELECT relrowsecurity FROM pg_class WHERE relname = 'enrollments';
     \d+ enrollments
     ```
     检查是否启用 RLS 及策略定义。
  3. 比较 `enrollments` 的 RLS 与 `users.auth_user_id` 的映射关系：策略通常要求 `student_id = auth.uid()` 或 `(select auth_user_id from users where id = student_id) = auth.uid()`。若策略与当前映射字段不一致，就会出现“有行但看不见”。

### 4.3 最小可复现检查清单

| # | 检查项 | 操作人 | 输出是否含秘密 |
|---|---|---|---|
| 1 | 线上容器内 `git rev-parse HEAD` | 平台运维/沙箱 | 否 |
| 2 | 线上 `app.log` 最近 50 行搜索 `selection_summary` / `student_selection_summary` / `missing_initialization` | 平台运维 | 否 |
| 3 | 线上 `/api/diag/auth` 与 `/api/diag/data` 在登录态下返回的状态 | 用户/教师 | 否 |
| 4 | 平台侧确认 `runtime/platform.db` 是否持久卷 | 平台运维 | 否 |
| 5 | PolarDB 只读查询 `enrollments` 行数与 RLS 状态 | 平台运维 | 否 |

---

## 5. AI 未就绪与部署版本/配置的关联

### 5.1 `da1d69e` 的 AI 配置逻辑

`ai_service.py::_config()`：

1. 优先读取平台原生模型变量：
   - `CODER_CODING_MODEL_BASE_URL`
   - `CODER_CODING_MODEL_API_KEY`
   - `CODER_CODING_MODEL`（默认 `doubao-seed-1-8-251228`）
2. 若原生模型变量完整，使用 `source=native`。
3. 若缺失，则尝试旧外部 AI 变量（`AI_BASE_URL`、`AI_API_KEY`、`AI_TEXT_MODEL`、`AI_VISION_MODEL`）；全部存在时使用 `source=legacy`。
4. 两者都缺失时抛出 `RuntimeError`：
   ```
   平台原生模型未配置，请设置 CODER_CODING_MODEL_BASE_URL 和 CODER_CODING_MODEL_API_KEY；
   当前缺少：...
   ```

### 5.2 与部署版本的关联

- `da1d69e` 是首个“优先平台原生模型”的版本。
- 如果线上部署的确实是 `da1d69e`，但平台未注入 `CODER_CODING_MODEL_*`，则 AI 服务直接不可用。
- 如果线上部署的是更早版本（如 `ef524fd` 之前），AI 可能仍走旧外部 AI 变量；但更早版本存在否定句拦截与证书 UI 问题。
- 因此，**“AI 未就绪”与“部署版本”是绑定的**：同一组环境变量，对不同 commit 意味着不同的可用性。

### 5.3 验证方法（不改代码、不输出秘密）

| # | 检查项 | 操作人 | 输出是否含秘密 |
|---|---|---|---|
| 1 | 线上容器环境变量 `CODER_CODING_MODEL_BASE_URL`、`CODER_CODING_MODEL_API_KEY` 是否存在（不输出值） | 平台运维 | 否（只输出存在/缺失） |
| 2 | 线上 `app.log` 搜索 `平台原生模型未配置` 或 `CODER_CODING_MODEL` | 平台运维 | 否 |
| 3 | 调用 `/api/teacher/ai` 或触发学生 AI 对话，观察返回是正常流式响应还是 500 / 503 | 用户/教师 | 否 |
| 4 | 若原生模型变量缺失，检查旧变量 `AI_BASE_URL`、`AI_API_KEY`、`AI_TEXT_MODEL`、`AI_VISION_MODEL` 是否存在 | 平台运维 | 否 |

### 5.4 建议

- 若平台原生模型变量已提供但 AI 仍报错，应检查线上 `app.log` 中 httpx 请求目标、状态码、响应摘要（不输出 key）。
- 若变量未提供且旧变量也不完整，需平台侧补充 `CODER_CODING_MODEL_BASE_URL` 与 `CODER_CODING_MODEL_API_KEY`。

---

## 6. 最小可验证诊断方案（不改代码、不输出秘密）

### 6.1 一次完整的线上诊断流程

1. **确认实际运行版本**
   - 平台运维进入线上容器执行：
     ```bash
     git rev-parse HEAD
     ```
   - 将结果与 `da1d69e` 比对；若不一致，所有后续诊断都需基于实际版本重新分析。

2. **确认后端模式**
   - 检查线上 `APP_ENV`：
     ```bash
     echo "$APP_ENV"
     ```
   - 检查数据库文件路径：
     ```bash
     ls -la runtime/platform.db
     ```
   - 预期（`da1d69e` + `start.sh`）：`APP_ENV=preview`，存在 `runtime/platform.db`。

3. **确认本地课程映射状态**
   - 在学生登录后，检查 SQLite：
     ```sql
     SELECT id, course_id FROM enrollments WHERE student_id = '<本地student_id>';
     SELECT id, name, external_ref FROM courses;
     ```
   - 若 `enrollments` 为空，说明本地课程映射缺失；问题在数据/导入流程，不在 Supabase。

4. **确认 Supabase 诊断端点状态**
   - 以学生身份登录后调用：
     ```bash
     curl -X POST https://<线上域名>/api/diag/auth
     curl -X POST https://<线上域名>/api/diag/data
     ```
   - 预期：`{"status":"ok"}` 或 `"missing_env"` / `"no_token"` / `"invalid"` / `"forbidden"`。
   - 若返回 `"forbidden"`，说明 JWT UUID 与远端 `users.auth_user_id` 未对齐，需要检查 `chaoxing_callback` 是否写入了 `auth_user_id`。

5. **确认 AI 配置状态**
   - 检查环境变量存在性（不输出值）：
     ```bash
     env | grep -E '^(CODER_CODING_MODEL|AI_)' | cut -d= -f1
     ```
   - 触发一次 AI 调用，查看 `app.log` 中是否有 `平台原生模型未配置` 或 httpx 错误。

6. **汇总输出模板**

   | 检查项 | 预期 | 实际 | 结论 |
   |---|---|---|---|
   | 运行版本 | `da1d69e` | ___ | ___ |
   | APP_ENV | `preview` | ___ | ___ |
   | SQLite 存在 | 是 | ___ | ___ |
   | 本地 Enrollment | 有行 | ___ | ___ |
   | /api/diag/auth | `ok` | ___ | ___ |
   | /api/diag/data | `ok` | ___ | ___ |
   | CODER_CODING_MODEL_BASE_URL | 已配置 | ___ | ___ |
   | CODER_CODING_MODEL_API_KEY | 已配置 | ___ | ___ |
   | AI 调用可用 | 是 | ___ | ___ |

### 6.2 安全红线

- 禁止在任何日志、聊天、文档中输出 `access_token`、`refresh_token`、`apikey`、`AI_API_KEY`、`CODER_CODING_MODEL_API_KEY`、完整 JWT 内容、真实 `student_id`、`auth_user_id`、`cxid`。
- 环境变量检查只输出“存在/缺失”或变量名，不输出值。
- 数据库查询只输出行数或布尔结论，不输出个人资料。

---

## 7. 需要平台侧配合的项

| # | 事项 | 优先级 | 原因 |
|---|---|---|---|
| 1 | 确认线上实际运行 commit | 高 | 决定所有诊断假设是否成立 |
| 2 | 提供线上 `app.log` / `console.log` 最近 100 行（脱敏） | 高 | 定位版本、AI、选关错误 |
| 3 | 确认 `runtime/platform.db` 与 `runtime/` 是否持久卷 | 高 | 决定课程映射与上传文件能否保留 |
| 4 | 确认 `CODER_CODING_MODEL_*` 是否已注入线上环境 | 高 | 决定 AI 是否可用 |
| 5 | 若走 Data API 路径，提供 PolarDB 只读查询结果（enrollments 行数、RLS 状态） | 中 | 区分 RLS 过滤与真无数据 |
| 6 | 批复 `0004_atomic_selection_rpc.sql` 执行方式 | 中 | 原子选关 RPC 落地的最后阻塞 |

---

## 8. 结论与建议

1. **版本一致性是当前最大风险**：如果线上出现 `missing_initialization` 或 `/api/level_selection` 返回 `selection_unavailable`，则线上版本大概率不是登记的 `da1d69e`，而是包含 Data API 选关改动的中间版本。应优先确认运行版本。
2. **AI 未就绪与原生模型变量强相关**：`da1d69e` 默认优先使用 `CODER_CODING_MODEL_*`；缺失时直接不可用。需平台侧确认是否已注入。
3. **课程映射缺失分两种场景**：
   - 若线上是 `da1d69e`：问题在本地 SQLite `Enrollment` 表为空或数据库未持久化。
   - 若线上是 Data API 版本：问题在远端 `enrollments` 无行或 RLS 策略过滤。
4. **下一步动作**：按第 6 节的最小可验证诊断流程收集证据；证据齐全后再决定是回滚版本、补环境变量、持久化数据库，还是推进 `0004_atomic_selection_rpc.sql` 的 PolarDB 控制台执行。
