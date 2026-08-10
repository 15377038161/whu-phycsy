# 武大量子实验平台教师本地部署与配置手册

适用版本：2026-08-07 交付版。本文面向需要在本地电脑、实验室服务器或校内服务器独立部署系统的教师与运维人员。

## 1. 交付包结构

解压后必须能看到以下关键文件：

| 路径 | 用途 | 是否可直接修改 |
| --- | --- | --- |
| `.env.example` | 配置模板，不含真实密钥 | 是，复制后修改 |
| `.env.production` | 实际运行配置；需自行创建，不进入代码仓库和交付包 | 是，严禁外传 |
| `docker-compose.yml` | PostgreSQL 与应用容器编排 | 外接数据库时修改 |
| `Dockerfile`、`requirements.txt` | 应用镜像与 Python 依赖 | 一般不修改 |
| `platform_app/models.py` | 全部数据库表和列的唯一代码定义 | 仅开发人员修改 |
| `platform_app/content.py` | 五项内置实验的初始内容与题库来源 | 仅通过新版本发布生效 |
| `platform_app/services/report_drafts.py` | 报告字段、章节和校验规则 | 仅开发人员修改 |
| `ai_service.py` | OpenAI 兼容模型调用入口 | 通常只改环境变量 |
| `templates/`、`static/` | 唯一网页界面 | 仅开发人员修改 |
| `scripts/verify_project.py` | 项目结构校验 | 部署前运行 |
| `scripts/package_docker.py` | 生成无密钥交付包 | 发布时运行 |

系统业务数据只使用 PostgreSQL。`runtime/platform.db` 仅是开发环境在没有配置 `DATABASE_URL` 时的本地 SQLite 兜底，生产环境设置 `APP_ENV=production` 后会拒绝使用 SQLite。

## 2. 部署前准备

### 2.1 推荐环境

- Windows 10/11：安装 Docker Desktop，启用 WSL 2 后端。
- Linux：安装 Docker Engine 与 Docker Compose v2。
- 建议至少 4 核 CPU、8 GB 内存、20 GB 可用磁盘。
- 浏览器建议使用最新版 Chrome、Edge 或 Firefox。
- 正式环境必须使用 HTTPS；只有临时内网预览可使用 `APP_ENV=preview`。

### 2.2 创建运行配置

在交付包根目录执行：

```powershell
Copy-Item .env.example .env.production
notepad .env.production
```

Linux 可执行：

```bash
cp .env.example .env.production
chmod 600 .env.production
```

`.env.production` 不得提交 Git、发送到群聊或放入交付 ZIP。

## 3. 数据库连接配置

### 3.1 使用交付包内置 PostgreSQL（推荐）

配置文件：项目根目录 `.env.production`。

填写示例：

```dotenv
APP_ENV=production
FLASK_SECRET_KEY=请替换为至少32字节的高强度随机字符串
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=首次初始化使用的强密码，至少12位
POSTGRES_DB=wuda_quantum
POSTGRES_USER=wuda
POSTGRES_PASSWORD=数据库强密码
```

参数说明：

| 参数 | 含义 | 填写要求 |
| --- | --- | --- |
| `POSTGRES_DB` | 数据库名 | 建议保留 `wuda_quantum` |
| `POSTGRES_USER` | 数据库账号 | 仅供应用连接，不建议使用超级用户 |
| `POSTGRES_PASSWORD` | 数据库密码 | 强随机密码；修改已运行实例前先完成数据库密码迁移 |
| `INITIAL_ADMIN_USERNAME` | 首次初始化教师账号 | 只在空数据库首次启动时使用 |
| `INITIAL_ADMIN_PASSWORD` | 首次初始化教师密码 | 生产环境至少 12 位；数据库已有用户后修改此项不会重置密码 |

`docker-compose.yml` 会自动拼接内部连接串：

```text
postgresql+psycopg://POSTGRES_USER:POSTGRES_PASSWORD@db:5432/POSTGRES_DB
```

