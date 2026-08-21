from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_, select

from ..db import db_session, transaction
from ..models import Course, CourseExperiment, Experiment, ExperimentVersion, FileAsset, QuizAssignment, ReportDraft, SubmissionRevision
from ..services.experiments import course_for_student, ensure_course_experiments, frozen_quiz, published_experiments, restart_quiz
from ..services.submissions import submit, withdraw
from ..services.reporting import build_docx, build_pdf, report_document
from ..services.files import IMAGE_UPLOADS, STUDENT_ATTACHMENT_UPLOADS, save_upload
from ..services.report_drafts import copy_revision_to_draft, get_or_create_draft, payload_from_document, save_draft, validate_document, validate_submission_document
from ai_service import translate_report_frontmatter
from .auth import current_user, role_required

bp = Blueprint("student", __name__, url_prefix="/student")

ACHIEVEMENT_META = {
    "ION": {"icon": "atom", "label": "离子囚禁与精密测量", "description": "完成离子阱实验的预习、操作、拟合与正式报告提交。"},
    "QKD": {"icon": "key-round", "label": "量子密钥与安全通信", "description": "完成量子密钥分发实验的预习、操作、拟合与正式报告提交。"},
    "ENT": {"icon": "link-2", "label": "量子关联与纠缠验证", "description": "完成量子纠缠实验的预习、操作、拟合与正式报告提交。"},
    "NV": {"icon": "gem", "label": "固态量子与相干操控", "description": "完成金刚石量子计算机实验的预习、操作、拟合与正式报告提交。"},
    "SPI": {"icon": "scan-line", "label": "计算成像与光场重建", "description": "完成单像素光子成像实验的预习、操作、拟合与正式报告提交。"},
}


def _activity_timestamp(value) -> float:
    if not value:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _quiz_score(assignment: QuizAssignment | None) -> int | None:
    if not assignment:
        return None
    attempts = []
    if assignment.completed_at:
        attempts.append({"questions": assignment.questions or [], "answers": assignment.answers or {}})
    attempts.extend(reversed(assignment.history or []))
    for attempt in attempts:
        questions = attempt.get("questions") or []
        answers = attempt.get("answers") or {}
        if questions and len(answers) == len(questions):
            correct_count = sum(answers.get(question.get("id")) == question.get("answer") for question in questions)
            return correct_count * 10
    return None


def _current_experiment(items, activity_at):
    if not items:
        return None, "", ""
    active = [item for item in items if item[0].id in activity_at]
    if active:
        featured = max(active, key=lambda item: _activity_timestamp(activity_at[item[0].id]))
        return featured, "当前实验 · CONTINUE LEARNING", "继续实验"
    return items[0], "当前实验 · NEXT EXPERIMENT", "开始实验"


def _achievement_context(items, user_id: str):
    achievements = []
    for exp, version, latest in items:
        meta = ACHIEVEMENT_META.get(exp.code)
        if not meta:
            continue
        unlocked = bool(latest and latest.status == "submitted")
        achievements.append({
            "code": exp.code,
            "title": exp.title,
            "summary": meta["label"],
            "description": meta["description"],
            "icon": meta["icon"],
            "unlocked": unlocked,
            "revision_no": latest.revision_no if unlocked else None,
            "unlocked_at": latest.submitted_at if unlocked else None,
        })
    unlocked = [item for item in achievements if item["unlocked"]]
    selected = max(unlocked, key=lambda item: _activity_timestamp(item["unlocked_at"])) if unlocked else (achievements[0] if achievements else None)
    return {
        "achievement_items": achievements,
        "achievement_selected": selected,
        "achievement_unlocked_count": len(unlocked),
        "achievement_owner_key": hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16],
    }


