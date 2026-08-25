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
from ..models import Course, CourseExperiment, Experiment, ExperimentVersion, FileAsset, QuizAssignment, ReportDraft, SubmissionRevision, StudentExperimentProgress
from ..services.experiments import course_for_student, ensure_course_experiments, frozen_quiz, published_experiments, restart_quiz
from ..services.submissions import submit, withdraw
from ..services.reporting import build_docx, build_pdf, report_document
from ..services.files import IMAGE_UPLOADS, STUDENT_ATTACHMENT_UPLOADS, save_upload
from ..services.report_drafts import copy_revision_to_draft, get_or_create_draft, payload_from_document, save_draft, validate_document, validate_submission_document
from ..services.progress import clean_step_data, get_progress, normalize_steps, selection_summary, update_report_from_step, validate_step
from ..services.fitting import validate_fit_result
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


def _catalog_versions(course: Course | None):
    return [version for _, version in published_experiments(db_session(), course.id if course else None)]


@bp.get("/level-selection")
@role_required("student")
def level_selection():
    user = current_user()
    course = course_for_student(db_session(), user.id)
    versions = _catalog_versions(course)
    summary = selection_summary(db_session(), course, user.id, versions) if course else {"required": 0, "selected": [], "count": 0, "ready": False, "by_version": {}}
    return jsonify({"required": summary["required"], "count": summary["count"], "ready": summary["ready"], "selected_version_ids": summary["selected"]})


@bp.post("/level-selection")
@role_required("student")
def save_level_selection():
    user = current_user()
    course = course_for_student(db_session(), user.id)
    if not course:
        return {"error": "学生尚未加入课程"}, 403
    versions = _catalog_versions(course)
    valid_ids = {version.id for version in versions}
    selected_ids = list(dict.fromkeys(item for item in request.form.getlist("selected_versions") if item in valid_ids))
    summary = selection_summary(db_session(), course, user.id, versions)
    completed_ids = {version_id for version_id, progress in summary["by_version"].items() if progress.completed_at}
    selected_ids = list(dict.fromkeys([*selected_ids, *completed_ids]))
    if len(selected_ids) < summary["required"]:
        flash(f"请至少选择 {summary['required']} 个实验关卡。", "error")
        return redirect(url_for("student.home"))
    with transaction() as tx:
        for version in versions:
            progress = get_progress(tx, course.id, user.id, version.id)
            progress.selected = version.id in selected_ids or progress.completed_at is not None
    flash(f"已保存选关：{len(selected_ids)} / {len(versions)} 关，可按任意顺序挑战。", "success")
    return redirect(url_for("student.home"))


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
    versions = [version for _, version, _ in items]
    selection = selection_summary(db_session(), course, user.id, versions) if course else {"required": 0, "selected": [], "count": 0, "ready": False, "by_version": {}}
    cover_assets = {}
    for _, version, _ in items:
        cover_hash = version.definition.get("cover_image_hash")
        if cover_hash:
            cover_assets[version.id] = db_session().get(FileAsset, cover_hash)
    selected_items = [item for item in items if selection["by_version"].get(item[1].id) and selection["by_version"][item[1].id].selected]
    featured, featured_kicker, featured_action = _current_experiment(selected_items, activity_at)
    completed_experiment_count = sum(1 for revision in latest_by_experiment.values() if revision.status == "submitted")
    achievement_context = _achievement_context(items, user.id)
    certificate_code = (request.args.get("certificate") or "").strip().upper()
    certificate_item = next(
        (item for item in achievement_context["achievement_items"] if item["code"] == certificate_code and item["unlocked"]),
        None,
    )
    return render_template(
        "student_home.html", user=user, course=course, items=items,
        quiz_score_map=quiz_score_map, completed_experiment_count=completed_experiment_count,
        submission_count=len(submission_rows), cover_assets=cover_assets, featured=featured,
        featured_kicker=featured_kicker, featured_action=featured_action,
        certificate_item=certificate_item, selection=selection, **achievement_context,
    )


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
    progress = db_session().scalar(select(StudentExperimentProgress).where(
        StudentExperimentProgress.course_id == course.id,
        StudentExperimentProgress.student_id == user.id,
        StudentExperimentProgress.experiment_version_id == version.id,
    ))
    selection = selection_summary(db_session(), course, user.id, _catalog_versions(course))
    if not progress or not progress.selected:
        if not selection["ready"]:
            flash(f"请先在首页至少选择 {selection['required']} 个实验关卡。", "error")
            return redirect(url_for("student.home"))
        with transaction() as tx:
            progress = get_progress(tx, course.id, user.id, version.id)
            progress.selected = True
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
        flash(f"第 {quiz.attempt_no or 1} 次预习已提交，答对 {correct}/10 题；可查看解析或直接进入操作。", "success")
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
    steps = normalize_steps(version.definition)
    steps_by_id = {step["id"]: step for step in steps}
    progress_data = dict(progress.step_data or {})
    for step in steps:
        if step.get("kind") != "fit":
            continue
        config = step.get("fit_config") or {}
        source_step = steps_by_id.get(config.get("source_step_id"))
        source_item = progress_data.get(str(source_step["index"]), {}) if source_step else progress_data.get(str(step["index"]), {})
        source_field = config.get("source_field_key")
        source_rows = (source_item.get("data") or {}).get(source_field, [])
        source_definition = next((field for field in (source_step or step).get("fields", []) if field.get("key") == source_field), None)
        step["fit_rows"] = source_rows if isinstance(source_rows, list) else []
        step["fit_columns"] = list((source_definition or {}).get("columns") or [])
    completed_steps = set(int(item) for item in (progress.completed_steps or []) if str(item).isdigit())
    current_step = next((step["index"] for step in steps if step.get("required", True) and step["index"] not in completed_steps), max(0, len(steps) - 1))
    materials = []
    for raw in version.definition.get("materials", []):
        material = dict(raw) if isinstance(raw, dict) else {}
        asset = db_session().get(FileAsset, material.get("asset_hash")) if material.get("asset_hash") else None
        preview = db_session().get(FileAsset, material.get("preview_asset_hash")) if material.get("preview_asset_hash") else None
        material["media_type"] = material.get("media_type") or (Path(asset.original_name).suffix.lstrip(".").lower() if asset else "pdf" if material.get("static_path") else "file")
        material["asset"] = asset; material["preview_asset"] = preview
        materials.append(material)
    return render_template("experiment.html", user=user, exp=exp, version=version, quiz=quiz, quiz_score=quiz_score, latest=latest, evaluation=None, demo_asset=demo_asset, report_draft=draft, progress=progress, step_specs=steps, current_step=current_step, materials=materials, pyodide_base_url=current_app.config["PYODIDE_BASE_URL"])


