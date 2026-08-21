from __future__ import annotations

from datetime import datetime, timezone
import math

from sqlalchemy import func, select

from ..db import transaction
from ..models import AuditEvent, ExperimentVersion, Review, SubmissionRevision
from .fitting import validate_fit_result
from .scoring import fingerprint

ACCURACY_ERROR_CUTOFF = 999.0


def accuracy_grade(reference_value, result_value):
    """确定性准确度建议评分，仅供教师审核参考，学生端不可见。

    相对误差 = |实验结果 - 冻结参考值| / |冻结参考值|；
    误差 <=5% 给 100，<=7% 给 90，<=10% 给 85，<=15% 给 80，其余 70。
    参考值缺失或非有限数值时返回 None，表示不给出建议分。
    """
    try:
        reference = float(reference_value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(reference):
        return None
    if reference == 0:
        relative_error = 0.0 if result_value == 0 else ACCURACY_ERROR_CUTOFF
    else:
        relative_error = abs(result_value - reference) / abs(reference)
    relative_error = min(relative_error, ACCURACY_ERROR_CUTOFF)
    if relative_error <= 0.05:
        score = 100
    elif relative_error <= 0.07:
        score = 90
    elif relative_error <= 0.10:
        score = 85
    elif relative_error <= 0.15:
        score = 80
    else:
        score = 70
    return relative_error, score


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
        graded = accuracy_grade(version.definition.get("reference_value"), value)
        relative_error, deterministic_score = graded if graded else (0.0, 0)
        revision = SubmissionRevision(request_id=request_id, student_id=student_id, course_id=course_id, experiment_version_id=version.id, revision_no=revision_no, payload=payload, result_value=value, relative_error=relative_error, deterministic_score=deterministic_score, passed=False, fingerprint=fp, evaluation_id=None, supersedes_id=previous.id if previous else None)
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
