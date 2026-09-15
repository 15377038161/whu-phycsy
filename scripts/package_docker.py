#!/usr/bin/env python3
"""Build a whitelist Docker delivery package and fail on secret-like content."""
from __future__ import annotations
import re, sys, zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / f"wuda-docker-{date.today():%Y%m%d}.zip"
ROOT_FILES = {"Dockerfile", ".dockerignore", ".env.example", "README.md", "DEPLOYMENT.md", "TEACHER_LOCAL_DEPLOYMENT_GUIDE.md", "ARCHITECTURE.md", "UI_VISUAL_STANDARD.md", "FUNCTION_API_PLAN.md", "TEACHER_UI_SPEC.md", "AGENTS.md", "requirements.txt", "app.py", "ai_service.py", "auth_service.py", "docker-compose.yml"}
INCLUDE_DIRS = {"platform_app", "scripts", "static", "templates"}
EXCLUDED_PARTS = {".git", ".pytest_cache", "__pycache__", ".venv", "dist", "outputs", "uploads", "runtime", "tmp", "实例实验报告"}
EXCLUDED_FILES = {"data.json", "demo_data.json", "PROJECT_PRESENTATION_SCRIPT.md", ".env.local.example"}
SECRET = re.compile(rb"(?i)(api[_-]?key\s*[=:]\s*[A-Za-z0-9_-]{20,}|bearer\s+[A-Za-z0-9._-]{20,})")

def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in rel.parts) or rel.name in EXCLUDED_FILES: return False
    if rel.name.startswith(".env"): return rel.name == ".env.example"
    return (len(rel.parts) == 1 and rel.name in ROOT_FILES) or rel.parts[0] in INCLUDE_DIRS

def main() -> int:
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and include(p))
    required = {"Dockerfile", "docker-compose.yml", ".env.example", "TEACHER_LOCAL_DEPLOYMENT_GUIDE.md", "UI_VISUAL_STANDARD.md", "FUNCTION_API_PLAN.md", "TEACHER_UI_SPEC.md", "scripts/init_database.py", "static/fonts/simhei.ttf", "static/quantum-platform.css", "static/platform.js", "static/images/brand/whu-seal.png", "static/images/brand/whu-signature-white.png", "static/images/brand/campus-sakura.webp", "static/images/brand/sakura-certificate.webp", "static/images/experiments/ion-trap.webp", "static/images/experiments/qkd.webp", "static/images/experiments/entanglement.webp", "static/images/experiments/diamond-nv.webp", "static/images/experiments/single-pixel.webp", "static/materials/ion-trap-202510.pdf", "static/materials/qkd-material.pdf", "static/materials/entanglement-20250429.pdf", "static/materials/nv-2024-08-30.pdf", "static/materials/single-pixel-material.pdf", "templates/student_records.html", "templates/student_achievements.html", "platform_app/models.py"}
    names = {p.relative_to(ROOT).as_posix() for p in files}
    missing = required - names
    if missing: print("Packaging failed; missing: " + ", ".join(sorted(missing)), file=sys.stderr); return 1
    for path in files:
        if path.name != ".env.example" and path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".ttf", ".pdf", ".docx", ".pptx", ".xlsx"} and SECRET.search(path.read_bytes()):
            print(f"Packaging refused: secret-like content in {path.relative_to(ROOT)}", file=sys.stderr); return 1
    OUTPUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files: archive.write(path, path.relative_to(ROOT).as_posix())
    print(f"Docker delivery package: {OUTPUT} ({len(files)} files)"); return 0

if __name__ == "__main__": raise SystemExit(main())
