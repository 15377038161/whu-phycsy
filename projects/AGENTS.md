# 武汉大学量子实验教学平台

武汉大学自托管量子实验教学平台，面向学生和教师的 Flask + Jinja 单体 Web 应用。

## 项目概述

本平台是武汉大学量子实验教学的核心系统，提供五项正式实验（离子阱、量子密钥分发、量子纠缠、金刚石量子计算机、单像素光子成像）的完整教学流程：预习题库、实验操作、数据拟合、报告编辑与教师审核。学生端包含实验探索、我的实验、报告与荣誉（首页为关卡展廊，任选一关开始挑战；提交成功自动弹出通关纪念证书，首页底部内联“我的通关纪念”）；教师端包含审核、实验管理、学生管理和学情观测台。

## 技术栈

- **后端**：Python 3.11 + Flask 3.0 + SQLAlchemy 2.0
- **数据库**：PostgreSQL（生产 / Coze 平台 Supabase）、SQLite（本地开发）
- **前端**：Jinja 模板 + 原生 JavaScript + 唯一 CSS（`static/quantum-platform.css`）
- **科学计算**：浏览器 Pyodide（NumPy、SciPy、Matplotlib、Pandas）
- **AI 服务**：双后端懒加载（流式响应）。默认走 Coze 平台集成模型 `doubao-seed-2-0-lite-260215`（开箱即用、无需密钥）；配置了 `AI_BASE_URL`+`AI_API_KEY`+`AI_TEXT_MODEL`+`AI_VISION_MODEL` 时改走 OpenAI 兼容接口（教师自托管用）。
- **部署**：Coze 平台（gunicorn）+ 教师自托管 Docker + Nginx 反向代理
- **包管理**：pip（requirements.txt）

## 目录结构

```
/workspace/projects/
├── app.py                      # WSGI 入口（Gunicorn 和本地开发）
├── platform_app/               # 核心应用包
│   ├── __init__.py            # create_app() 工厂函数
│   ├── models.py              # SQLAlchemy 模型定义
│   ├── db.py                  # 数据库初始化
│   ├── blueprints/            # HTTP 路由
│   │   ├── auth.py           # 认证（登录、登出、密码修改）
│   │   ├── student.py        # 学生端页面
│   │   ├── teacher.py        # 教师端页面
│   │   └── api.py            # API 接口（AI、报告、拟合等）
│   └── services/              # 业务逻辑层
│       ├── experiment.py     # 实验版本管理
│       ├── submission.py     # 提交修订
│       ├── review.py         # 教师审核
│       ├── report.py         # 报告草稿与提交
│       └── fit.py            # 拟合服务
├── templates/                  # Jinja 模板（唯一 UI）
├── static/                     # 静态资源
│   ├── quantum-platform.css  # 唯一样式表
│   ├── platform.js           # 前端逻辑
│   ├── images/               # 品牌与实验图片
│   ├── fonts/simhei.ttf      # 中文 PDF 字体（必须保留）
│   └── vendor/               # 第三方库（KaTeX、lucide）
├── ai_service.py              # AI 客户端（必须懒加载）
├── source_docs/               # 内部知识文档（不向学生公开）
├── scripts/                   # 运维脚本
│   ├── verify_project.py     # 项目验证
│   ├── init_database.py      # 数据库初始化
│   ├── build.sh              # 预览构建
│   └── run.sh                # 预览启动
├── tests/                     # 测试用例
├── requirements.txt           # Python 依赖
├── Dockerfile                 # Docker 镜像
├── docker-compose.yml         # 生产编排
└── .coze                      # 平台配置
```

## 关键入口

- **应用入口**：`app.py` → `platform_app.create_app()`
- **路由注册**：`platform_app/blueprints/` 下四个蓝图
- **数据库模型**：`platform_app/models.py`
- **业务逻辑**：`platform_app/services/` 各模块
- **UI 模板**：`templates/` 目录
- **样式表**：`static/quantum-platform.css`（唯一）
- **AI 服务**：`ai_service.py`（懒加载，流式）

## 运行与预览

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器（默认 5000 端口）
python app.py
```

### 预览链路

项目已配置 `.coze` 和 `.preview`，支持平台预览：

- **构建脚本**：`scripts/build.sh`（创建虚拟环境、安装依赖）
- **启动脚本**：`scripts/run.sh`（从 `.preview` 读取端口，启动 Flask dev server）
- **端口**：固定 5000（对外暴露），从 `.preview` 读取
- **绑定**：`0.0.0.0`（IPv4 全接口）

### 生产部署

两条独立部署路径，用途不同：

**1. Coze 平台部署**（`.coze` 的 `[deploy]`）：由 `scripts/setup.sh`（pip 安装 `requirements.txt`）+ `scripts/http_run.sh`（gunicorn 监听 5000，`exec gunicorn --bind 0.0.0.0:$PORT app:app`）驱动。平台自动注入 `PGDATABASE_URL`（Supabase PostgreSQL 直连），开发模式即可用 PostgreSQL；本地无该变量时回退 SQLite。

**2. 教师自托管 Docker**（交付给学校）：

```bash
# Docker 构建
docker build -t whu-quantum-lab .

