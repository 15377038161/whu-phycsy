# 功能与接口规划 V1

本文是页面功能、HTTP 接口、状态与异常处理的统一规划。`ARCHITECTURE.md` 仍是系统边界真源；本文不改变权限、不可覆盖修订、学生隐私、PostgreSQL 生产数据与浏览器 Pyodide 等既有规则。

## 1. 通用契约

- 基础路径：页面接口使用现有 Flask 路由；结构化接口使用 `/api/...`。
- 认证：会话 Cookie；学生和教师端点按角色校验。未登录页面请求重定向登录，API 返回 `401`；越权返回 `403`。
- 写请求：HTML 表单携带 `csrf_token`；JSON/AJAX 使用 `X-CSRFToken`。
- 时间：ISO 8601，服务端存储带时区时间；日期筛选起止值显式说明是否包含当天末尾。
- 成功 JSON：业务对象或 `{data, meta}`；异步长任务可返回 `{job_id, status, poll_after_ms}`。
- 失败 JSON：`{"error":"用户可理解的信息","code":"稳定错误码","details":{}}`。不得向用户暴露堆栈、SQL、密钥或内部评分。
- 幂等：正式提交使用 `request_id`；导入、AI 生成和导出任务后续统一支持幂等键。
- 分页：长列表规划使用 `page`、`page_size`（默认 20、最大 100），响应 `meta.total/page/page_size/has_next`。
- 可观测性：响应附 `request_id`；服务端记录角色、对象、动作、结果和耗时，不记录敏感正文与密钥。

## 2. 已实现结构化接口

| 接口 | 权限 | 请求 | 成功响应 | 关键异常 | 页面调用 |
| --- | --- | --- | --- | --- | --- |
| `GET /health` | 公共 | 无 | `{status:"ok"}` | 500 | 容器存活检查 |
| `GET /ready` | 公共 | 无 | `{status, checks:{database,files,ai}}` | 503 未就绪 | 部署就绪检查 |
| `POST /api/student/assistant` | 学生 | `question`、`experiment_code`、`history` | SSE：`delta/done/error` | 400 输入错误、403、服务不可用 | 学生 AI 抽屉 |
| `POST /api/fitting/validate` | 学生 | 拟合结构化结果 | `{result}` | 400 校验失败 | 实验拟合页 |
| `GET /api/student/submissions` | 学生 | 无 | 本人提交修订数组 | 403 | 我的实验/报告 |
| `GET /api/teacher/submissions` | 教师 | 无 | 所属课程提交与最新审核状态数组 | 403 | 审核队列 |
| `GET /api/teacher/analytics` | 教师 | `course`、`experiment`、`task_type`、`status`、`submitted_from/to` | 课程、汇总、实验与学生明细 | 400、403 | 学情筛选抽屉、30 秒刷新 |
| `POST /api/teacher/assistant` | 教师 | `question`、`course_id` 及可选筛选 | `{answer,generated_at}` | 400、403、503 | 教师 AI 抽屉 |

## 3. 已实现报告草稿接口

| 接口 | 请求 | 返回 | 调用与冲突处理 |
| --- | --- | --- | --- |
| `GET /student/experiment/{code}/report-draft` | 路径实验代码 | 草稿、内容、资产哈希、`lock_version` | 进入报告步骤时读取；不存在时创建活动草稿 |
| `PUT /student/experiment/{code}/report-draft` | `content`、`lock_version` | 更新后的完整草稿 | 自动保存；409 `conflict` 时展示服务器版本并要求刷新/保留选择 |
| `POST .../report-draft/image` | multipart `image` | `asset_hash/url/lock_version` | 仅图片白名单；超限/非法格式返回 400/413 |
| `POST .../report-draft/translate` | `content`、`lock_version` | 翻译后草稿 | AI 失败 503；冲突 409，不覆盖新版本 |
| `POST .../report-draft/preview.pdf` | `content` | PDF 流 | 校验失败 400；页面显示阶段化生成状态 |

## 4. 已实现页面写操作

- 学生：提交预习、提交正式报告、最多两次撤回、复制历史修订为新草稿、导出本人 DOCX/PDF。
- 教师：创建课程与导入学生、重置密码、手动/AI 创建实验草稿、编辑与发布版本、生成/替换题库、复制/排序/下架/安全删除实验、保存人工审核、导出内部报告/成绩/学情。
- 所有删除、撤回、下架、替换题库、发布正式版本必须先显示强确认模态；成功使用通知，失败保留当前输入并说明恢复路径。

## 5. 后续接口规划

以下端点为规划，不得在前端伪装为已完成能力。

### 5.1 通知与待办

- `GET /api/notifications?page&page_size&unread_only` → `{data:[{id,type,title,created_at,read_at,target}],meta}`。
- `POST /api/notifications/{id}/read` → `{id,read_at}`；重复调用幂等。
- `GET /api/tasks/summary` → 学生待完成实验或教师待审核数量，不包含学生不可见评分。
- 异常：404 对象不存在；409 通知状态冲突；429 频率限制。

