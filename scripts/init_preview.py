#!/usr/bin/env python3
"""Create the isolated demo student/course only in an explicit preview environment."""
from __future__ import annotations

from flask import current_app
from sqlalchemy import select

from auth_service import password_hash
from platform_app import create_app
from platform_app.db import transaction
from platform_app.models import Course, Enrollment, User


def main() -> None:
    app = create_app()
    with app.app_context():
        if current_app.config["APP_ENV"] != "preview":
            raise RuntimeError("Preview bootstrap is only allowed when APP_ENV=preview")
        with transaction() as session:
            if not session.get(User, "S001"):
                session.add(User(id="S001", username="S001", name="演示学生", role="student", password_hash=password_hash("123456")))
            if not session.get(Course, "C001"):
                session.add(Course(id="C001", name="量子实验演示班"))
            enrolled = session.scalar(select(Enrollment).where(Enrollment.course_id == "C001", Enrollment.student_id == "S001"))
            if not enrolled:
                session.add(Enrollment(course_id="C001", student_id="S001"))
    print("Preview student and course are ready.")


if __name__ == "__main__":
    main()
