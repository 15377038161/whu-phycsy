# Coze 已部署版本 UI 升级交接包

## 结论

本交接包用于把 2026-08-12 至 2026-08-13 完成的移动端适配、统一弹层、防呆导航、状态反馈和无障碍改造，同步到已经部署的一版项目中。

本次运行时更新只涉及 6 个文件：

1. `templates/base.html`
2. `templates/report.html`
3. `templates/teacher_analytics.html`
4. `templates/teacher_dashboard.html`
5. `static/platform.js`
6. `static/quantum-platform.css`

不修改数据库结构、后端路由、业务模型、用户数据、报告数据、上传文件或环境变量。

## 先判断能否直接覆盖

### 可以使用覆盖包

Coze 上的源代码同时满足：

- 存在 `templates/base.html`；
- 存在 `static/platform.js` 和 `static/quantum-platform.css`；
- `base.html` 通过 `url_for('static', ...)` 加载上述 JS/CSS；
- 教师页面使用 `teacher_dashboard.html`、`teacher_analytics.html`；
- 报告页使用 `report.html`。

### 不能直接覆盖

出现任意一种情况时停止覆盖：

- 项目以 `.coze`、iframe token 或旧 Coze SDK 为运行入口；
- 页面不在 `templates/`，或同时存在两套 CSS/旧页面；
- 没有当前 Flask 蓝图与 `url_for` 路由；
- Coze 版本对这 6 个文件已有独立业务改动且无法确认差异。

此时应使用完整包 `dist/wuda-docker-20260813.zip` 做整体迁移，不要把新 UI 拼接进旧 UI。

## 本目录内容

- `FILE_CHANGE_MAP.md`：逐文件说明修改位置、功能和依赖。
- `COZE_APPLY_CHECKLIST.md`：备份、覆盖、重启、验收和回滚步骤。
- `COZE_AGENT_CHANGE_PROMPT.md`：可直接交给 Coze 开发助手执行的提示词。
- `PACKAGE_CONTENTS.md`：交接包条目、大小与 SHA-256 校验值。
- `coze-ui-update-overwrite-20260813.zip`：保持原始目录结构的完整覆盖文件。
- `coze-ui-preview-reference-20260813.zip`：13 张移动端 AI 预览图与页面清单，仅作视觉参照，不上传到生产运行目录。

## 已验证结果

- `python scripts/verify_project.py`：通过。
- `pytest -q`：72 passed。
- Chromium 四档视口全页面审计：44/44 通过。
- 桌面 1440×900、平板 1024×768/768×1024、手机 390×844 均无页面级横向溢出。
- 覆盖抽屉、模态、通知、返回/首页、表单错误、离线提示、焦点回归和移动端触控尺寸。

## 不要上传的内容

- `.env.local`、`.env.production`、任何 API Key；
- 数据库文件、真实报告、上传文件与运行日志；
- `node_modules/`、`.workbuddy/`、测试截图和本地缓存；
- `coze-ui-preview-reference-20260813.zip` 内的评审图片。

## 推荐执行方式

先完整阅读 `COZE_APPLY_CHECKLIST.md`。任何覆盖前先下载或复制 Coze 当前版本的 6 个目标文件作为回滚备份；覆盖完成后必须重启应用并清除静态资源缓存。