### 5.2 长任务与导出

- `POST /api/jobs`：`type` 为 `analytics_export/grades_export/report_export/import_students`，`parameters` 按类型校验。
- `GET /api/jobs/{job_id}` → `{status:queued|running|succeeded|failed,progress,result_url,error}`。
- `DELETE /api/jobs/{job_id}`：仅排队/运行任务可取消；完成任务返回 409。
- 页面通过通知弹窗显示开始/完成，通过抽屉展示任务列表；断网恢复后只重新查询，不重复创建任务。

### 5.3 草稿恢复与设备冲突

- `GET /api/drafts/{id}/versions?page&page_size`：只返回本人/所属对象的历史元数据与可恢复版本。
- `POST /api/drafts/{id}/restore`：`source_lock_version`、`request_id`；恢复生成新版本，不覆盖当前版本。
- 409 返回 `current_version/source_version` 摘要，模态要求用户显式选择。

### 5.4 可访问性与个人偏好

- `GET /api/preferences` → `{reduced_motion,high_contrast,density}`。
- `PUT /api/preferences`：白名单字段；服务端保存跨设备偏好，浏览器媒体查询仍优先。
- 不保存障碍类型、医疗信息等敏感推断。

## 6. 页面模块与接口映射

| 页面 | 主页面保留 | 抽屉/模态 | 接口与状态 |
| --- | --- | --- | --- |
| 学生首页 | 当前实验、完成概览、实验展廊 | AI 答疑抽屉 | 首页服务端渲染；AI SSE 含连接/中断态 |
| 我的实验 | 实验进度与筛选 | 记录详情可扩展抽屉 | 提交列表；空/错误/正常态 |
| 实验工作台 | 当前步骤内容 | 代码、帮助、AI 长内容抽屉；提交确认模态 | 草稿、拟合校验、上传、预览、提交 |
| 报告详情 | 当前报告正文 | 报告目录抽屉 | DOCX/PDF 导出；生成中/失败态 |
| 教师审核 | 审核队列 | 筛选抽屉、决定确认模态 | 提交列表、审核写入、成绩导出 |
| 学情观测 | 汇总与明细 | 筛选与 AI 分析抽屉 | analytics 查询/导出，30 秒刷新 |
| 实验管理 | 实验列表与核心状态 | AI 创建模态、危险确认模态 | 创建、复制、排序、发布、下架、删除 |
| 学生管理 | 班级与名单 | 创建/导入/重置模态 | Excel 导入、账户操作、任务观测跳转 |

## 7. 调用逻辑与异常恢复

1. 用户触发操作后先做本地必填/格式校验；失败聚焦首个字段，不发请求。
2. 不可逆操作先确认；确认后按钮进入 `aria-busy`，携带 CSRF 与幂等标识。
3. `2xx` 更新页面状态并通知成功；正式业务对象不在原记录上覆盖。
4. `400/422` 映射到字段或业务说明；`401` 引导重新登录；`403` 说明权限边界；`404` 回到安全上级页面。
5. `409` 保留用户输入并展示冲突处理；`413` 说明文件上限；`429` 显示可重试时间；`500/503` 保留现场并提供重试。
6. 网络异常区分离线与服务超时。离线不写入“成功”，恢复联网后由用户确认重试；幂等请求可安全重放。

## 8. 接口验收

- 每个接口覆盖成功、未认证、越权、输入非法、对象不存在、冲突和服务异常测试。
- 学生 API 断言绝不出现教师分数、审核决定和内部评语。
- 文件端点覆盖扩展名/MIME 双校验、大小限制、哈希不可覆盖与 `nosniff`。
- 浏览器验证加载、空、错误、离线、恢复、重复点击和多标签冲突。
- 文档新增规划端点时必须标注状态；只有后端、前端、测试与文档均完成后才能改为“已实现”。

## 9. 双层闯关与步骤数据（已实现）

- GET/POST /student/level-selection：读取和保存学生大关卡选择，按班级最低通关数校验。
- GET /student/experiment/<code>/progress：读取实验步骤完成状态和已保存数据。
- PUT /student/experiment/<code>/steps/<step_no>：保存步骤数据与完成状态。
- POST /student/experiment/<code>/steps/<step_no>/image：保存步骤图片并同步到报告草稿。
- POST /student/experiment/<code>/steps/<step_no>/fit-result：校验并保存浏览器端拟合结果，同步参数与拟合图到报告。
- POST /student/experiment/<code>/steps/<step_no>/fit-fallback：保存 Excel 拟合参数与结果图，作为在线拟合失败时的受控兜底。

步骤保存按发布版本中的结构化字段校验必填值、表格有效行、图片和拟合状态，并返回 `current_step`、`validation_errors` 与 `report_sync_conflict`。学生只能进入当前小关或已完成关；上游数据变化会清除依赖它的旧拟合结果。