其中 `db` 是 Compose 内部服务名，不是公网主机名。

### 3.2 连接学校已有 PostgreSQL

配置文件：项目根目录 `docker-compose.yml`。

找到 `services.app.environment.DATABASE_URL`，改为读取独立变量：

```yaml
environment:
  APP_ENV: ${APP_ENV:-production}
  DATABASE_URL: ${DATABASE_URL}
  DATA_DIR: /data
```

然后在 `.env.production` 添加：

```dotenv
DATABASE_URL=postgresql+psycopg://用户名:密码@数据库主机:5432/数据库名
```

连接参数：

| 连接部分 | 说明 |
| --- | --- |
| `postgresql+psycopg` | 必须保留，系统使用 SQLAlchemy + psycopg |
| 用户名/密码 | 需要建表、查询、插入、更新权限 |
| 数据库主机 | 可填校内 IP 或 DNS；容器内不能用 `127.0.0.1` 指代宿主机 |
| 端口 | PostgreSQL 默认 `5432` |
| 数据库名 | 建议独立库 `wuda_quantum` |

若数据库在 Windows 宿主机，可按环境使用 `host.docker.internal`；Linux 宿主机需使用可从容器访问的实际地址。防火墙只允许应用服务器访问数据库端口。

### 3.3 数据库验证、备份与恢复

启动后检查：

```powershell
docker compose --env-file .env.production ps
docker compose --env-file .env.production exec -T db pg_isready -U wuda -d wuda_quantum
Invoke-WebRequest http://127.0.0.1:5000/ready -UseBasicParsing
```

备份必须同时保存数据库与文件卷：

```powershell
docker compose --env-file .env.production exec -T db pg_dump -U wuda wuda_quantum > wuda.sql
docker run --rm -v wuda_app_files:/data -v ${PWD}:/backup alpine tar czf /backup/wuda-files.tgz -C /data .
```

恢复数据库：

```powershell
Get-Content .\wuda.sql -Raw | docker compose --env-file .env.production exec -T db psql -U wuda wuda_quantum
```

升级前必须先备份。发布版本、提交修订、教师审核和上传文件不可通过 SQL 原地覆盖。

## 4. 自定义模型替换

### 4.1 配置入口

唯一常规配置入口是项目根目录 `.env.production`：

```dotenv
AI_BASE_URL=https://模型服务商的OpenAI兼容地址/v1
AI_API_KEY=模型服务商创建的密钥
AI_TEXT_MODEL=文本模型ID
AI_VISION_MODEL=视觉模型ID
AI_READY_TTL_SECONDS=300
```

模型调用代码位于 `ai_service.py`，客户端按请求懒加载。系统不依赖 Coze 或其他平台专有 SDK。

### 4.2 参数填写说明

| 参数 | 用途 | 调整建议 |
| --- | --- | --- |
| `AI_BASE_URL` | OpenAI 兼容 API 根地址 | 通常以 `/v1` 结尾；不要追加 `/chat/completions` |
| `AI_API_KEY` | 调用凭证 | 只保存在 `.env.production`，不得写入代码和截图 |
| `AI_TEXT_MODEL` | 学生答疑、学情助手、翻译、题库与实验草稿生成 | 选择支持 Chat Completions、中文和 JSON 输出的模型 |
| `AI_VISION_MODEL` | 视觉能力就绪检查和需要图像理解的任务 | 若供应商用同一多模态模型，可与文本模型填同一 ID |
| `AI_READY_TTL_SECONDS` | `/ready` 模型探测缓存秒数 | 默认 300；排查配置时可临时调低到 30 |

替换流程：

1. 在模型服务商后台确认 Key、计费计划、区域和工作空间一致。
2. 修改 `.env.production` 中五个 AI 参数。
3. 重建应用容器：

   ```powershell
   docker compose --env-file .env.production up -d --build app
   ```

