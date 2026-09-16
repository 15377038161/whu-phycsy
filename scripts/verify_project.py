#!/usr/bin/env python3
from __future__ import annotations
import importlib, py_compile, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 关键运行时依赖的导入名（requirements.txt 中的包名与 import 名可能不同）。
DEPENDENCY_IMPORTS = {
    "flask": "flask",
    "gunicorn": "gunicorn",
    "sqlalchemy": "sqlalchemy",
    "psycopg": "psycopg",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
    "xlrd": "xlrd",
    "pypdf": "pypdf",
    "reportlab": "reportlab",
    "httpx": "httpx",
    "dotenv": "python-dotenv",
}
REQUIRED = ["app.py", "ARCHITECTURE.md", "TEACHER_LOCAL_DEPLOYMENT_GUIDE.md", "UI_VISUAL_STANDARD.md", "TEACHER_UI_SPEC.md", "AGENTS.md", "Dockerfile", "docker-compose.yml", "platform_app/models.py", "platform_app/blueprints/auth.py", "platform_app/blueprints/student.py", "platform_app/blueprints/teacher.py", "platform_app/blueprints/api.py", "platform_app/services/scoring.py", "platform_app/services/submissions.py", "templates/base.html", "templates/student_home.html", "templates/student_records.html", "templates/student_achievements.html", "static/quantum-platform.css", "static/platform.js", "static/fonts/simhei.ttf", "static/images/brand/whu-seal.png", "static/images/brand/whu-signature-white.png", "static/images/brand/campus-sakura.webp", "static/images/brand/sakura-certificate.webp", "static/images/experiments/ion-trap.webp", "static/images/experiments/qkd.webp", "static/images/experiments/entanglement.webp", "static/images/experiments/diamond-nv.webp", "static/images/experiments/single-pixel.webp", "scripts/package_docker.py", "scripts/init_preview.py"]
FORBIDDEN = [".coze", "lib/supabase_client.py", "db_service.py", "storage_service.py", "scripts/package_coze.py", "COZE_DEPLOY_MANUAL.md", "templates/home.html", "levels"]

def main():
    errors=[]
    for path in REQUIRED:
        if not (ROOT/path).is_file(): errors.append(f"缺少文件: {path}")
    for path in FORBIDDEN:
        if (ROOT/path).exists(): errors.append(f"废弃入口仍存在: {path}")
    requirements=(ROOT/"requirements.txt").read_text("utf-8").lower()
    for obsolete in ("supabase", "coze-coding-dev-sdk"):
        if obsolete in requirements: errors.append(f"废弃依赖仍存在: {obsolete}")
    # 依赖完整性：逐一导入关键运行时依赖，缺装/损坏会在此暴露。
    for import_name, package_name in DEPENDENCY_IMPORTS.items():
        try:
            importlib.import_module(import_name)
        except Exception as exc:
            errors.append(f"依赖缺失或损坏: {package_name} (import {import_name}) -> {exc}")
    runtime=list(ROOT.glob("*.py"))+list((ROOT/"platform_app").rglob("*.py"))
    with tempfile.TemporaryDirectory() as temp:
        for i,path in enumerate(runtime):
            try: py_compile.compile(str(path),cfile=str(Path(temp)/f"{i}.pyc"),doraise=True)
            except py_compile.PyCompileError as exc: errors.append(f"Python 语法错误: {path.relative_to(ROOT)}: {exc.msg}")
    if errors:
        print("项目验证失败："); [print("- "+e) for e in errors]; return 1
    print(f"项目验证通过：{len(REQUIRED)} 个关键文件，{len(runtime)} 个 Python 模块。"); return 0

if __name__ == "__main__": sys.exit(main())
