# 可直接粘贴给 Coze 开发助手的执行提示词

请先只检查，不要立即覆盖文件。

目标：把“移动端适配、统一弹层、全局防呆导航、状态反馈与无障碍”更新合并到当前已部署项目，同时保留现有后端业务、数据库、环境变量和用户数据。

第一步，确认当前项目是否为以下 Flask/Jinja 架构：

- 存在 `templates/base.html`；
- 存在 `static/platform.js`、`static/quantum-platform.css`；
- 存在 `templates/report.html`、`teacher_analytics.html`、`teacher_dashboard.html`；
- `base.html` 使用 Flask `url_for` 加载静态资源。

如果不满足，停止操作并报告当前真实入口、模板路径和 CSS/JS 路径；不要把新旧 UI 并行保留，不要恢复旧 Coze SDK、iframe 页面或旧 CSS。

如果满足：

1. 先备份当前 6 个目标文件；
2. 对照 `FILE_CHANGE_MAP.md` 检查当前版本是否有额外业务修改；
3. 以 `coze-ui-update-overwrite-20260813.zip` 为目标版本，合并以下文件：
   - `templates/base.html`
   - `templates/report.html`
   - `templates/teacher_analytics.html`
   - `templates/teacher_dashboard.html`
   - `static/platform.js`
   - `static/quantum-platform.css`
4. 不能修改 `platform_app/blueprints/`、models、数据库、上传数据和环境变量；
5. 保持唯一 UI 为 `templates/` + `static/quantum-platform.css`，禁止新增 `mobile.css` 或旧版兼容页面；
6. 保留学生隐私边界：教师评分和内部评语不得进入学生页面或响应；
7. 保留学生代码仅在浏览器 Pyodide 执行的边界；
8. 完成后重启应用并清理静态缓存。

验收：

- 运行 `python scripts/verify_project.py` 和 `pytest -q`；
- 验证 1440×900、1024×768、768×1024、390×844；
- 检查返回上级、回到首页、实验上一步/下一步；
- 检查抽屉、模态、通知的关闭按钮、遮罩、Escape 和焦点回归；
- 检查离线提示、表单错误、Loading 与重复提交防护；
- 检查学生与教师完整登录和核心业务流程；
- 不得把 `.env.local`、`.env.production`、API Key、真实报告、上传文件或日志加入交付包。

最终请报告：实际修改文件、合并冲突、测试结果、浏览器验证结果，以及是否需要回滚。不要只回复纸面方案。