# Docker Compose 启动
docker-compose up -d
```

生产环境必须使用 PostgreSQL，通过 `DATABASE_URL` 环境变量配置。

## 用户偏好与长期约束

1. **唯一 UI**：`templates/` + `static/quantum-platform.css`，禁止恢复旧页面或并行 CSS
2. **五项正式实验**：离子阱、量子密钥分发、量子纠缠、金刚石量子计算机、单像素光子成像
3. **数据库**：生产只用 PostgreSQL（含 Coze 平台 Supabase 的 `PGDATABASE_URL`），禁止回退到 `data.json`、SQLite；禁止用 Supabase SDK 替换 SQLAlchemy 数据层
4. **不可覆盖**：发布版本、提交修订、AI 评估、教师审核和文件均不可原地覆盖
5. **教师评分隔离**：教师评分和内部评语不得进入任何学生响应或学生报告。正式提交时按发布版本参考值自动计算相对误差与确定分（≤5%=100，≤7%=90，≤10%=85，≤15%=80，>15%=70），仅在教师审核页作为建议分展示并预填人工评分；正式成绩以人工审核分为准
6. **客户端执行**：学生代码只在浏览器 Pyodide 中运行，服务器绝不执行
7. **AI 双后端懒加载**：AI 客户端必须懒加载（首次调用才初始化）。默认走 Coze 平台集成模型 `doubao-seed-2-0-lite-260215`（开箱即用、无需密钥）；配置了 `AI_BASE_URL`+`AI_API_KEY`+`AI_TEXT_MODEL`+`AI_VISION_MODEL` 时改走 OpenAI 兼容接口（教师自托管）。Coze SDK 仅用于 AI 能力，不得用于数据/存储等其他能力。
8. **保留资源**：不得删除 `source_docs/`、`static/fonts/simhei.ttf` 或报告依赖
9. **交付包清洁**：`.env.local`、Key CSV、真实报告、旧数据和上传文件不得进入交付包
10. **验证必做**：修改后至少运行 `python scripts/verify_project.py` 和 `pytest -q`

## 常见问题和预防

### 数据库连接

- 数据库连接优先级：`DATABASE_URL`（显式设置，教师自托管）→ `PGDATABASE_URL`（Coze 平台自动注入的 Supabase PostgreSQL 直连）→ SQLite（`runtime/platform.db`，本地开发兜底）
- 开发环境未设置 `DATABASE_URL` 且无 `PGDATABASE_URL` 时使用 `runtime/platform.db`（SQLite）
- 生产环境 `APP_ENV=production` 时必须使用 PostgreSQL，否则启动失败
- 数据库初始化：`python scripts/init_database.py`

### 预览端口

- 预览端口固定 5000，从 `.preview` 文件读取
- 启动脚本会自动清理同端口残留进程
- 绝不碰 9000 端口（系统保留）

### 预览 iframe 与 session cookie

- Coze 平台预览通常以跨源 iframe 嵌入应用；`SameSite=Lax` 会在 iframe 子请求中丢弃 session cookie，导致登录后 CSRF 失败或认证丢失（表现为"只显示登录页、提交后被挡"）。
- `_PreviewSessionInterface`（`platform_app/__init__.py`）在 HTTPS（平台代理，经 ProxyFix `x_proto=1` 判定）时发出 `SameSite=None; Secure`，使 cookie 能跨源 iframe 回传；HTTP 本地开发保持 `Lax`。
- 开发模式下 `frame-ancestors *` 且移除 `X-Frame-Options`，允许平台嵌入预览；生产模式恢复 `DENY` / `frame-ancestors 'none'`。
- SQLite 启用 WAL + `busy_timeout=5000`，缓解 gunicorn 多 worker 并发写锁定。

### FaaS 只读文件系统

- Coze FaaS 部署环境（`/opt/bytefaas/`）文件系统只读，`create_app()` 中 `Path(DATA_DIR).mkdir()` 会因 `OSError: [Errno 30] Read-only file system` 失败。
- `_on_coze_platform()`（检测 `PGDATABASE_URL`/`COZE_SUPABASE_URL`）返回 `True` 时，`DATA_DIR` 默认 `/tmp/whu-quantum-lab`（FaaS 可写目录），SQLite 回退路径同步使用该目录。
- 本地开发无平台环境变量时保持 `root/runtime` 不变。
- `setup.sh` 只安装 `requirements.txt`（11 个轻量包），构建 <30 秒；不在构建阶段安装 `coze-coding-dev-sdk`（平台运行时预装，AI 服务懒加载）。

### AI 服务

- AI 客户端必须懒加载（首次调用才初始化），`ai_service.py` 为双后端分发层。
- **后端选择**（调用时判定）：同时配置 `AI_BASE_URL`+`AI_API_KEY`+`AI_TEXT_MODEL`+`AI_VISION_MODEL` 走 OpenAI 兼容接口（教师自托管）；否则走 Coze 平台集成模型 `doubao-seed-2-0-lite-260215`（开箱即用，模型可用 `AI_COZE_MODEL` 覆盖）。
- Coze SDK（`coze_coding_dev_sdk`）由平台运行时预装，AI 服务懒加载，构建阶段不需要安装。`setup.sh` 只安装 `requirements.txt`；SDK 缺失时 AI 接口返回友好错误，不影响应用启动。教师自托管走 OpenAI 路径，不依赖该 SDK。
- 流式响应，设置 `X-Accel-Buffering: no`。

### 开箱即用（部署播种）

- `scripts/http_run.sh`（Coze 部署）与 `scripts/run.sh`（预览）在启动服务前会运行 `scripts/init_database.py` 播种：管理员 admin/admin123、学生 S001/123456、演示课程 C001 及 5 个实验。
- 播种幂等，绝不覆盖已有数据；`APP_ENV=production` 时不播种（要求 `INITIAL_ADMIN_PASSWORD` ≥12 位）。
- 播种在关键依赖点（admin → course → enrollment）显式 `flush()`，确保 PostgreSQL 外键约束下的插入顺序正确（SQLite 默认不强制外键，也需要兼容）。
- 开发模式用 SQLite（`runtime/platform.db`），无需外部数据库即可启动；生产仍需 PostgreSQL `DATABASE_URL`。

### 文件上传

- 文件按 SHA-256 内容寻址，上传后不可覆盖
- 默认上限 500 MB（`MAX_UPLOAD_MB`）
- 严格校验扩展名与 MIME 白名单

### `.coze` 平台配置

- `.coze` 是 Coze 平台的预览/部署配置文件（含 `sub_id`、`project_type`、`[dev]`、`[deploy]`），**不是**旧 Coze SDK 依赖，允许存在于仓库根目录。
- 教师自托管交付包（`scripts/package_docker.py`）采用根文件白名单（`ROOT_FILES`），`.coze` 不在白名单内，因此不会进入交付 ZIP，交付包保持清洁。
- `scripts/verify_project.py` 的 FORBIDDEN 列表和 `tests/test_portable_delivery.py` 的仓库根检查均不禁止 `.coze`；只有交付 ZIP 内容检查（`test_delivery_package_is_clean`）继续排除它。修改这几处时务必保持该区分。

### 验证命令

每次修改后必须执行：

```bash
python scripts/verify_project.py
pytest -q
```

---

# AI 修改规则

修改任何代码前，必须完整阅读 `ARCHITECTURE.md`。

1. 唯一 UI 是 `templates/` + `static/quantum-platform.css`；禁止恢复旧页面、旧 CSS 或并行 UI。
2. 唯一正式实验是离子阱、量子密钥分发、量子纠缠、金刚石量子计算机、单像素光子成像。
3. 生产业务数据只使用 PostgreSQL（含 Coze 平台 Supabase 的 `PGDATABASE_URL`）；禁止回退到 `data.json`、SQLite；禁止用 Supabase SDK 替换 SQLAlchemy 数据层。
4. 发布版本、提交修订、AI 评估、教师审核和文件均不可原地覆盖。
5. 教师评分和内部评语不得进入任何学生响应或学生报告。
6. 学生代码只在浏览器 Pyodide 中运行，服务器绝不执行。
7. AI 客户端必须懒加载；默认走 Coze 集成模型（开箱即用），配置 `AI_API_KEY` 等时走 OpenAI 兼容接口（教师自托管），两条路径都不得破坏。
8. 不得删除 `source_docs/`、`static/fonts/simhei.ttf` 或报告依赖。
9. `.env.local`、Key CSV、真实报告、旧数据和上传文件不得进入交付包。
10. 修改后至少运行 `python scripts/verify_project.py` 和 `pytest -q`。