def _student_progress_context(user_id: str, course: Course | None):
    """Build the student's single experiment catalogue without exposing review data."""
    catalog = published_experiments(db_session(), course.id if course else None)
    revision_rows = db_session().execute(
        select(SubmissionRevision, ExperimentVersion)
        .join(ExperimentVersion, ExperimentVersion.id == SubmissionRevision.experiment_version_id)
        .where(SubmissionRevision.student_id == user_id)
        .order_by(SubmissionRevision.submitted_at.desc())
    ).all()
    latest_by_experiment = {}
    for revision, version in revision_rows:
        latest_by_experiment.setdefault(version.experiment_id, revision)
    assignment_rows = db_session().execute(
        select(QuizAssignment, ExperimentVersion)
        .join(ExperimentVersion, ExperimentVersion.id == QuizAssignment.experiment_version_id)
        .where(QuizAssignment.student_id == user_id)
        .order_by(QuizAssignment.frozen_at.desc())
    ).all()
    assignment_by_experiment = {}
    for assignment, version in assignment_rows:
        assignment_by_experiment.setdefault(version.experiment_id, assignment)

    items, progress_items = [], []
    for exp, version in catalog:
        latest = latest_by_experiment.get(exp.id)
        assignment = assignment_by_experiment.get(exp.id)
        score = _quiz_score(assignment)
        if latest and latest.status == "submitted":
            state, label, progress = "completed", "已完成", 100
        elif assignment and assignment.completed_at:
            state, label, progress = "incomplete", "待提交报告", 75
        elif assignment and assignment.answers:
            state, label, progress = "incomplete", "预习进行中", 35
        else:
            state, label, progress = "incomplete", "未开始", 0
        items.append((exp, version, latest))
        progress_items.append({
            "exp": exp, "version": version, "revision": latest, "quiz_score": score,
            "state": state, "label": label, "progress": progress,
        })
    return items, progress_items, revision_rows


def _version(code: str, student_id: str | None = None, course_id: str | None = None):
    if student_id:
        draft_statement = (
            select(ExperimentVersion)
            .join(ReportDraft, ReportDraft.experiment_version_id == ExperimentVersion.id)
            .join(Experiment)
            .where(
                Experiment.code == code,
                ReportDraft.student_id == student_id,
                ReportDraft.status == "active",
                or_(ReportDraft.source_revision_id.is_not(None), ReportDraft.lock_version > 1),
            )
            .order_by(ReportDraft.updated_at.desc())
        )
        if course_id:
            draft_statement = draft_statement.where(ReportDraft.course_id == course_id)
        draft_version = db_session().scalar(draft_statement)
        if draft_version:
            return draft_version
        pinned_rows = db_session().execute(
            select(QuizAssignment, ExperimentVersion)
            .join(ExperimentVersion, QuizAssignment.experiment_version_id == ExperimentVersion.id)
            .join(Experiment)
            .where(
                Experiment.code == code,
                QuizAssignment.student_id == student_id,
                *( [QuizAssignment.course_id == course_id] if course_id else [] ),
            )
            .order_by(QuizAssignment.frozen_at.desc())
        ).all()
        for assignment, pinned in pinned_rows:
            submitted = db_session().scalar(select(SubmissionRevision.id).where(SubmissionRevision.student_id == student_id, SubmissionRevision.experiment_version_id == pinned.id))
            if assignment.answers and not submitted:
                return pinned
    statement = (
        select(ExperimentVersion)
        .join(Experiment)
        .where(Experiment.code == code, ExperimentVersion.status == "published")
    )
    if course_id:
        statement = statement.join(
            CourseExperiment,
            CourseExperiment.experiment_id == Experiment.id,
        ).where(
            CourseExperiment.course_id == course_id,
            CourseExperiment.active.is_(True),
        )
    return db_session().scalar(statement.order_by(ExperimentVersion.version_no.desc()))


