#!/usr/bin/env bash
# Dev run: start Flask on the platform-assigned port.
set -euo pipefail
cd "$(dirname "$0")/.."
# 必须显式设置 APP_ENV=preview：若缺省为 development，DEBUG=True 会启动
# Flask debug reloader（fork 双进程 + 文件变更自动重启），在平台预览环境
# 会反复触发 "Address already in use" 导致进程崩溃，表现为预览"拒绝连接"。
# preview 模式使用内置 SQLite、关闭 debug/reloader，进程稳定且不自毁。
export APP_ENV=preview
exec python3 app.py
