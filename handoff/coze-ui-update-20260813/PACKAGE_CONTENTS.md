# 交接包内容与校验值

## 代码覆盖包

- 文件：`coze-ui-update-overwrite-20260813.zip`
- 大小：131,453 字节
- ZIP 条目：16
- SHA-256：`CAE90AFB62F00F3337DC99568C4A1D26F5D095F6E470ED02668E83A8CD82F3E5`

内容：6 个运行时文件、4 个项目规范/打包文件、4 个交接说明文件、`UPDATE_MANIFEST.json`、`TRACKED_CHANGES.patch`。

## 视觉参考包

- 文件：`coze-ui-preview-reference-20260813.zip`
- 大小：19,485,322 字节
- ZIP 条目：23
- SHA-256：`07F70C538D82E15A955F1BE43A24D0C82D00303A752090ADE9060B5CD4F452C3`

内容：13 张移动端 AI 页面预览、预览页面清单、6 张弹层专项截图和 3 张多端全局 UX 截图。

视觉参考包不属于生产运行文件，不要解压到 Coze 应用代码目录。

## 完整 Docker 交付包

- 文件：`D:\coze\wuda\dist\wuda-docker-20260813.zip`
- SHA-256：`4F861D52B20DB9D19070211FAECB9BE4229854F08F811E7C2B72D4E78BD8AEAC`

当 Coze 已部署版本不是同一 Flask/Jinja 架构时，应使用完整 Docker 包迁移，不使用局部覆盖包。