@bp.get("/home")
@role_required("student")
def home():
    user = current_user()
    course = course_for_student(db_session(), user.id)
    if course:
        with transaction() as tx:
            ensure_course_experiments(tx, tx.get(Course, course.id))
    submission_rows = db_session().execute(
        select(SubmissionRevision, ExperimentVersion)
        .join(ExperimentVersion, ExperimentVersion.id == SubmissionRevision.experiment_version_id)
        .where(SubmissionRevision.student_id == user.id)
        .order_by(SubmissionRevision.submitted_at.desc())
    ).all()
    latest_by_experiment = {}
    activity_at = {}
    for revision, revision_version in submission_rows:
        latest_by_experiment.setdefault(revision_version.experiment_id, revision)
        current = activity_at.get(revision_version.experiment_id)
        if current is None or _activity_timestamp(revision.submitted_at) > _activity_timestamp(current):
            activity_at[revision_version.experiment_id] = revision.submitted_at
    quiz_rows = db_session().execute(
        select(QuizAssignment, ExperimentVersion)
        .join(ExperimentVersion, ExperimentVersion.id == QuizAssignment.experiment_version_id)
        .where(QuizAssignment.student_id == user.id, *([QuizAssignment.course_id == course.id] if course else []))
        .order_by(QuizAssignment.frozen_at.desc())
    ).all()
    quiz_score_map = {}
    for assignment, assignment_version in quiz_rows:
        current = activity_at.get(assignment_version.experiment_id)
        if current is None or _activity_timestamp(assignment.frozen_at) > _activity_timestamp(current):
            activity_at[assignment_version.experiment_id] = assignment.frozen_at
        score = _quiz_score(assignment)
        if assignment_version.experiment_id not in quiz_score_map and score is not None:
            quiz_score_map[assignment_version.experiment_id] = score
    items = []
    for exp, version in published_experiments(db_session(), course.id if course else None):
        latest = latest_by_experiment.get(exp.id)
        items.append((exp, version, latest))
    cover_assets = {}
    for _, version, _ in items:
        cover_hash = version.definition.get("cover_image_hash")
        if cover_hash:
            cover_assets[version.id] = db_session().get(FileAsset, cover_hash)
    featured, featured_kicker, featured_action = _current_experiment(items, activity_at)
    completed_experiment_count = sum(1 for revision in latest_by_experiment.values() if revision.status == "submitted")
    achievement_context = _achievement_context(items, user.id)
    certificate_code = request.args.get("certificate", "").strip()
    certificate_item = next((item for item in achievement_context["achievement_items"] if item["code"] == certificate_code and item["unlocked"]), None)
    return render_template("student_home.html", user=user, course=course, items=items, quiz_score_map=quiz_score_map, completed_experiment_count=completed_experiment_count, submission_count=len(submission_rows), cover_assets=cover_assets, featured=featured, featured_kicker=featured_kicker, featured_action=featured_action, certificate_item=certificate_item, **achievement_context)


@bp.get("/records")
@role_required("student")
def records():
    user = current_user()
    course = course_for_student(db_session(), user.id)
    items, progress_items, revision_rows = _student_progress_context(user.id, course)
    return render_template(
        "student_records.html", user=user, course=course, items=items, progress_items=progress_items,
        revision_count=len(revision_rows), completed_count=sum(item["state"] == "completed" for item in progress_items),
    )


@bp.get("/achievements")
@role_required("student")
def achievements():
    user = current_user()
    course = course_for_student(db_session(), user.id)
    items, _, _ = _student_progress_context(user.id, course)
    reports = db_session().execute(
        select(SubmissionRevision, Experiment, ExperimentVersion)
        .join(ExperimentVersion, ExperimentVersion.id == SubmissionRevision.experiment_version_id)
        .join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
        .where(SubmissionRevision.student_id == user.id)
        .order_by(SubmissionRevision.submitted_at.desc())
    ).all()
    return render_template("student_achievements.html", user=user, reports=reports, **_achievement_context(items, user.id))