4. 检查 `GET /ready`，正常结果应包含 `ai: true`。
5. 登录学生端验证受限答疑，登录教师端验证题库生成或学情助手。

常见故障顺序：先检查 Key 是否有效，再检查 Base URL 与 Key 所属区域/计划是否匹配，再核对模型 ID，最后查看容器日志。不要在日志中打印完整 Key。

### 4.3 代码级参数调整

温度、最大输出长度和系统提示词在 `ai_service.py` 各业务函数的 `_chat(...)` 调用附近。只有开发人员需要修改。修改后必须重新构建镜像并运行全量测试。学生答疑的隐私限制和越权拒绝规则不得删除；教师评分仍必须由教师人工完成。

## 5. 其他运行参数

| 参数 | 默认/示例 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `production` | 正式环境启用 Secure Cookie 与 HSTS；HTTP 临时预览填 `preview` |
| `FLASK_SECRET_KEY` | 无默认安全值 | 至少 32 字节随机内容，变更会使现有会话失效 |
| `MAX_UPLOAD_MB` | `500` | 封面、视频、报告图片等上传上限 |
| `PYODIDE_BASE_URL` | 校内 HTTPS 镜像地址 | 必须指向 Pyodide v0.27.7 `full/` 目录并以 `/` 结尾 |
| `PIP_INDEX_URL` | `https://pypi.org/simple` | 只影响 Docker 构建依赖下载 |
| `PIP_DEFAULT_TIMEOUT` | `120` | 只影响 pip 下载超时 |

学生拟合代码只在浏览器 Pyodide 中运行，服务器不执行学生代码。

## 6. 业务字段字典

数据库字段的唯一代码定义位于 `platform_app/models.py`。下列“修改方式”指正常业务入口；不建议直接改数据库。

### 6.1 账号、班级与实验关系

| 表 | 字段 | 定义 | 正常修改方式 |
| --- | --- | --- | --- |
| `users` | `id` | 用户/学号主键 | 学生导入时确定；教师初始值通常为 `T001` |
| `users` | `username` | 登录名，唯一 | 学生名册导入；教师首次初始化 |
| `users` | `name` | 姓名 | 学生管理或导入数据 |
| `users` | `role` | `teacher` 或 `student` | 初始化/导入时确定，不在普通 UI 改角色 |
| `users` | `password_hash` | 密码哈希 | 账号修改密码或教师重置学生密码 |
| `users` | `active` | 是否可登录 | 账号管理逻辑 |
| `users` | `must_change_password` | 是否强制首次改密 | 导入/重置密码时设置 |
| `users` | `created_at` | 创建时间 | 系统自动写入 |
| `courses` | `id` | 班级主键 | 创建班级时生成 |
| `courses` | `teacher_id` | 负责教师 | 创建班级时绑定 |
| `courses` | `name` | 班级名称 | 教师端学生管理 |
| `courses` | `created_at` | 创建时间 | 系统自动写入 |
| `enrollments` | `id` | 选课关系主键 | 系统生成 |
| `enrollments` | `course_id`、`student_id` | 班级与学生关系，组合唯一 | 名册导入/班级管理 |
| `course_experiments` | `course_id`、`experiment_id` | 班级可见实验关系 | 实验发布和班级初始化 |
| `course_experiments` | `position` | 班级内排序 | 实验管理 |
| `course_experiments` | `active` | 是否向该班级开放 | 发布/下架操作 |
| `course_experiments` | `created_at` | 创建时间 | 系统自动写入 |

学生名册支持 `.xlsx/.xls`。必须能识别学号和姓名；班级、专业、手机号等额外列不会进入当前业务表。没有密码列时，可在导入弹窗填写统一临时密码。

### 6.2 实验与发布版本

