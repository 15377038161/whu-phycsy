# 武大量子实验平台部署手册

教师本地部署、内置/外部 PostgreSQL 连接、自定义模型替换和全部业务字段说明统一维护在 `TEACHER_LOCAL_DEPLOYMENT_GUIDE.md`。制作交付包前必须运行 `python scripts/verify_project.py`，确认该文档存在并被 `scripts/package_docker.py` 纳入 ZIP。

题卷重做功能为 `quiz_assignments` 增加 `attempt_no` 和 `history` 字段，应用启动时的幂等 schema migration 会自动补列。部署后必须确认 PostgreSQL 字段存在，并完成一次“答题—逐题解析—重新抽题—原题不重复”的真实浏览器验收。学生 AI 使用 `text/event-stream` 流式输出，Nginx 必须尊重应用返回的 `X-Accel-Buffering: no`，不得重新缓冲完整回答。成绩导出使用现有 `openpyxl` 依赖，不需要额外外部服务；报告提交已不再调用 AI 评分，因此 AI 暂时不可用不会阻塞报告提交和教师人工评分。

## 本地试用

1. 当前 `.env.local` 已由 Codex 写入临时 AI Key，并被 Git 忽略。不要复制、上传或打印该文件。
2. 运行 `docker compose -f docker-compose.local.yml up --build`，访问 `http://127.0.0.1:5000`。
3. 演示账号：教师 `admin/admin123`，学生 `S001/123456`。首次登录后应修改为学校账号体系要求的密码。

## 学校服务器

1. 解压交付包，把 `.env.example` 复制为 `.env.production`，填写强随机密钥、数据库密码、学校自己的 AI Key 与模型。
2. lucide 图标与 KaTeX 已随应用本地交付，不依赖公网。把 Pyodide v0.27.7 镜像到校内 HTTPS 静态服务并填写以 `/` 结尾的 `PYODIDE_BASE_URL`；应用会把该地址的源自动加入 CSP 的脚本、连接和 Worker 白名单。
3. 运行 `docker compose --env-file .env.production up -d --build`。应用只绑定 `127.0.0.1:5000`，用 Nginx/Caddy 配置 HTTPS 反向代理。
4. 验收 `GET /health` 为 200，`GET /ready` 为 200，并完成一次受限原理/步骤 AI 首段流式到达、AI 越权问题拒绝、学生所有页面仅显示预习题成绩、预习题逐题解析与无原题重做、浏览器拟合、报告自动保存、PDF 精确预览、正式提交、教师人工评分、班级成绩 Excel、复制为下一修订以及 Word/PDF 导出。

若服务器访问 PyPI 较慢，可在 `.env.production` 设置 `PIP_INDEX_URL` 和 `PIP_DEFAULT_TIMEOUT`；阿里云 ECS 可使用 `https://mirrors.aliyun.com/pypi/simple/`。该设置只影响镜像构建，不进入应用运行环境。

仅用于 IP + HTTP 的临时预览时，可设置 `APP_ENV=preview`；该模式不启用 Debug，仍可连接 PostgreSQL，但允许浏览器在 HTTP 下保存登录会话。接入 HTTPS 后必须恢复 `APP_ENV=production`，以重新启用 Secure Cookie。
预览环境首次启动后执行 `docker compose --env-file .env.production exec -T app python scripts/init_preview.py`，幂等创建演示学生与课程；脚本在非 `preview` 环境会直接拒绝执行。

## 旧数据归档

在本地或受控迁移环境运行：

```bash
docker compose run --rm app python scripts/archive_legacy_data.py /secure/path/data.json
```

脚本只迁移账号/课程身份；旧进度、提交和报告整体进入只读归档，不映射到新五项实验。

## 备份与恢复

```bash
docker compose --env-file .env.production exec -T db pg_dump -U wuda wuda_quantum > wuda.sql
docker run --rm -v wuda_app_files:/data -v "$PWD":/backup alpine tar czf /backup/wuda-files.tgz -C /data .
cat wuda.sql | docker compose --env-file .env.production exec -T db psql -U wuda wuda_quantum
```

数据库和文件卷必须作为同一备份批次保存。升级前先备份，再运行新版 `docker compose up -d --build`。

## 安全交接

- HTTPS、强密码、数据库防火墙和定期备份由学校运维负责。
- 生产环境必须保持 `APP_ENV=production`，以启用 Secure Cookie 与一年 HSTS；反向代理需把真实协议和客户端地址传给应用。
- 发布后用浏览器确认响应无 CSP 违规，并实际完成一次 Pyodide 拟合、KaTeX 公式显示和 lucide 图标显示。
- `.env.production`、`.env.local` 和 Key CSV 不得进入交付包或日志。
- 武大验收完成后，替换为学校自己的 AI Key，并在供应商后台删除当前临时 Key。
