from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, request, session, stream_with_context
from sqlalchemy import select

from ai_service import ai_ready, stream_student_question, student_ai_restriction

from ..db import db_session, ready as database_ready
from ..models import Course, Experiment, ExperimentVersion, SubmissionRevision
from ..services.experiments import course_for_student, published_experiments
from ..services.fitting import validate_fit_result
from ..supabase_client import auth_get_user, data_api_request, refresh_access_token
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
    payload = {
        "status": "ok",
        "service": "luojia-quantum-lab",
        "version": current_app.config.get("APP_VERSION", "1.0.0"),
    }
    # 暴露连接监控快照：数据库 / 文件 / 可选 AI 的最新健康状态，供平台
    # 探针与运维观测服务运行健康度，异常时能第一时间从日志与接口定位。
    monitor = current_app.extensions.get("health_monitor")
    if monitor is not None:
        payload["health"] = monitor.snapshot()
    return payload


@bp.get("/ready")
def ready():
    data_dir = Path(current_app.config["DATA_DIR"])
    # AI 是可选的增强能力：预览/本地环境可能未配置 AI 凭证，这不应影响
    # 核心服务的就绪判定，否则 /ready 永远 503，平台的健康探针会误判
    # 服务"未就绪/拒绝连接"。核心就绪仅由 database + files 决定。
    try:
        ai_ok = ai_ready()
    except Exception:
        ai_ok = False
    core_checks = {
        "database": database_ready(),
        "files": data_dir.exists() and data_dir.is_dir(),
    }
    optional_checks = {"ai": ai_ok}
    core_ready = all(core_checks.values())
    checks = {**core_checks, **optional_checks}
    return (
        {"status": "ready", "checks": checks},
        200,
    ) if core_ready else ({"status": "not_ready", "checks": checks}, 503)


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


# ── Supabase Auth/Data API 服务端诊断端点 ─────────────────────────
# 这些端点仅用于确认当前登录用户的 Supabase 认证与映射状态。
# 它们只返回状态与脱敏标识符，绝不返回 access_token / refresh_token 或完整 JWT 内容。


