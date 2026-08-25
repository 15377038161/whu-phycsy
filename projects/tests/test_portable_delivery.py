from __future__ import annotations
import subprocess, sys, zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delivery_package_is_clean():
    result = subprocess.run([sys.executable, "scripts/package_docker.py"], cwd=ROOT, check=True, capture_output=True, text=True)
    package = ROOT / "dist" / f"wuda-docker-{date.today():%Y%m%d}.zip"
    assert package.exists(), result.stdout
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert {"Dockerfile", "docker-compose.yml", ".env.example", "platform_app/models.py", "static/fonts/simhei.ttf", "static/quantum-platform.css", "static/platform.js", "static/materials/ion-trap-202510.pdf", "static/materials/qkd-material.pdf", "static/materials/entanglement-20250429.pdf", "static/materials/nv-2024-08-30.pdf", "static/materials/single-pixel-material.pdf"} <= names
        forbidden = (".git", ".env.local", "data.json", "实例实验报告", "COZE", ".coze", "supabase_client", "__pycache__")
        assert not any(any(item.lower() in name.lower() for item in forbidden) for name in names)


def test_old_coze_and_supabase_runtime_are_removed():
    for path in ("db_service.py", "storage_service.py", "lib/supabase_client.py", "scripts/package_coze.py", "levels"):
        assert not (ROOT / path).exists()