def _step_context(code: str, step_no: int):
    user = current_user()
    course = course_for_student(db_session(), user.id)
    version = _version(code, user.id, course.id if course else None) if course else None
    if not course or not version:
        return None
    steps = normalize_steps(version.definition)
    if step_no < 0 or step_no >= len(steps):
        return None
    progress = db_session().scalar(select(StudentExperimentProgress).where(
        StudentExperimentProgress.course_id == course.id,
        StudentExperimentProgress.student_id == user.id,
        StudentExperimentProgress.experiment_version_id == version.id,
    ))
    if not progress or not progress.selected:
        return None
    draft = db_session().scalar(select(ReportDraft).where(
        ReportDraft.course_id == course.id,
        ReportDraft.student_id == user.id,
        ReportDraft.experiment_version_id == version.id,
    ))
    return user, course, version, steps[step_no], progress, draft


@bp.get("/experiment/<code>/progress")
@role_required("student")
def experiment_progress(code):
    user = current_user()
    course = course_for_student(db_session(), user.id)
    version = _version(code, user.id, course.id if course else None) if course else None
    if not course or not version:
        return {"error": "实验不存在"}, 404
    progress = db_session().scalar(select(StudentExperimentProgress).where(
        StudentExperimentProgress.course_id == course.id,
        StudentExperimentProgress.student_id == user.id,
        StudentExperimentProgress.experiment_version_id == version.id,
    ))
    steps = normalize_steps(version.definition)
    completed_steps = list(progress.completed_steps or []) if progress else []
    current_step = next((step["index"] for step in steps if step.get("required", True) and step["index"] not in completed_steps), len(steps) - 1 if steps else 0)
    return jsonify({
        "selected": bool(progress and progress.selected),
        "completed_steps": completed_steps,
        "step_data": dict(progress.step_data or {}) if progress else {},
        "level_completed": bool(progress and progress.completed_at),
        "current_step": current_step,
        "step_count": len(steps),
    })


