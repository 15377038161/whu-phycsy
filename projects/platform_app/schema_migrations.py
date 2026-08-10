from __future__ import annotations

import uuid

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def _column_names(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _add_column(connection, table: str, definition: str) -> None:
    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {definition}"))


def _upgrade_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    dialect = engine.dialect.name
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "DATETIME"
    bool_default = "false" if dialect == "postgresql" else "0"
    with engine.begin() as connection:
        if "must_change_password" not in _column_names(inspector, "users"):
            _add_column(connection, "users", f"must_change_password BOOLEAN NOT NULL DEFAULT {bool_default}")
        if "teacher_id" not in _column_names(inspector, "courses"):
            _add_column(connection, "courses", "teacher_id VARCHAR(64) REFERENCES users(id)")
        quiz_columns = _column_names(inspector, "quiz_assignments")
        if "completed_at" not in quiz_columns:
            _add_column(connection, "quiz_assignments", f"completed_at {timestamp_type}")
        if "attempt_no" not in quiz_columns:
            _add_column(connection, "quiz_assignments", "attempt_no INTEGER NOT NULL DEFAULT 1")
        if "history" not in quiz_columns:
            _add_column(connection, "quiz_assignments", "history JSON NOT NULL DEFAULT '[]'")
        if "course_id" not in _column_names(inspector, "submission_revisions"):
            _add_column(connection, "submission_revisions", "course_id VARCHAR(64) REFERENCES courses(id)")
        if "decision" not in _column_names(inspector, "reviews"):
            _add_column(connection, "reviews", "decision VARCHAR(20) NOT NULL DEFAULT 'approved'")
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_courses_teacher_id ON courses (teacher_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_submission_revisions_course_id ON submission_revisions (course_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_decision ON reviews (decision)"))


def _upgrade_quiz_constraint(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    constraints = inspector.get_unique_constraints("quiz_assignments")
    old = next(
        (
            item
            for item in constraints
            if set(item.get("column_names") or []) == {"student_id", "experiment_version_id"}
        ),
        None,
    )
    target_exists = any(
        set(item.get("column_names") or [])
        == {"course_id", "student_id", "experiment_version_id"}
        for item in constraints
    )
    with engine.begin() as connection:
        if old and old.get("name"):
            quoted = connection.dialect.identifier_preparer.quote(old["name"])
            connection.execute(text(f"ALTER TABLE quiz_assignments DROP CONSTRAINT {quoted}"))
        if not target_exists:
            connection.execute(
                text(
                    "ALTER TABLE quiz_assignments ADD CONSTRAINT "
                    "uq_quiz_course_student_version UNIQUE "
                    "(course_id, student_id, experiment_version_id)"
                )
            )


def _upgrade_submission_constraint(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    constraints = inspector.get_unique_constraints("submission_revisions")
    old = next(
        (
            item
            for item in constraints
            if set(item.get("column_names") or [])
            == {"student_id", "experiment_version_id", "revision_no"}
        ),
        None,
    )
    target_exists = any(
        set(item.get("column_names") or [])
        == {"course_id", "student_id", "experiment_version_id", "revision_no"}
        for item in constraints
    )
    with engine.begin() as connection:
        if old and old.get("name"):
            quoted = connection.dialect.identifier_preparer.quote(old["name"])
            connection.execute(
                text(f"ALTER TABLE submission_revisions DROP CONSTRAINT {quoted}")
            )
        if not target_exists:
            connection.execute(
                text(
                    "ALTER TABLE submission_revisions ADD CONSTRAINT "
                    "uq_submission_course_student_version_revision UNIQUE "
                    "(course_id, student_id, experiment_version_id, revision_no)"
                )
            )


def _backfill_relations(engine: Engine) -> None:
    from .models import (
        Course,
        CourseExperiment,
        Enrollment,
        Experiment,
        QuizAssignment,
        SubmissionRevision,
        User,
    )

    with Session(engine, expire_on_commit=False) as session:
        teacher_id = session.scalar(
            select(User.id)
            .where(User.role == "teacher")
            .order_by(User.created_at, User.id)
        )
        if teacher_id:
            for course in session.scalars(select(Course).where(Course.teacher_id.is_(None))):
                course.teacher_id = teacher_id

        experiments = session.scalars(
            select(Experiment)
            .where(Experiment.retired.is_(False))
            .order_by(Experiment.order_no, Experiment.id)
        ).all()
        for course in session.scalars(select(Course)).all():
            existing = set(
                session.scalars(
                    select(CourseExperiment.experiment_id).where(
                        CourseExperiment.course_id == course.id
                    )
                ).all()
            )
            if existing:
                continue
            for position, experiment in enumerate(experiments, start=1):
                session.add(
                    CourseExperiment(
                        id=str(uuid.uuid4()),
                        course_id=course.id,
                        experiment_id=experiment.id,
                        position=position,
                        active=True,
                    )
                )

        for assignment in session.scalars(
            select(QuizAssignment).where(QuizAssignment.completed_at.is_(None))
        ):
            if assignment.answers:
                assignment.completed_at = assignment.frozen_at

        for revision in session.scalars(
            select(SubmissionRevision).where(SubmissionRevision.course_id.is_(None))
        ):
            course_id = session.scalar(
                select(QuizAssignment.course_id)
                .where(
                    QuizAssignment.student_id == revision.student_id,
                    QuizAssignment.experiment_version_id == revision.experiment_version_id,
                )
                .order_by(QuizAssignment.frozen_at.desc())
            )
            if not course_id:
                enrolled = session.scalars(
                    select(Enrollment.course_id).where(
                        Enrollment.student_id == revision.student_id
                    )
                ).all()
                if len(enrolled) == 1:
                    course_id = enrolled[0]
            revision.course_id = course_id
        session.commit()


def migrate_schema(engine: Engine) -> None:
    """Idempotently upgrade existing PostgreSQL and local SQLite schemas."""

    _upgrade_columns(engine)
    _upgrade_quiz_constraint(engine)
    _upgrade_submission_constraint(engine)
    _backfill_relations(engine)