| 表 | 字段 | 定义 | 正常修改方式 |
| --- | --- | --- | --- |
| `experiments` | `id` | 实验主键 | 系统生成 |
| `experiments` | `code` | 实验代码，唯一，最长 24 字符 | 创建实验草稿时确定 |
| `experiments` | `title` | 实验名称 | 教师编辑并发布新版本 |
| `experiments` | `order_no` | 列表排序 | 实验管理 |
| `experiments` | `retired` | 整体归档/下架标志 | 下架/恢复操作 |
| `experiment_drafts` | `teacher_id` | 草稿所有教师 | 创建草稿时绑定 |
| `experiment_drafts` | `experiment_id` | 对应正式实验，可为空 | 新建/编辑草稿流程 |
| `experiment_drafts` | `status` | 草稿状态 | 保存、发布或删除草稿 |
| `experiment_drafts` | `code`、`title` | 草稿代码与标题 | 教师编辑器 |
| `experiment_drafts` | `definition` | 实验内容 JSON | 教师编辑器，结构见下文 |
| `experiment_drafts` | `source_asset_hash` | 来源材料文件哈希 | 上传实验材料时写入 |
| `experiment_drafts` | `source_kind` | `prompt` 等来源类型 | 创建草稿时写入 |
| `experiment_drafts` | `created_at` | 创建时间 | 系统自动写入 |
| `experiment_versions` | `experiment_id`、`version_no` | 实验及不可覆盖版本号，组合唯一 | 每次发布生成新版本 |
| `experiment_versions` | `status` | `draft`、`published` 等 | 发布/下架流程 |
| `experiment_versions` | `definition` | 冻结后的实验内容 JSON | 只能发布新版本，不原地覆盖历史版本 |
| `experiment_versions` | `created_at`、`published_at` | 创建/发布时间 | 系统自动写入 |

`definition` JSON 字段：

| 键 | 类型 | 说明 | 修改入口 |
| --- | --- | --- | --- |
| `summary` | 字符串 | 实验简介 | 教师实验编辑器“基本信息” |
| `principle` | 字符串 | 实验原理 | “原理与仪器” |
| `apparatus` | 字符串 | 仪器设备 | “原理与仪器” |
| `reference_value` | 数字 | 参考结果，仅用于实验定义/内部判断 | “拟合与误差”；不可泄露给学生答疑 |
| `reference_unit` | 字符串 | 参考值单位 | “拟合与误差” |
| `fit_template` | 字符串 | `linear/polynomial/exponential/sine/rabi/odmr/echo` | “拟合与误差” |
| `formula` | 字符串 | 拟合公式/浏览器代码的说明 | “拟合与误差” |
| `steps` | 字符串数组 | 学生操作步骤 | “实验步骤” |
| `questions` | 对象数组 | 候选题库 | “候选题库”逐题审核/手动添加/AI 补题 |
| `cover_image_hash` | 字符串 | 展厅封面文件 SHA-256 | 封面上传 |
| `demo_video_hash` | 字符串 | 演示视频文件 SHA-256 | 视频上传 |
| `question_bank_revision` | 整数 | 内置题库修订号 | 系统升级维护 |
| `operation_steps_revision` | 整数 | 内置步骤修订号 | 系统升级维护 |
| `report_sections` | 字符串数组 | 报告章节清单 | 系统默认模板维护 |

单题对象字段：`id` 题目唯一标识；`concept_id` 母题方向标识；`concept_title` 教师可读方向名；`question` 题干；`options` 四个选项；`answer` 正确选项原文；`explanation` 解析；`reviewed_by_teacher` 是否已由教师审核。发布前至少 40 道题、10 个母题方向，并满足每个方向的变式要求。

### 6.3 预习、提交、报告与审核

