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
- 交付/排障见 `DEPLOY_ADAPTATION.md`。
