from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from sqlalchemy import select

from ai_service import ai_ready, stream_student_question, student_ai_restriction

from ..db import db_session, ready as database_ready
from ..models import Course, Experiment, ExperimentVersion, SubmissionRevision
from ..services.experiments import course_for_student, published_experiments
from ..services.fitting import validate_fit_result
from ..teacher_ai import answer_teacher_question
from ..teacher_analytics import build_teacher_ai_snapshot, get_teacher_analytics
from .auth import current_user, role_required

bp = Blueprint("api", __name__)


def _iso_datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@bp.get("/health")
def health():
    return {"status": "ok"}


@bp.get("/ready")
def ready():
    data_dir = Path(current_app.config["DATA_DIR"])
    try: ai_ok = ai_ready()
    except Exception: ai_ok = False
    checks = {"database": database_ready(), "files": data_dir.exists() and data_dir.is_dir(), "ai": ai_ok}
    return ({"status": "ready", "checks": checks}, 200) if all(checks.values()) else ({"status": "not_ready", "checks": checks}, 503)


@bp.post("/api/student/assistant")
@role_required("student")
def student_assistant():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question:
        return {"error": "请先输入问题。"}, 400
    if len(question) > 800:
        return {"error": "问题过长，请精简到 800 字以内。"}, 400
    restriction = student_ai_restriction(question)
    if restriction:
        return {"answer": restriction, "restricted": True}
    code = str(payload.get("experiment_code", "")).strip().upper()[:12]
    user = current_user()
    course = course_for_student(db_session(), user.id)
    selected = next(((exp, version) for exp, version in published_experiments(db_session(), course.id if course else None) if exp.code == code), None)
    if not selected:
        return {"answer": "请先进入具体实验页面。我只能解释当前实验原理，或提醒该实验已经发布的操作步骤。", "restricted": True}
    exp, version = selected
    definition = version.definition or {}
    context = "\n".join([
        f"实验名称：{exp.title}",
        f"实验原理：{str(definition.get('principle', ''))[:3000]}",
        "已发布操作步骤：",
        *[f"{index}. {str(step)[:600]}" for index, step in enumerate((definition.get("steps") or [])[:12], 1)],
    ])
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    def events():
        try:
            for chunk in stream_student_question(question, context, history):
                yield f"data: {json.dumps({'type': 'delta', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception:
            yield f"data: {json.dumps({'type': 'error', 'error': 'AI 答疑服务暂时不可用，请稍后重试。'}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(events()),
        content_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@bp.post("/api/fitting/validate")
@role_required("student")
def fitting_validate():
    try:
        return {"result": validate_fit_result(request.get_json(silent=True) or {})}
    except ValueError as exc:
        return {"error": str(exc)}, 400


@bp.get("/api/student/submissions")
@role_required("student")
def student_submissions():
    user = current_user()
    rows = db_session().execute(select(SubmissionRevision, Experiment).join(ExperimentVersion, ExperimentVersion.id == SubmissionRevision.experiment_version_id).join(Experiment, Experiment.id == ExperimentVersion.experiment_id).where(SubmissionRevision.student_id == user.id).order_by(SubmissionRevision.submitted_at.desc())).all()
    return jsonify([{"id": row.id, "experiment": exp.title, "revision": row.revision_no, "status": row.status, "submitted_at": row.submitted_at.isoformat()} for row, exp in rows])


@bp.get("/api/teacher/submissions")
@role_required("teacher")
def teacher_submissions():
    from ..models import Review, User
    user = current_user()
    course_ids = db_session().scalars(select(Course.id).where(Course.teacher_id == user.id)).all()
    rows = db_session().execute(select(SubmissionRevision, User, Experiment).join(User, User.id == SubmissionRevision.student_id).join(ExperimentVersion, ExperimentVersion.id == SubmissionRevision.experiment_version_id).join(Experiment, Experiment.id == ExperimentVersion.experiment_id).where(SubmissionRevision.course_id.in_(course_ids)).order_by(SubmissionRevision.submitted_at.desc())).all() if course_ids else []
    result = []
    for revision, student, exp in rows:
        review = db_session().scalar(select(Review).where(Review.submission_id == revision.id).order_by(Review.created_at.desc()))
        result.append({"id": revision.id, "student": student.name, "student_id": student.id, "experiment": exp.title, "status": revision.status, "review_status": review.decision if review else "pending", "submitted_at": revision.submitted_at.isoformat()})
    return jsonify(result)


@bp.get("/api/teacher/analytics")
@role_required("teacher")
def teacher_analytics():
    try:
        result = get_teacher_analytics(
            db_session(),
            current_user().id,
            course_id=request.args.get("course") or None,
            experiment_id=request.args.get("experiment") or None,
            task_type=request.args.get("task_type") or None,
            status=request.args.get("status") or None,
            submitted_from=_iso_datetime(request.args.get("submitted_from")),
            submitted_to=_iso_datetime(request.args.get("submitted_to")),
        )
        return jsonify(result)
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}, 400


@bp.post("/api/teacher/assistant")
@role_required("teacher")
def teacher_assistant():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    try:
        analytics = get_teacher_analytics(
            db_session(),
            current_user().id,
            course_id=str(payload.get("course_id") or "") or None,
            experiment_id=str(payload.get("experiment_id") or "") or None,
            task_type=str(payload.get("task_type") or "") or None,
            status=str(payload.get("status") or "") or None,
            submitted_from=_iso_datetime(payload.get("submitted_from")),
            submitted_to=_iso_datetime(payload.get("submitted_to")),
        )
        answer = answer_teacher_question(question, build_teacher_ai_snapshot(analytics))
        return {"answer": answer, "generated_at": analytics["generated_at"]}
    except PermissionError as exc:
        return {"error": str(exc)}, 403
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}, 400
    except RuntimeError as exc:
        return {"error": str(exc)}, 503
