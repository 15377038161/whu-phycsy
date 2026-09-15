#!/usr/bin/env python3
"""Create the schema and sanitized defaults without overwriting existing data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from auth_service import password_hash
from platform_app.services.experiments import seed_defaults

with app.app_context():
    seed_defaults(password_hash)
print("Database schema and defaults are ready.")