| 表 | 字段 | 定义 | 正常修改方式 |
| --- | --- | --- | --- |
| `quiz_assignments` | `course_id`、`student_id`、`experiment_version_id` | 班级/学生/实验版本绑定 | 学生首次进入预习时冻结 |
| `quiz_assignments` | `questions` | 当前 10 题 JSON | 系统随机抽题后冻结 |
| `quiz_assignments` | `answers` | 学生答案映射 | 学生逐题作答 |
| `quiz_assignments` | `attempt_no` | 当前尝试次数 | 重做时递增 |
| `quiz_assignments` | `history` | 历次完整题目、答案、完成时间 | 重做时追加，不覆盖 |
| `quiz_assignments` | `signature` | 题目组合哈希 | 系统生成，用于防重复 |
| `quiz_assignments` | `frozen_at`、`completed_at` | 冻结/完成时间 | 系统自动写入 |
| `submission_revisions` | `request_id` | 幂等请求 ID | 正式提交时生成 |
| `submission_revisions` | `student_id`、`course_id`、`experiment_version_id` | 提交所属关系 | 正式提交时绑定 |
| `submission_revisions` | `revision_no` | 修订号 | 每次重新提交递增 |
| `submission_revisions` | `status` | `submitted/withdrawn/superseded` | 提交、撤回、修订流程 |
| `submission_revisions` | `payload` | 完整冻结提交 JSON | 从报告草稿生成，不原地修改 |
| `submission_revisions` | `result_value` | 学生关键结果数值 | 报告提交前填写 |
| `submission_revisions` | `relative_error`、`deterministic_score`、`passed` | 旧兼容列；当前正式成绩不依赖它们 | 不作为学生展示或教师正式评分入口 |
| `submission_revisions` | `fingerprint` | 内容指纹 | 系统生成 |
| `submission_revisions` | `evaluation_id` | 旧评估关系，可为空 | 当前报告提交不调用 AI 评分 |
| `submission_revisions` | `submitted_at`、`withdrawn_at` | 提交/撤回时间 | 系统自动写入 |
| `submission_revisions` | `supersedes_id` | 被本修订替代的提交 | 重新提交时自动关联 |
| `report_drafts` | `student_id`、`course_id`、`experiment_version_id` | 每名学生每版本唯一活动草稿 | 进入报告时创建 |
| `report_drafts` | `source_revision_id` | 草稿复制来源修订 | “复制为新修订”时写入 |
| `report_drafts` | `status` | `active/frozen` 等 | 正式提交后冻结 |
| `report_drafts` | `content` | 结构化报告 JSON | 报告编辑器自动保存 |
| `report_drafts` | `asset_hashes` | 当前草稿允许引用的图片哈希 | 报告上传图片时追加 |
| `report_drafts` | `lock_version` | 乐观锁版本号 | 每次保存递增，防止多页覆盖 |
| `report_drafts` | `created_at`、`updated_at` | 创建/更新时间 | 系统自动写入 |
| `reviews` | `submission_id` | 被审核的提交修订 | 教师审核页 |
| `reviews` | `teacher_id` | 审核教师 | 登录身份自动绑定 |
| `reviews` | `private_score` | 教师内部成绩 0–100 | 教师审核页 |
| `reviews` | `private_comment` | 教师内部评语 | 教师审核页；不得进入学生响应或报告 |
| `reviews` | `decision` | 审核决定 | 教师审核页 |
| `reviews` | `superseded` | 是否被后续审核替代 | 新审核时自动处理 |
| `reviews` | `created_at` | 审核时间 | 系统自动写入 |

报告 `content` 顶层字段：`schema_version`、`title_zh`、`title_en`、`author_name`、`student_id`、`affiliation_zh`、`affiliation_en`、`abstract_zh`、`keywords_zh`、`abstract_en`、`keywords_en`、`sections`、`fit_result`、`result_value`、`steps_complete`。

`sections` 固定章节 ID：`purpose`、`apparatus`、`principle`、`steps`、`raw_data`、`fit`、`error`、`discussion`、`conclusion`、`references`。内容块支持 `paragraph`、`heading`、`quote`、`formula`、`list`、`table`、`image`。拟合输入会进入 `raw_data` 表格，拟合图和参数保存在 `fit_result` 并进入实时预览、Word/PDF 导出。