def _login_required_json(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return jsonify({"error": "未登录", "diag_status": "unauthenticated"}), 401
        return fn(*args, **kwargs)

    return wrapped


def _mask_value(value: str | None) -> str | None:
    """脱敏：长度足够时保留首尾各 4 位，否则全部遮蔽。"""
    if not value:
        return None
    if len(value) <= 4:
        return "*" * len(value)
    if len(value) <= 8:
        return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"
    return f"{value[:4]}***{value[-4:]}"


def _env_ok() -> bool:
    from ..supabase_client import _supabase_env

    return _supabase_env() is not None


def _current_cx_token(allow_refresh: bool = True) -> tuple[str | None, str | None]:
    """从当前服务端会话获取有效的超星/Supabase access_token。

    若 token 已过期且会话中存在 refresh_token，则在服务端静默刷新并更新会话。
    返回 (token, error_code)；error_code 为 None 表示成功。
    """
    access_token = session.get("cx_access_token")
    refresh_token = session.get("cx_refresh_token")
    if not access_token:
        return None, "no_token"
    if not _env_ok():
        return None, "missing_env"
    try:
        resp = auth_get_user(access_token)
    except RuntimeError:
        return None, "missing_env"
    except Exception:
        return None, "unreachable"
    if resp.status_code == 200:
        return access_token, None
    if resp.status_code in (401, 403) and allow_refresh and refresh_token:
        try:
            rresp = refresh_access_token(refresh_token)
        except RuntimeError:
            return None, "missing_env"
        except Exception:
            return None, "unreachable"
        if rresp.status_code != 200:
            return None, "refresh_failed"
        payload = rresp.json() or {}
        new_access = payload.get("access_token")
        new_refresh = payload.get("refresh_token")
        if not new_access:
            return None, "refresh_failed"
        session["cx_access_token"] = new_access
        if new_refresh:
            session["cx_refresh_token"] = new_refresh
        session.modified = True
        return new_access, None
    if resp.status_code in (401, 403):
        return None, "invalid"
    return None, "unreachable"


@bp.post("/api/diag/auth")
@_login_required_json
def diag_auth():
    """诊断当前登录用户的 Supabase Auth 状态与 auth.uid() → 本地用户映射。"""
    user = current_user()
    assert user is not None
    timestamp = datetime.now(timezone.utc).isoformat()
    if not _env_ok():
        return jsonify({
            "env_ok": False,
            "auth_status": "missing_env",
            "local_user_id": user.id,
            "local_role": user.role,
            "local_cxid_mask": _mask_value(user.chaoxing_cxid),
            "timestamp": timestamp,
        })

    access_token, error = _current_cx_token(allow_refresh=True)
    if error:
        return jsonify({
            "env_ok": True,
            "auth_status": error,
            "local_user_id": user.id,
            "local_role": user.role,
            "local_cxid_mask": _mask_value(user.chaoxing_cxid),
            "timestamp": timestamp,
        })

    try:
        resp = auth_get_user(access_token)
    except Exception:
        return jsonify({
            "env_ok": True,
            "auth_status": "unreachable",
            "local_user_id": user.id,
            "local_role": user.role,
            "local_cxid_mask": _mask_value(user.chaoxing_cxid),
            "timestamp": timestamp,
        })
    if resp.status_code != 200:
        return jsonify({
            "env_ok": True,
            "auth_status": "invalid" if resp.status_code in (401, 403) else "unreachable",
            "local_user_id": user.id,
            "local_role": user.role,
            "local_cxid_mask": _mask_value(user.chaoxing_cxid),
            "timestamp": timestamp,
        })

    verified = resp.json() or {}
    supabase_uid = str(verified.get("id") or "")
    metadata = verified.get("user_metadata") or {}
    mapped_cxid = str(metadata.get("cxid") or supabase_uid or "")
    local_cxid = user.chaoxing_cxid or ""
    mapping_match = bool(local_cxid and mapped_cxid == local_cxid)

    return jsonify({
        "env_ok": True,
        "auth_status": "ok",
        "supabase_uid_mask": _mask_value(supabase_uid),
        "local_user_id": user.id,
        "local_role": user.role,
        "local_cxid_mask": _mask_value(local_cxid),
        "mapping_match": mapping_match,
        "timestamp": timestamp,
    })


@bp.post("/api/diag/data")
@_login_required_json
def diag_data():
    """诊断当前登录用户通过自身 JWT 访问 Data API (PostgREST) 的能力。

    只查询当前用户自己的 cxid 对应行，返回脱敏后的映射字段以验证 RLS 与权限。
    """
    user = current_user()
    assert user is not None
    timestamp = datetime.now(timezone.utc).isoformat()
    local_cxid = user.chaoxing_cxid
    if not _env_ok():
        return jsonify({
            "env_ok": False,
            "data_status": "missing_env",
            "local_user_id": user.id,
            "local_cxid_mask": _mask_value(local_cxid),
            "timestamp": timestamp,
        })
    if not local_cxid:
        return jsonify({
            "env_ok": True,
            "data_status": "no_cxid",
            "local_user_id": user.id,
            "local_cxid_mask": None,
            "timestamp": timestamp,
        })

    access_token, error = _current_cx_token(allow_refresh=True)
    if error:
        return jsonify({
            "env_ok": True,
            "data_status": error,
            "local_user_id": user.id,
            "local_cxid_mask": _mask_value(local_cxid),
            "timestamp": timestamp,
        })

    path = f"/users?select=id,role,auth_user_id&cxid=eq.{quote(local_cxid, safe='')}&limit=1"
    try:
        resp = data_api_request("GET", path, access_token)
    except Exception:
        return jsonify({
            "env_ok": True,
            "data_status": "unreachable",
            "local_user_id": user.id,
            "local_cxid_mask": _mask_value(local_cxid),
            "timestamp": timestamp,
        })
    if resp.status_code in (401, 403):
        return jsonify({
            "env_ok": True,
            "data_status": "forbidden",
            "local_user_id": user.id,
            "local_cxid_mask": _mask_value(local_cxid),
            "timestamp": timestamp,
        })
    if resp.status_code != 200:
        return jsonify({
            "env_ok": True,
            "data_status": "unreachable",
            "local_user_id": user.id,
            "local_cxid_mask": _mask_value(local_cxid),
            "timestamp": timestamp,
        })

    rows = resp.json() or []
    row = rows[0] if rows else None
    safe_row = None
    if row and isinstance(row, dict):
        safe_row = {
            "id": row.get("id"),
            "role": row.get("role"),
            "auth_user_id_mask": _mask_value(str(row.get("auth_user_id") or "")),
        }
    return jsonify({
        "env_ok": True,
        "data_status": "ok" if row else "empty",
        "row_count": len(rows),
        "row": safe_row,
        "local_user_id": user.id,
        "local_cxid_mask": _mask_value(local_cxid),
        "timestamp": timestamp,
    })
