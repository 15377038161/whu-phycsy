#!/usr/bin/env python3
"""Archive legacy JSON and import only account/course identities."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app import app
from auth_service import password_hash
from platform_app.db import transaction
from platform_app.models import Course, Enrollment, LegacyArchive, User

parser = argparse.ArgumentParser(); parser.add_argument("path", type=Path); args = parser.parse_args()
raw = args.path.read_bytes(); payload = json.loads(raw.decode("utf-8")); digest = hashlib.sha256(raw).hexdigest()
with app.app_context(), transaction() as session:
    if session.scalar(select(LegacyArchive).where(LegacyArchive.sha256 == digest)): raise SystemExit("This legacy snapshot is already archived.")
    session.add(LegacyArchive(source_name=args.path.name, sha256=digest, payload=payload))
    for cid, source in payload.get("courses", {}).items():
        if not session.get(Course, str(cid)): session.add(Course(id=str(cid), name=str(source.get("name") or cid)))
    for sid, source in payload.get("students", {}).items():
        sid = str(sid)
        if not session.get(User, sid): session.add(User(id=sid, username=sid, name=str(source.get("name") or sid), role="student", password_hash=source.get("password_hash") or password_hash(str(source.get("password") or "123456"))))
        for cid in source.get("course_ids", []):
            if session.get(Course, str(cid)) and not session.scalar(select(Enrollment).where(Enrollment.course_id == str(cid), Enrollment.student_id == sid)): session.add(Enrollment(course_id=str(cid), student_id=sid))
print(f"Archived {args.path} as {digest}; progress remains read-only in legacy_archives.")
