from __future__ import annotations

from datetime import datetime, timezone
import math

from sqlalchemy import func, select

from ..db import transaction
from ..models import AuditEvent, ExperimentVersion, Review, SubmissionRevision
from .fitting import validate_fit_result
from .scoring import fingerprint


def submit(
    student_id: str,
    version: ExperimentVersion,
    request_id: str,
    form_payload: dict,
    *,
    course_id: str | None = None,
) -> tuple[SubmissionRevision, bool]:
    with transaction() as session:
        duplicate = session.scalar(select(SubmissionRevision).where(SubmissionRevision.student_id == student_id, SubmissionRevision.request_id == request_id))
        if duplicate:
            return duplicate, False
        value = float(form_payload["result_value"])
        if not math.isfinite(value): raise ValueError("关键结果必须是有限数值")
        fit_result = validate_fit_result(form_payload.get("fit_result") or {})
        payload = {**form_payload, "result_value": value, "fit_result": fit_result}
        fp = fingerprint(version.id, payload, form_payload.get("file_hashes", []))
        previous = session.scalar(
            select(SubmissionRevision)
            .where(
                SubmissionRevision.student_id == student_id,
                SubmissionRevision.experiment_version_id == version.id,
                SubmissionRevision.course_id == course_id,
            )
            .order_by(SubmissionRevision.revision_no.desc())
        )
        revision_no = (previous.revision_no if previous else 0) + 1
        revision = SubmissionRevision(request_id=request_id, student_id=student_id, course_id=course_id, experiment_version_id=version.id, revision_no=revision_no, payload=payload, result_value=value, relative_error=0.0, deterministic_score=0, passed=False, fingerprint=fp, evaluation_id=None, supersedes_id=previous.id if previous else None)
        session.add(revision)
        session.flush()
        if previous and previous.status == "submitted":
            previous.status = "superseded"
        session.add(AuditEvent(actor_id=student_id, action="submission.create", entity_type="submission", entity_id=revision.id, detail={"revision": revision_no, "fingerprint": fp, "course_id": course_id, "grading": "teacher_only"}))
        return revision, False


def withdraw(student_id: str, submission_id: str):
    with transaction() as session:
        revision = session.get(SubmissionRevision, submission_id)
        if not revision or revision.student_id != student_id or revision.status != "submitted":
            raise ValueError("该提交不可撤回")
        count = session.scalar(select(func.count()).select_from(SubmissionRevision).where(SubmissionRevision.student_id == student_id, SubmissionRevision.experiment_version_id == revision.experiment_version_id, SubmissionRevision.withdrawn_at.is_not(None)))
        if count >= 2:
            raise ValueError("每个实验最多撤回两次")
        revision.status = "withdrawn"
        revision.withdrawn_at = datetime.now(timezone.utc)
        reviews = session.scalars(select(Review).where(Review.submission_id == revision.id, Review.superseded.is_(False))).all()
        for review in reviews:
            review.superseded = True
        session.add(AuditEvent(actor_id=student_id, action="submission.withdraw", entity_type="submission", entity_id=revision.id, detail={"withdrawal_number": count + 1, "reviews_superseded": len(reviews)}))
        return revision