@bp.put("/experiment/<code>/steps/<int:step_no>")
@role_required("student")
def save_experiment_step(code, step_no):
    context = _step_context(code, step_no)
    if not context:
        return {"error": "步骤不存在或尚未选关"}, 404
    user, course, version, step, _, draft_state = context
    if draft_state and draft_state.status != "active":
        return {"error": "正式报告已冻结；如需修改实验数据，请先复制历史报告为新草稿"}, 409
    payload = request.get_json(silent=True) or {}
    clean_data = clean_step_data(step, payload.get("data"))
    completed = bool(payload.get("completed"))
    with transaction() as tx:
        progress = get_progress(tx, course.id, user.id, version.id)
        current = dict(progress.step_data or {})
        previous_item = dict(current.get(str(step_no)) or {})
        item = {**previous_item, "data": clean_data, "image_hashes": list(previous_item.get("image_hashes") or [])}
        completed_steps = set(int(value) for value in (progress.completed_steps or []) if str(value).isdigit())
        steps = normalize_steps(version.definition)
        first_incomplete = next((candidate["index"] for candidate in steps if candidate.get("required", True) and candidate["index"] not in completed_steps), len(steps))
        if step_no > first_incomplete and step_no not in completed_steps:
            return jsonify({"error": "请先完成当前小关卡", "current_step": first_incomplete}), 409
        errors = validate_step(step, clean_data, item["image_hashes"], item.get("fit_result")) if completed else []
        if errors:
            return jsonify({"error": errors[0]["message"], "validation_errors": errors, "current_step": first_incomplete}), 422
        current[str(step_no)] = item
        if completed:
            completed_steps.add(step_no)
        else:
            completed_steps.discard(step_no)
        if previous_item.get("data") != clean_data:
            for fit_step in steps:
                if fit_step.get("kind") != "fit" or fit_step.get("fit_config", {}).get("source_step_id") != step.get("id"):
                    continue
                fit_item = dict(current.get(str(fit_step["index"])) or {})
                if fit_item.get("fit_result"):
                    fit_item.pop("fit_result", None); fit_item.pop("fallback_chart_hash", None)
                    current[str(fit_step["index"])] = fit_item; completed_steps.discard(fit_step["index"])
        progress.step_data = current
        progress.completed_steps = sorted(completed_steps)
        required_steps = [candidate["index"] for candidate in steps if candidate.get("required", True)]
        level_completed = bool(required_steps) and all(item in completed_steps for item in required_steps)
        if level_completed:
            progress.completed_at = progress.completed_at or datetime.now(timezone.utc)
        else:
            progress.completed_at = None
        draft = tx.scalar(select(ReportDraft).where(ReportDraft.course_id == course.id, ReportDraft.student_id == user.id, ReportDraft.experiment_version_id == version.id))
        report_synced = True
        if draft and draft.status == "active":
            report_synced = update_report_from_step(draft, step, step_no, clean_data, item["image_hashes"], item.get("fit_result"), item.get("fallback_chart_hash", ""), bool(payload.get("force_sync")))
        next_step = next((candidate["index"] for candidate in steps if candidate.get("required", True) and candidate["index"] not in completed_steps), len(steps) - 1 if steps else 0)
        response = {"completed_steps": progress.completed_steps, "level_completed": level_completed, "step_data": progress.step_data, "current_step": next_step, "report_sync_conflict": not report_synced}
    return jsonify(response)


@bp.post("/experiment/<code>/steps/<int:step_no>/image")
@role_required("student")
def upload_experiment_step_image(code, step_no):
    context = _step_context(code, step_no)
    if not context:
        return {"error": "步骤不存在或尚未选关"}, 404
    user, course, version, step, _, draft_state = context
    if draft_state and draft_state.status != "active":
        return {"error": "正式报告已冻结；如需补充图片，请先复制历史报告为新草稿"}, 409
    if not any(field.get("type") == "image" for field in step.get("fields", [])):
        return {"error": "当前步骤未配置图片上传"}, 400
    upload = request.files.get("image")
    if not upload or not upload.filename:
        return {"error": "请选择图片"}, 400
    try:
        asset_hash = save_upload(upload, IMAGE_UPLOADS)
        with transaction() as tx:
            progress = get_progress(tx, course.id, user.id, version.id)
            current = dict(progress.step_data or {})
            item = dict(current.get(str(step_no)) or {"data": {}, "image_hashes": []})
            item["image_hashes"] = list(dict.fromkeys([*(item.get("image_hashes") or []), asset_hash]))
            current[str(step_no)] = item
            progress.step_data = current
            assets = list(dict.fromkeys([*(progress.asset_hashes or []), asset_hash]))
            progress.asset_hashes = assets
            draft = tx.scalar(select(ReportDraft).where(ReportDraft.course_id == course.id, ReportDraft.student_id == user.id, ReportDraft.experiment_version_id == version.id))
            if draft and draft.status == "active":
                draft.asset_hashes = list(dict.fromkeys([*(draft.asset_hashes or []), asset_hash]))
                update_report_from_step(draft, step, step_no, item.get("data") or {}, item["image_hashes"], item.get("fit_result"), item.get("fallback_chart_hash", ""))
        return jsonify({"asset_hash": asset_hash, "url": url_for("auth.media", sha256=asset_hash)})
    except ValueError as exc:
        return {"error": str(exc)}, 400