@bp.route("/experiment/<code>", methods=["GET", "POST"])
@role_required("student")
def experiment(code):
    user = current_user()
    course = course_for_student(db_session(), user.id)
    if not course:
        return "学生尚未加入课程", 403
    version = _version(code, user.id, course.id)
    if not version:
        return "实验不存在", 404
    exp = db_session().get(Experiment, version.experiment_id)
    with transaction() as tx:
        quiz = frozen_quiz(tx, user.id, course.id, tx.get(ExperimentVersion, version.id))
    if request.method == "POST" and request.form.get("action") == "quiz":
        if quiz.completed_at:
            flash("本次预习题已经提交，答案不能覆盖；如需重做请重新抽取不同题目。", "error")
            return redirect(url_for("student.experiment", code=code) + "#quiz")
        answers = {q["id"]: request.form.get(q["id"], "") for q in quiz.questions}
        if len(answers) != 10 or any(not answer for answer in answers.values()):
            flash("请完成全部十道预习题后再提交。", "error")
            return redirect(url_for("student.experiment", code=code) + "#quiz")
        with transaction() as tx:
            saved = tx.get(QuizAssignment, quiz.id)
            if saved.completed_at:
                raise ValueError("本次预习题已经提交，不能重复覆盖")
            saved.answers = answers
            saved.completed_at = datetime.now(timezone.utc)
        correct = sum(answers.get(q["id"]) == q["answer"] for q in quiz.questions)
        flash(f"第 {quiz.attempt_no or 1} 次预习已提交，答对 {correct}/10 题；请逐题查看对错和解析。", "success")
        return redirect(url_for("student.experiment", code=code) + "#quiz")
    if request.method == "POST" and request.form.get("action") == "quiz_retake":
        try:
            with transaction() as tx:
                restarted = restart_quiz(tx, tx.get(QuizAssignment, quiz.id), tx.get(ExperimentVersion, version.id), user.id)
            flash(f"已生成第 {restarted.attempt_no} 套预习题，历史原题已全部排除，题目和选项顺序也已重新排列。", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("student.experiment", code=code) + "#quiz")
    latest = db_session().scalar(select(SubmissionRevision).where(SubmissionRevision.student_id == user.id, SubmissionRevision.experiment_version_id == version.id).order_by(SubmissionRevision.revision_no.desc()))
    demo_asset = db_session().get(FileAsset, version.definition.get("demo_video_hash")) if version.definition.get("demo_video_hash") else None
    with transaction() as tx:
        draft = get_or_create_draft(tx, tx.get(type(user), user.id), course.id, tx.get(ExperimentVersion, version.id), tx.get(Experiment, exp.id))
    quiz_score = sum((quiz.answers or {}).get(q["id"]) == q["answer"] for q in quiz.questions) if quiz.completed_at else None
    return render_template("experiment.html", user=user, exp=exp, version=version, quiz=quiz, quiz_score=quiz_score, latest=latest, evaluation=None, demo_asset=demo_asset, report_draft=draft, pyodide_base_url=__import__('flask').current_app.config["PYODIDE_BASE_URL"])


def _draft_context(code: str):
    user = current_user()
    course = course_for_student(db_session(), user.id)
    if not course:
        return None
    version = _version(code, user.id, course.id)
    if not version:
        return None
    experiment = db_session().get(Experiment, version.experiment_id)
    draft = db_session().scalar(select(ReportDraft).where(ReportDraft.course_id == course.id, ReportDraft.student_id == user.id, ReportDraft.experiment_version_id == version.id))
    return user, course, version, experiment, draft


def _draft_response(draft: ReportDraft):
    return {
        "id": draft.id,
        "status": draft.status,
        "lock_version": draft.lock_version,
        "source_revision_id": draft.source_revision_id,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "content": draft.content,
        "asset_hashes": list(draft.asset_hashes or []),
    }


@bp.get("/experiment/<code>/report-draft")
@role_required("student")
def report_draft_get(code):
    context = _draft_context(code)
    if not context:
        return {"error": "报告草稿不存在"}, 404
    user, course, version, experiment, draft = context
    if not draft:
        with transaction() as tx:
            draft = get_or_create_draft(tx, tx.get(type(user), user.id), course.id, tx.get(ExperimentVersion, version.id), tx.get(Experiment, experiment.id))
    return jsonify(_draft_response(draft))


@bp.put("/experiment/<code>/report-draft")
@role_required("student")
def report_draft_save(code):
    context = _draft_context(code)
    if not context or not context[-1]:
        return {"error": "报告草稿不存在"}, 404
    draft = context[-1]
    payload = request.get_json(silent=True) or {}
    try:
        with transaction() as tx:
            saved = save_draft(tx, tx.get(ReportDraft, draft.id), payload.get("content"), int(payload.get("lock_version", 0)))
            response = _draft_response(saved)
        return jsonify(response)
    except RuntimeError as exc:
        if str(exc) == "report_draft_conflict":
            current = db_session().get(ReportDraft, draft.id)
            return {"error": "其他页面已修改这份草稿", "code": "conflict", "draft": _draft_response(current)}, 409
        raise
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}, 400


