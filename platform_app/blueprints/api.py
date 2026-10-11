from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, render_template, request, session, stream_with_context
from sqlalchemy import select

from ai_service import ai_ready, stream_student_question, student_ai_restriction

from ..db import db_session, ready as database_ready
from ..diag_runtime import runtime_diagnostic_payload
from ..models import Course, Experiment, ExperimentVersion, SubmissionRevision
from ..services.experiments import course_for_student, published_experiments
from ..services.fitting import validate_fit_result
from ..supabase_client import _env_ok as _supabase_env_ok, data_api_request
from ..teacher_ai import answer_teacher_question
from ..teacher_analytics import build_teacher_ai_snapshot, get_teacher_analytics
from .auth import _refresh_access_token, _verify_access_token, current_user, role_required

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


def _current_valid_token() -> tuple[str | None, str | None]:
    """从当前服务端会话获取有效的 Supabase access_token，必要时静默刷新。

    复用 auth.py 的 `_verify_access_token` / `_refresh_access_token`，刷新后必须
    重新调用 getUser 验证，才能确认新 token 有效。返回 (token, error_code)。
    """
    access_token = session.get("cx_access_token")
    refresh_token = session.get("cx_refresh_token")
    if not access_token:
        return None, "no_token"

    user, _error = _verify_access_token(access_token)
    if user is not None:
        return access_token, None

    if not refresh_token:
        return None, "invalid"

    payload, _refresh_error = _refresh_access_token(refresh_token)
    if payload is None:
        return None, "invalid"

    new_access = payload.get("access_token")
    new_refresh = payload.get("refresh_token")
    if not new_access:
        return None, "invalid"

    # 刷新后必须重新 getUser 验证，不能直接信任刷新响应。
    user, _verify_error = _verify_access_token(new_access)
    if user is None:
        return None, "invalid"

    session["cx_access_token"] = new_access
    if new_refresh:
        session["cx_refresh_token"] = new_refresh
    session.modified = True
    return new_access, None


def _diag_response(status: str) -> Response:
    """返回固定诊断状态；浏览器表单提交时渲染简单 HTML，API/测试返回 JSON。"""
    if "text/html" in request.accept_mimetypes:
        html = (
            "<!doctype html><html lang=\"zh-CN\">"
            "<head><meta charset=\"utf-8\"><title>连接诊断</title></head>"
            f"<body><h1>连接诊断</h1><p>状态：<code>{status}</code></p>"
            "<button onclick=\"history.back()\">返回</button></body></html>"
        )
        return Response(html, content_type="text/html; charset=utf-8")
    return jsonify({"status": status})


@bp.post("/api/diag/auth")
@_login_required_json
def diag_auth():
    """诊断当前登录用户的 Supabase Auth 状态。

    仅返回固定状态枚举，不输出 user_id、role、cxid、JWT、SID 或任何个人资料。
    """
    if not _supabase_env_ok():
        return _diag_response("missing_env")

    _access_token, error = _current_valid_token()
    if error:
        return _diag_response(error)

    return _diag_response("ok")


@bp.post("/api/diag/data")
@_login_required_json
def diag_data():
    """诊断当前登录用户通过自身 JWT 访问 Data API 的能力。

    先 Auth getUser 取得已验证 UUID，再按 auth_user_id=eq.本人UUID 查询 users 表，
    逐行确认归属后只返回 mapping_exists 对应的固定状态。禁止用 user_metadata.cxid
    授权，禁止回退到 cxid 推断映射，不返回行内容或个人资料。
    """
    if not _supabase_env_ok():
        return _diag_response("missing_env")

    access_token, error = _current_valid_token()
    if error:
        return _diag_response(error)

    user, _error = _verify_access_token(access_token)
    if user is None:
        return _diag_response("invalid")

    auth_uid = str(user.get("id") or "")
    if not auth_uid:
        return _diag_response("invalid")

    path = f"/users?select=auth_user_id&auth_user_id=eq.{quote(auth_uid, safe='')}&limit=1"
    try:
        resp = data_api_request("GET", path, access_token)
    except Exception:
        return _diag_response("unreachable")

    if resp.status_code in (401, 403):
        return _diag_response("forbidden")
    if resp.status_code != 200:
        return _diag_response("unreachable")

    try:
        rows = resp.json() or []
    except Exception:
        return _diag_response("unreachable")

    mapping_exists = any(
        isinstance(row, dict) and str(row.get("auth_user_id") or "") == auth_uid
        for row in rows
    )
    return _diag_response("ok" if mapping_exists else "forbidden")


@bp.get("/diag")
def diag_index():
    """Render the connection diagnostics page with CSRF-protected forms.

    Requires a logged-in session; anonymous access is denied.
    """
    if current_user() is None:
        return jsonify({"error": "未登录", "diag_status": "unauthenticated"}), 401
    return render_template("diag.html")


@bp.post("/api/diag/runtime")
@_login_required_json
def diag_runtime():
    """Return strict allow-list runtime self-attestation facts.

    The response proves which code path is actually loaded, how AI is
    configured, and whether the current JWT can see any enrollment rows.
    No secrets, paths, hostnames, URLs, JWT claims, user lists, or raw
    exception text are emitted.

    CSRF protection is enforced by the global `protect_state_changes` hook in
    `platform_app/__init__.py`; this endpoint does not accept anonymous requests.
    """
    payload = runtime_diagnostic_payload()
    if "text/html" in request.accept_mimetypes:
        rows = "".join(f"<tr><td>{k}</td><td><code>{v}</code></td></tr>" for k, v in payload.items())
        html = (
            "<!doctype html><html lang=\"zh-CN\">"
            "<head><meta charset=\"utf-8\"><title>运行版本诊断</title></head>"
            "<body><h1>运行版本诊断</h1>"
            "<table border=\"1\" cellpadding=\"6\"><tr><th>字段</th><th>值</th></tr>"
            f"{rows}</table>"
            "<button onclick=\"history.back()\">返回</button></body></html>"
        )
        return Response(html, content_type="text/html; charset=utf-8")
    return jsonify(payload)
