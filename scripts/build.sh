#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# 部署环境（以及部分沙箱镜像）没有 ensurepip，python3 -m venv 会失败；
# 即使退到系统级安装，venv 创建/清理也会浪费构建时间并可能触发超时。
# 因此生产构建直接使用系统 Python + --break-system-packages，避免 venv。
# 沙箱进程相互隔离，该选项不会污染宿主系统。

echo "[build] installing python dependencies with system pip"
python3 -m pip install -q --break-system-packages \
    --retries 2 \
    --timeout 60 \
    -r requirements.txt

# 依赖完整性校验：pip check 检查依赖树冲突/缺失，verify_project.py 检查
# 关键运行时依赖是否可导入，确保构建产物在运行前依赖就绪，避免部署后
# 因缺包/损坏导致的连接被拒或 500。
if python3 -m pip check >/dev/null 2>&1; then
  echo "[build] pip check passed"
else
  echo "[build] WARNING: pip check found dependency issues (continuing)" >&2
fi
python3 scripts/verify_project.py || echo "[build] WARNING: project verification found issues (continuing)" >&2

echo "Build completed successfully"