@bp.post("/experiment/<code>/report-draft/image")
@role_required("student")
def report_draft_image(code):
    context = _draft_context(code)
    if not context or not context[-1]:
        return {"error": "报告草稿不存在"}, 404
    draft = context[-1]
    if draft.status != "active":
        return {"error": "当前草稿已冻结"}, 409
    upload = request.files.get("image")
    if not upload or not upload.filename:
        return {"error": "请选择图片"}, 400
    try:
        asset_hash = save_upload(upload, IMAGE_UPLOADS)
        with transaction() as tx:
            current = tx.get(ReportDraft, draft.id)
            assets = list(dict.fromkeys([*(current.asset_hashes or []), asset_hash]))
            if len(assets) > 30:
                raise ValueError("每份报告最多插入 30 张图片")
            current.asset_hashes = assets
            current.lock_version += 1
            current.updated_at = datetime.now(timezone.utc)
            tx.flush()
            lock_version = current.lock_version
        return {"asset_hash": asset_hash, "url": url_for("auth.media", sha256=asset_hash), "lock_version": lock_version}
    except ValueError as exc:
        return {"error": str(exc)}, 400


@bp.post("/experiment/<code>/report-draft/translate")
@role_required("student")
def report_draft_translate(code):
    context = _draft_context(code)
    if not context or not context[-1]:
        return {"error": "报告草稿不存在"}, 404
    draft = context[-1]
    payload = request.get_json(silent=True) or {}
    try:
        expected = int(payload.get("lock_version", 0))
        if expected != draft.lock_version or draft.status != "active":
            return {"error": "草稿已变化，请保存后重试", "code": "conflict", "draft": _draft_response(draft)}, 409
        document = validate_document(payload.get("content"), draft.asset_hashes or [])
        translated = translate_report_frontmatter(document["title_zh"], document["abstract_zh"], document["keywords_zh"])
        document.update(translated)
        with transaction() as tx:
            saved = save_draft(tx, tx.get(ReportDraft, draft.id), document, expected)
            response = _draft_response(saved)
        return jsonify(response)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}, 400
    except RuntimeError as exc:
        return {"error": str(exc)}, 503


@bp.post("/experiment/<code>/report-draft/preview.pdf")
@role_required("student")
def report_draft_preview(code):
    context = _draft_context(code)
    if not context or not context[-1]:
        return {"error": "报告草稿不存在"}, 404
    user, _course, version, experiment, draft = context
    payload = request.get_json(silent=True) or {}
    try:
        document = validate_document(payload.get("content"), draft.asset_hashes or [])
        preview_revision = SimpleNamespace(payload={"report_document": document, "file_hashes": list(draft.asset_hashes or [])}, revision_no="预览", submitted_at=datetime.now(timezone.utc))
        stream = build_pdf(preview_revision, version, experiment, None, user, Path(current_app.static_folder) / "fonts" / "simhei.ttf")
        return send_file(stream, mimetype="application/pdf", as_attachment=False, download_name=f"{experiment.code}-preview.pdf")
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}, 400


