from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    teacher_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    min_experiments_required: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExperimentDraft(Base):
    __tablename__ = "experiment_drafts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    code: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(160))
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    source_asset_hash: Mapped[str | None] = mapped_column(ForeignKey("file_assets.sha256"))
    source_kind: Mapped[str] = mapped_column(String(30), default="prompt")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class CourseExperiment(Base):
    __tablename__ = "course_experiments"
    __table_args__ = (UniqueConstraint("course_id", "experiment_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    versions: Mapped[list["ExperimentVersion"]] = relationship(back_populates="experiment")


class ExperimentVersion(Base):
    __tablename__ = "experiment_versions"
    __table_args__ = (UniqueConstraint("experiment_id", "version_no"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    experiment: Mapped[Experiment] = relationship(back_populates="versions")


class QuizAssignment(Base):
    __tablename__ = "quiz_assignments"
    __table_args__ = (
        UniqueConstraint("course_id", "experiment_version_id", "signature"),
        UniqueConstraint("course_id", "student_id", "experiment_version_id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    experiment_version_id: Mapped[str] = mapped_column(ForeignKey("experiment_versions.id"), index=True)
    questions: Mapped[list] = mapped_column(JSON)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    history: Mapped[list] = mapped_column(JSON, default=list)
    signature: Mapped[str] = mapped_column(String(64))
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("fingerprint", "evaluator_version"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    evaluator_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120), default="deterministic-fallback")
    score: Mapped[int] = mapped_column(Integer)
    feedback: Mapped[str] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SubmissionRevision(Base):
    __tablename__ = "submission_revisions"
    __table_args__ = (
        UniqueConstraint("student_id", "request_id"),
        UniqueConstraint("course_id", "student_id", "experiment_version_id", "revision_no"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(String(80))
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), index=True)
    experiment_version_id: Mapped[str] = mapped_column(ForeignKey("experiment_versions.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="submitted", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result_value: Mapped[float] = mapped_column(Float)
    relative_error: Mapped[float] = mapped_column(Float)
    deterministic_score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    evaluation_id: Mapped[str | None] = mapped_column(ForeignKey("evaluations.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("submission_revisions.id"))


class ReportDraft(Base):
    __tablename__ = "report_drafts"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", "experiment_version_id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    experiment_version_id: Mapped[str] = mapped_column(ForeignKey("experiment_versions.id"), index=True)
    source_revision_id: Mapped[str | None] = mapped_column(ForeignKey("submission_revisions.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_hashes: Mapped[list] = mapped_column(JSON, default=list)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class StudentExperimentProgress(Base):
    """Student-selected experiment and step-level learning state."""

    __tablename__ = "student_experiment_progress"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", "experiment_version_id"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    experiment_version_id: Mapped[str] = mapped_column(ForeignKey("experiment_versions.id"), index=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_steps: Mapped[list] = mapped_column(JSON, default=list)
    step_data: Mapped[dict] = mapped_column(JSON, default=dict)
    asset_hashes: Mapped[list] = mapped_column(JSON, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submission_revisions.id"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    private_score: Mapped[int] = mapped_column(Integer)
    private_comment: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str] = mapped_column(String(20), default="approved", index=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Award(Base):
    __tablename__ = "awards"
    __table_args__ = (UniqueConstraint("student_id", "experiment_version_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    student_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    experiment_version_id: Mapped[str] = mapped_column(ForeignKey("experiment_versions.id"))
    score: Mapped[int] = mapped_column(Integer)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FileAsset(Base):
    __tablename__ = "file_assets"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    object_key: Mapped[str] = mapped_column(String(200), unique=True)
    original_name: Mapped[str] = mapped_column(String(240))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LegacyArchive(Base):
    __tablename__ = "legacy_archives"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    source_name: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