@bp.post("/experiment/<code>/steps/<int:step_no>/fit-result")
@role_required("student")
def save_experiment_fit_result(code, step_no):
    context = _step_context(code, step_no)
    if not context:
        return {"error": "步骤不存在或尚未选关"}, 404
    user, course, version, step, _, draft_state = context
    if draft_state and draft_state.status != "active":
        return {"error": "正式报告已冻结；如需重新拟合，请先复制历史报告为新草稿"}, 409
    if step.get("kind") != "fit":
        return {"error": "当前步骤不是拟合关卡"}, 400
    try:
        fit_result = validate_fit_result((request.get_json(silent=True) or {}).get("result") or {})
        fit_result["source"] = "browser"
        with transaction() as tx:
            progress = get_progress(tx, course.id, user.id, version.id)
            current = dict(progress.step_data or {}); item = dict(current.get(str(step_no)) or {"data": {}, "image_hashes": []})
            item["fit_result"] = fit_result; item.pop("fallback_chart_hash", None); current[str(step_no)] = item; progress.step_data = current
            draft = tx.scalar(select(ReportDraft).where(ReportDraft.course_id == course.id, ReportDraft.student_id == user.id, ReportDraft.experiment_version_id == version.id))
            if draft and draft.status == "active": update_report_from_step(draft, step, step_no, item.get("data") or {}, item.get("image_hashes") or [], fit_result)
        return jsonify({"result": fit_result})
    except ValueError as exc:
        return {"error": str(exc)}, 400


@bp.post("/experiment/<code>/steps/<int:step_no>/fit-fallback")
@role_required("student")
def save_experiment_fit_fallback(code, step_no):
    context = _step_context(code, step_no)
    if not context:
        return {"error": "步骤不存在或尚未选关"}, 404
    user, course, version, step, _, draft_state = context
    if draft_state and draft_state.status != "active":
        return {"error": "正式报告已冻结；如需重新拟合，请先复制历史报告为新草稿"}, 409
    if step.get("kind") != "fit" or not step.get("fit_config", {}).get("allow_excel_fallback"):
        return {"error": "当前步骤未开放 Excel 兜底"}, 400
    chart = request.files.get("chart")
    if not chart or not chart.filename:
        return {"error": "请上传 Excel 生成的拟合结果图"}, 400
    try:
        parameters = json.loads(request.form.get("parameters") or "{}")
        fit_result = validate_fit_result({"code": "", "formula": step.get("fit_config", {}).get("formula", ""), "initial_parameters": {}, "final_parameters": parameters, "metrics": {}})
        fit_result["source"] = "excel_fallback"
        chart_hash = save_upload(chart, IMAGE_UPLOADS)
        with transaction() as tx:
            progress = get_progress(tx, course.id, user.id, version.id)
            current = dict(progress.step_data or {}); item = dict(current.get(str(step_no)) or {"data": {}, "image_hashes": []})
            item["fit_result"] = fit_result; item["fallback_chart_hash"] = chart_hash; current[str(step_no)] = item; progress.step_data = current
            progress.asset_hashes = list(dict.fromkeys([*(progress.asset_hashes or []), chart_hash]))
            draft = tx.scalar(select(ReportDraft).where(ReportDraft.course_id == course.id, ReportDraft.student_id == user.id, ReportDraft.experiment_version_id == version.id))
            if draft and draft.status == "active":
                draft.asset_hashes = list(dict.fromkeys([*(draft.asset_hashes or []), chart_hash]))
                update_report_from_step(draft, step, step_no, item.get("data") or {}, item.get("image_hashes") or [], fit_result, chart_hash)
        return jsonify({"result": fit_result, "chart_hash": chart_hash, "chart_url": url_for("auth.media", sha256=chart_hash)})
    except (ValueError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}, 400


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
    progress = db_session().scalar(select(StudentExperimentProgress).where(
        StudentExperimentProgress.course_id == course.id,
        StudentExperimentProgress.student_id == user.id,
        StudentExperimentProgress.experiment_version_id == version.id,
    ))
    required_steps = [item["index"] for item in normalize_steps(version.definition) if item.get("required", True)]
    if not progress or not required_steps or not all(item in set(progress.completed_steps or []) for item in required_steps):
        flash("请先完成实验操作中的全部必做小关卡。", "error")
        return redirect(url_for("student.experiment", code=code) + "#operation")
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
        payload["steps_complete"] = True
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
        flash("本关实验已完成，正式报告修订已保存。", "success")
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
