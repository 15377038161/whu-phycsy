# 文件修改地图

## 一、运行时必须同步的文件

### `templates/base.html`

修改内容：

- 静态资源版本更新为 `20260813-multidevice-v1`，用于清除旧 JS/CSS 缓存；
- 增加“跳到主要内容”无障碍入口；
- 所有登录后页面增加统一“返回上级 / 回到首页”工具条；
- 增加全局离线状态条；
- 主内容增加 `id="mainContent"` 与可聚焦能力；
- 学生、教师 AI 面板补充遮罩、`role="dialog"`、`aria-controls`、`aria-expanded`；
- 保留原登录、角色导航、CSRF、AI 地址与账户安全弹窗。

依赖：必须与新版 `static/platform.js` 和 `static/quantum-platform.css` 同时上线。

### `static/platform.js`

修改内容：

- 统一抽屉、模态和通知的开启/关闭控制；
- 支持关闭按钮、遮罩、Escape、焦点约束与焦点回归；
- 将不可逆操作的浏览器原生确认替换为统一确认模态；
- Flask flash 消息转为统一通知弹窗；
- 增加返回上级的同源历史判断和角色首页兜底；
- 增加 `aria-current`、离线/恢复状态、表单错误聚焦与 `aria-invalid`；
- 表单提交增加 Loading 和防重复点击；
- AI 长内容面板纳入抽屉规范，支持遮罩关闭和焦点回归；
- 修复报告目录关闭后锚点定位、学情筛选抽屉状态和审核表格过滤契约。

依赖：模板必须包含对应的 `data-open-layer`、`data-close-layer`、`data-network-status` 等标记。

### `static/quantum-platform.css`

修改内容：

- 新增统一右侧抽屉、手机底部面板、确认模态和通知弹窗样式；
- 新增全局返回/首页工具条、离线状态条、跳过导航和焦点高亮；
- 新增表单错误、提交 Loading、高对比度和减少动效规则；
- 抽屉桌面/平板宽度为 460px，手机为全宽底部面板；
- 移动端输入框保持 16px，核心按钮保持 44–48px 触控高度；
- 移除 AI 入口持续位移动画，避免触控目标不稳定；
- 保留唯一 `quantum-platform.css`，不创建移动端平行 CSS。

### `templates/teacher_analytics.html`

修改内容：

- 学情筛选从主页面内联区域移入 `analytics-filters` 抽屉；
- 保留班级、实验、任务、状态、日期和导出功能；
- 增加抽屉标题、关闭按钮和无障碍属性。

### `templates/teacher_dashboard.html`

修改内容：

- 审核队列的搜索、状态、课程与排序进入 `review-filters` 抽屉；
- 主页面只保留队列、统计和关键操作；
- 审核表格补充 `data-filter-table`，确保前端过滤真实生效。

### `templates/report.html`

修改内容：

- 报告工具栏增加“报告目录”；
- 长目录进入 `report-outline` 抽屉；
- 正文各节增加稳定锚点，点击目录后关闭抽屉并定位正文；
- 保留学生/教师报告权限差异和 DOCX/PDF 导出。

## 二、建议同步的规范文档

### `UI_VISUAL_STANDARD.md`

新增完整色值、字体、间距、按钮、断点、内容分层、弹层、表单状态、无障碍、动效、离线和验收标准。

### `FUNCTION_API_PLAN.md`

新增现有接口与后续规划接口的请求参数、响应格式、权限、幂等、异常处理和页面映射。规划接口仅为设计，不代表已经实现。

### `ARCHITECTURE.md`

补充统一弹层、全局导航、离线/表单反馈和接口文档真源约束。

## 三、交付工具文件

### `scripts/package_docker.py`

把 `FUNCTION_API_PLAN.md` 加入 Docker 白名单和必需文件校验，避免重新打包时遗漏接口规划文档。该文件不影响线上运行。

## 四、明确未修改

- `platform_app/blueprints/`：无接口或路由变更；
- `platform_app/models.py`：无数据库结构变更；
- `platform_app/services/`：无业务规则变更；
- PostgreSQL 数据、上传卷、报告修订和审核记录：无迁移；
- AI 模型、Base URL、API Key：无配置变更；
- 学生隐私边界、教师内部评分规则和浏览器 Pyodide 执行边界：保持不变。