`fit_result` 字段：`code` 浏览器执行代码；`formula` 公式；`initial_parameters` 初始参数对象；`final_parameters` 最终参数对象；`metrics` 指标对象；`plot_data_url` PNG Base64 图像，最大约 5 MB。该对象由浏览器拟合生成并随草稿/正式修订保存。

正式提交 `payload` 字段：`abstract`、`principle`、`raw_data`、`discussion`、`conclusion`、`result_value`、`fit_result`、`steps_complete`、`file_hashes`、`report_document`。其中 `report_document` 是完整结构化报告快照。

### 6.4 荣誉、审计、文件与兼容数据

| 表 | 字段 | 定义 | 正常修改方式 |
| --- | --- | --- | --- |
| `awards` | `student_id`、`experiment_version_id` | 学生与实验版本的唯一荣誉关系 | 业务规则生成/历史兼容；当前学生纪念证书以有效正式提交为准 |
| `awards` | `score`、`awarded_at` | 旧荣誉分数与授予时间 | 不作为当前学生正式成绩来源 |
| `audit_events` | `actor_id` | 操作人，可为空 | 系统自动写入 |
| `audit_events` | `action` | 操作代码 | 系统自动写入 |
| `audit_events` | `entity_type`、`entity_id` | 被操作业务对象 | 系统自动写入 |
| `audit_events` | `detail` | 审计详情 JSON | 系统自动写入，不存密钥 |
| `audit_events` | `created_at` | 操作时间 | 系统自动写入 |
| `file_assets` | `sha256` | 文件内容哈希主键 | 上传时生成 |
| `file_assets` | `object_key` | `/data` 文件卷中的对象键 | 上传服务生成 |
| `file_assets` | `original_name`、`content_type`、`size` | 原文件名、MIME、字节数 | 上传时识别 |
| `file_assets` | `created_at` | 上传时间 | 系统自动写入 |
| `legacy_archives` | `source_name`、`sha256` | 旧数据来源与哈希 | 旧数据归档脚本 |
| `legacy_archives` | `payload` | 只读旧数据 JSON | 仅归档，不映射到新实验进度 |
| `legacy_archives` | `imported_at` | 归档时间 | 系统自动写入 |
| `evaluations` | 全部字段 | 历史 AI/确定性评估兼容表 | 当前正式报告评分不写入；不得恢复为学生评分来源 |

## 7. 启动与验收

首次启动：

```powershell
docker compose --env-file .env.production up -d --build
docker compose --env-file .env.production ps
```

结构和测试验证：

```powershell
python scripts/verify_project.py
pytest -q
python scripts/package_docker.py
```

服务验证：

```powershell
Invoke-WebRequest http://127.0.0.1:5000/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:5000/ready -UseBasicParsing
```

浏览器验收至少完成：教师登录与改密、班级创建和名册导入、五项实验可见、预习抽题与重做、浏览器拟合、拟合数据/图进入报告、报告自动保存、PDF 精确预览、正式提交、教师人工评分、学情筛选与 Excel 导出、历史报告复制为新修订。

## 8. 常见问题

- `/ready` 的 `database` 为 false：核对 `DATABASE_URL`、数据库网络、防火墙、账号权限和数据库名。
- `/ready` 的 `ai` 为 false：按 Key、计费计划/区域、Base URL、模型 ID 顺序排查。
- 登录后立即回到登录页：正式环境必须经 HTTPS；临时 HTTP 预览设置 `APP_ENV=preview` 并重启。
- 拟合页无法加载：确认 `PYODIDE_BASE_URL` 是 HTTPS、版本为 0.27.7、路径以 `/` 结尾，并可从浏览器直接访问。
- 修改 `.env.production` 未生效：执行 `docker compose --env-file .env.production up -d --build app`，不要只刷新网页。
- 修改实验历史数据：不要直接覆盖已发布版本；在教师端创建草稿并发布新版本。

交付与排障时只记录配置项名称和错误信息，不复制完整数据库密码、AI Key、Cookie 或会话数据。