@bp.post("/experiment/<code>/submit")
@role_required("student")
def submit_experiment(code):
    user = current_user()
    course = course_for_student(db_session(), user.id)
    if not course:
        return "学生尚未加入课程", 403
    version = _version(code, user.id, course.id)
    if not version:
        return "实验不存在", 404
    quiz = db_session().scalar(
        select(QuizAssignment).where(
            QuizAssignment.course_id == course.id,
            QuizAssignment.student_id == user.id,
            QuizAssignment.experiment_version_id == version.id,
        )
    )
    if not quiz or not quiz.completed_at or len(quiz.answers or {}) != 10:
        flash("请先完成并提交十道预习题。", "error")
        return redirect(url_for("student.experiment", code=code))
    try:
        draft_id = request.form.get("draft_id", "").strip()
        if draft_id:
            draft = db_session().get(ReportDraft, draft_id)
            if not draft or draft.student_id != user.id or draft.course_id != course.id or draft.experiment_version_id != version.id:
                raise ValueError("报告草稿不存在或无权访问")
            if draft.status != "active":
                raise ValueError("当前报告草稿已冻结")
            document = validate_submission_document(draft.content, draft.asset_hashes or [])
            payload = payload_from_document(document, file_hashes=draft.asset_hashes or [])
        else:
            fit_result = json.loads(request.form.get("fit_result", "{}") or "{}")
            payload = {k: request.form.get(k, "").strip() for k in ("abstract", "principle", "raw_data", "discussion", "conclusion")}
            file_hashes = [save_upload(item, STUDENT_ATTACHMENT_UPLOADS) for item in request.files.getlist("attachments") if item and item.filename]
            payload.update({"result_value": request.form.get("result_value"), "fit_result": fit_result, "steps_complete": request.form.get("steps_complete") == "yes", "file_hashes": file_hashes})
        if not payload["steps_complete"]:
            raise ValueError("必须确认已完成全部必做步骤")
        revision, _ = submit(
            user.id,
            version,
            request.form.get("request_id") or str(uuid.uuid4()),
            payload,
            course_id=course.id,
        )
        if draft_id:
            with transaction() as tx:
                locked = tx.get(ReportDraft, draft_id)
                if locked and locked.status == "active":
                    locked.status = "locked"
                    locked.updated_at = datetime.now(timezone.utc)
        flash("提交成功。报告修订已保存；学生端仅展示预习题成绩。", "success")
        return redirect(url_for("student.home", certificate=code))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("student.experiment", code=code))


@bp.post("/submission/<submission_id>/withdraw")
@role_required("student")
def withdraw_submission(submission_id):
    try:
        withdraw(current_user().id, submission_id)
        flash("提交已撤回；原始数据和原审核完整保留。", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("student.home"))


@bp.post("/submission/<submission_id>/copy-to-draft")
@role_required("student")
def copy_submission_to_draft(submission_id):
    user = current_user()
    revision = db_session().get(SubmissionRevision, submission_id)
    if not revision or revision.student_id != user.id:
        return "报告不存在", 404
    version = db_session().get(ExperimentVersion, revision.experiment_version_id)
    experiment = db_session().get(Experiment, version.experiment_id)
    with transaction() as tx:
        draft = copy_revision_to_draft(tx, tx.get(SubmissionRevision, revision.id), tx.get(ExperimentVersion, version.id), tx.get(Experiment, experiment.id), tx.get(type(user), user.id))
    if request.accept_mimetypes.best == "application/json":
        return jsonify(_draft_response(draft))
    flash(f"已从 R{revision.revision_no} 创建可编辑草稿。", "success")
    return redirect(url_for("student.experiment", code=experiment.code) + "#report")


@bp.get("/report/<submission_id>")
@role_required("student")
def report(submission_id):
    revision = db_session().get(SubmissionRevision, submission_id)
    if not revision or revision.student_id != current_user().id:
        return "报告不存在", 404
    version = db_session().get(ExperimentVersion, revision.experiment_version_id)
    exp = db_session().get(Experiment, version.experiment_id)
    user = current_user()
    return render_template("report.html", revision=revision, version=version, exp=exp, evaluation=None, user=user, report_user=user, report_doc=report_document(revision, version, exp, user), teacher_view=False, review=None)


@bp.get("/report/<submission_id>.<format>")
@role_required("student")
def export_report(submission_id, format):
    revision = db_session().get(SubmissionRevision, submission_id)
    if not revision or revision.student_id != current_user().id or format not in {"docx", "pdf"}: return "报告不存在", 404
    version = db_session().get(ExperimentVersion, revision.experiment_version_id); exp = db_session().get(Experiment, version.experiment_id)
    if format == "docx": stream, mime = build_docx(revision, version, exp, None, current_user()), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else: stream, mime = build_pdf(revision, version, exp, None, current_user(), __import__('pathlib').Path(current_app.static_folder) / "fonts" / "simhei.ttf"), "application/pdf"
    return send_file(stream, mimetype=mime, as_attachment=True, download_name=f"{exp.code}-R{revision.revision_no}.{format}")
