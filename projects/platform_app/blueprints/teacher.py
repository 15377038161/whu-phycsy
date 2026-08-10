from __future__ import annotations

from copy import deepcopy
import json
import uuid
from datetime import datetime, time, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy import func, select

from ..content import EXPERIMENTS, definition
from ..db import db_session, transaction
from ..models import AuditEvent, Course, CourseExperiment, Enrollment, Experiment, ExperimentDraft, ExperimentVersion, FileAsset, QuizAssignment, Review, SubmissionRevision, User
from auth_service import password_hash
from ..services.accounts import _validate_new_password, reset_student_password
from ..services.experiments import copy_experiment, ensure_course_experiments, publish_version
from ..services.files import IMAGE_UPLOADS, TEACHING_MATERIAL_UPLOADS, VIDEO_UPLOADS, save_upload
from ..services.course_materials import extract_teaching_material
from ..services.reporting import build_docx, build_pdf, report_document
from ..services.grade_export import build_grade_workbook
from ..services.student_roster import parse_student_roster
from ..teacher_analytics import build_teacher_analytics_workbook, get_teacher_analytics
from .auth import current_user, role_required
from ai_service import generate_experiment_draft, generate_question_bank

bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _owned_courses(session, teacher_id: str):
    return session.scalars(
        select(Course)
        .where(Course.teacher_id == teacher_id)
        .order_by(Course.created_at, Course.id)
    ).all()


def _owned_course_ids(session, teacher_id: str) -> list[str]:
    return [course.id for course in _owned_courses(session, teacher_id)]


def _latest_reviews(session, submission_ids: list[str]) -> dict[str, Review]:
    if not submission_ids:
        return {}
    rows = session.scalars(
        select(Review)
        .where(Review.submission_id.in_(submission_ids), Review.superseded.is_(False))
        .order_by(Review.created_at.desc())
    ).all()
    result = {}
    for row in rows:
        result.setdefault(row.submission_id, row)
    return result


def _teacher_can_access_revision(session, teacher_id: str, revision: SubmissionRevision) -> bool:
    return bool(
        revision.course_id
        and session.scalar(
            select(Course.id).where(
                Course.id == revision.course_id,
                Course.teacher_id == teacher_id,
            )
        )
    )


def _query_datetime(value: str | None, *, end: bool = False):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if len(value) == 10:
        parsed = datetime.combine(parsed.date(), time.max if end else time.min)
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


@bp.get("")
@role_required("teacher")
def dashboard():
    user = current_user()
    course_ids = _owned_course_ids(db_session(), user.id)
    submissions = db_session().execute(
        select(SubmissionRevision, User, Experiment)
        .join(User, User.id == SubmissionRevision.student_id)
        .join(ExperimentVersion, ExperimentVersion.id == SubmissionRevision.experiment_version_id)
        .join(Experiment, Experiment.id == ExperimentVersion.experiment_id)
        .where(SubmissionRevision.course_id.in_(course_ids))
        .order_by(SubmissionRevision.submitted_at.desc())
    ).all() if course_ids else []
    review_map = _latest_reviews(db_session(), [row.id for row, *_ in submissions])
    stats = {
        "total": len(submissions),
        "pending": sum(revision.status == "submitted" and revision.id not in review_map for revision, *_ in submissions),
        "withdrawn": sum(revision.status == "withdrawn" for revision, *_ in submissions),
        "passed": sum(bool(review_map.get(revision.id) and review_map[revision.id].decision == "approved") for revision, *_ in submissions),
        "returned": sum(bool(review_map.get(revision.id) and review_map[revision.id].decision == "returned") for revision, *_ in submissions),
    }
    return render_template("teacher_dashboard.html", user=user, submissions=submissions, stats=stats, review_map=review_map, courses=_owned_courses(db_session(), user.id))


@bp.get("/grades.xlsx")
@role_required("teacher")
def export_grades():
    course_id = request.args.get("course", "").strip()
    course = db_session().scalar(select(Course).where(Course.id == course_id, Course.teacher_id == current_user().id))
    if not course:
        return "班级不存在或无权导出", 404
    stream = build_grade_workbook(db_session(), course)
    return send_file(stream, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"grades-{course.id}.xlsx")


@bp.get("/analytics")
@role_required("teacher")
def analytics():
    try:
        data = get_teacher_analytics(
            db_session(),
            current_user().id,
            course_id=request.args.get("course") or None,
            experiment_id=request.args.get("experiment") or None,
            task_type=request.args.get("task_type") or None,
            status=request.args.get("status") or None,
            submitted_from=_query_datetime(request.args.get("submitted_from")),
            submitted_to=_query_datetime(request.args.get("submitted_to"), end=True),
        )
    except (PermissionError, ValueError) as exc:
        flash(str(exc), "error")
        data = get_teacher_analytics(db_session(), current_user().id)
    return render_template("teacher_analytics.html", user=current_user(), analytics=data)


@bp.get("/analytics.xlsx")
@role_required("teacher")
def export_analytics():
    try:
        data = get_teacher_analytics(
            db_session(),
            current_user().id,
            course_id=request.args.get("course") or None,
            experiment_id=request.args.get("experiment") or None,
            task_type=request.args.get("task_type") or None,
            status=request.args.get("status") or None,
            submitted_from=_query_datetime(request.args.get("submitted_from")),
            submitted_to=_query_datetime(request.args.get("submitted_to"), end=True),
        )
    except (PermissionError, ValueError) as exc:
        return str(exc), 400
    if not data.get("course"):
        return "当前教师暂无可导出的班级", 404
    stream = build_teacher_analytics_workbook(data)
    return send_file(
        stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"analytics-{data['course']['id']}.xlsx",
    )


@bp.get("/experiments")
@role_required("teacher")
def experiments():
    items = db_session().scalars(select(Experiment).order_by(Experiment.order_no)).all()
    versions = {exp.id: db_session().scalars(select(ExperimentVersion).where(ExperimentVersion.experiment_id == exp.id).order_by(ExperimentVersion.version_no.desc())).all() for exp in items}
    draft_id = request.args.get("draft", "")
    active_draft = db_session().get(ExperimentDraft, draft_id) if draft_id else None
    if active_draft and (active_draft.teacher_id != current_user().id or active_draft.status != "draft"):
        active_draft = None
    published_count = sum(version.status == "published" for rows in versions.values() for version in rows)
    return render_template("teacher_experiments.html", user=current_user(), items=items, versions=versions, active_count=sum(not exp.retired for exp in items), published_count=published_count, active_draft=active_draft, courses=_owned_courses(db_session(), current_user().id))


@bp.post("/experiments/<experiment_id>/move")
@role_required("teacher")
def move_experiment(experiment_id):
    direction = request.form.get("direction", "")
    if direction not in {"up", "down"}:
        return "排序方向无效", 400
    with transaction() as tx:
        items = tx.scalars(select(Experiment).order_by(Experiment.order_no, Experiment.id).with_for_update()).all()
        for index, item in enumerate(items, start=1):
            item.order_no = index
        current_index = next((index for index, item in enumerate(items) if item.id == experiment_id), None)
        if current_index is None:
            return "实验不存在", 404
        target_index = current_index + (-1 if direction == "up" else 1)
        if 0 <= target_index < len(items):
            current = items[current_index]; target = items[target_index]
            current.order_no, target.order_no = target.order_no, current.order_no
            owned_ids = _owned_course_ids(tx, current_user().id)
            course_rows = tx.scalars(
                select(CourseExperiment).where(CourseExperiment.course_id.in_(owned_ids))
            ).all() if owned_ids else []
            order_map = {item.id: item.order_no for item in items}
            for course_row in course_rows:
                if course_row.experiment_id in order_map:
                    course_row.position = order_map[course_row.experiment_id]
            tx.add(AuditEvent(actor_id=current_user().id, action="experiment.reorder", entity_type="experiment", entity_id=current.id, detail={"direction": direction, "from": current_index + 1, "to": target_index + 1}))
            flash(f"{current.title} 已{('上移' if direction == 'up' else '下移')}，学生端顺序同步更新。", "success")
        else:
            flash("已经位于目录边界，顺序未改变。", "success")
    return redirect(url_for("teacher.experiments"))


@bp.post("/experiments/<experiment_id>/copy")
@role_required("teacher")
def copy_existing_experiment(experiment_id):
    try:
        with transaction() as tx:
            source = tx.get(Experiment, experiment_id)
            if not source:
                raise ValueError("实验不存在")
            copied = copy_experiment(tx, source, current_user().id)
            copied_id = copied.id
        flash("实验已复制为独立草稿，请检查内容后发布。", "success")
        return redirect(url_for("teacher.edit_experiment", experiment_id=copied_id))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("teacher.experiments"))


@bp.route("/students", methods=["GET", "POST"])
@role_required("teacher")
def students():
    teacher = current_user()
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "class":
                name = request.form.get("course_name", "").strip()
                if not name:
                    raise ValueError("班级名称不能为空")
                with transaction() as tx:
                    course = Course(id=str(uuid.uuid4()), teacher_id=teacher.id, name=name[:160])
                    tx.add(course)
                    tx.flush()
                    ensure_course_experiments(tx, course)
                    tx.add(AuditEvent(actor_id=teacher.id, action="course.create", entity_type="course", entity_id=course.id, detail={"source": "manual"}))
                flash("班级已创建，并已关联当前实验目录。", "success")
            elif action == "students":
                course_id = request.form.get("course_id", "")
                upload = request.files.get("student_roster")
                if not upload or not upload.filename:
                    raise ValueError("请选择 Excel 学生名单")
                roster = parse_student_roster(upload, request.form.get("default_password", ""))
                with transaction() as tx:
                    course = tx.scalar(select(Course).where(Course.id == course_id, Course.teacher_id == teacher.id))
                    if not course:
                        raise ValueError("课程不存在或不属于当前教师")
                    enrolled = 0
                    created_accounts = 0
                    for row in roster.rows:
                        sid, name, password = row.student_id, row.name, row.password
                        existing = tx.get(User, sid)
                        if existing and existing.role != "student":
                            raise ValueError(f"第 {row.row_no} 行账号已被教师使用")
                        if not existing:
                            if not password:
                                raise ValueError(f"第 {row.row_no} 行是新账号但没有临时密码；请填写统一临时密码后重试")
                            _validate_new_password(password, password)
                            tx.add(User(id=sid, username=sid, name=name or sid, role="student", password_hash=password_hash(password), must_change_password=True))
                            created_accounts += 1
                        if not tx.scalar(select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == sid)):
                            tx.add(Enrollment(course_id=course_id, student_id=sid))
                            enrolled += 1
                    tx.add(AuditEvent(actor_id=teacher.id, action="students.import", entity_type="course", entity_id=course_id, detail={
                        "rows": len(roster.rows),
                        "created_accounts": created_accounts,
                        "enrolled": enrolled,
                        "sheet": roster.sheet_name,
                        "header_row": roster.header_row,
                        "student_id_column": roster.student_id_column,
                        "name_column": roster.name_column,
                        "password_column": roster.password_column,
                        "ignored_columns": roster.ignored_columns,
                    }))
                ignored = f"，忽略 {roster.ignored_columns} 个其他字段" if roster.ignored_columns else ""
                flash(
                    f"已从“{roster.sheet_name}”识别 {len(roster.rows)} 名学生："
                    f"学号列“{roster.student_id_column}”、姓名列“{roster.name_column}”{ignored}；"
                    f"新增 {created_accounts} 个账号、{enrolled} 条选课记录。",
                    "success",
                )
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("teacher.students"))
    courses = _owned_courses(db_session(), teacher.id)
    course_ids = [course.id for course in courses]
    rows = db_session().execute(
        select(Enrollment, User, Course)
        .join(User, User.id == Enrollment.student_id)
        .join(Course, Course.id == Enrollment.course_id)
        .where(Course.id.in_(course_ids))
        .order_by(Course.name, User.id)
    ).all() if course_ids else []
    course_counts = {course.id: sum(row_course.id == course.id for _, _, row_course in rows) for course in courses}
    requested_course = request.args.get("course") or None
    analytics = get_teacher_analytics(db_session(), teacher.id, course_id=requested_course)
    progress = {}
    for item in analytics["students"]:
        report_tasks = [task for task in item.get("tasks", []) if task.get("task_id", "").endswith(":report")]
        progress[item["id"]] = {
            **item,
            "completed": sum(task.get("status") == "completed" for task in report_tasks),
            "in_progress": sum(task.get("status") == "in_progress" for task in report_tasks),
            "not_started": sum(task.get("status") == "not_started" for task in report_tasks),
            "total": len(report_tasks),
        }
    selected_id = (analytics.get("course") or {}).get("id")
    selected_rows = [row for row in rows if row[2].id == selected_id]
    account_ready = sum(not student.must_change_password for _, student, _ in selected_rows)
    return render_template("teacher_students.html", user=teacher, courses=courses, rows=rows, course_counts=course_counts, progress=progress, analytics=analytics, selected_course=analytics.get("course"), experiment_total=analytics["summary"]["task_count"] // 2, account_ready=account_ready)


@bp.post("/experiments/ai-draft")
@role_required("teacher")
def create_ai_experiment_draft():
    instruction = request.form.get("experiment_prompt", "").strip()
    material_upload = request.files.get("experiment_material")
    if not instruction and not (material_upload and material_upload.filename):
        flash("请先描述实验，或上传一份实验材料。", "error")
        return redirect(url_for("teacher.experiments"))
    try:
        material_text = ""
        source_hash = None
        source_kind = request.form.get("input_mode", "text")[:30]
        if material_upload and material_upload.filename:
            material_text, source_kind = extract_teaching_material(material_upload)
            source_hash = save_upload(material_upload, TEACHING_MATERIAL_UPLOADS)
        generated = generate_experiment_draft(instruction, material_text)
        if db_session().scalar(select(Experiment).where(Experiment.code == generated["code"])):
            raise ValueError("AI 生成的实验代码已存在，请在提示中指定一个新代码。")
        with transaction() as tx:
            draft = ExperimentDraft(teacher_id=current_user().id, code=generated["code"], title=generated["title"], definition=generated["definition"], source_asset_hash=source_hash, source_kind=source_kind)
            tx.add(draft); tx.flush()
            tx.add(AuditEvent(actor_id=current_user().id, action="experiment.draft.generate", entity_type="experiment_draft", entity_id=draft.id, detail={"source_kind": source_kind, "material": bool(source_hash)}))
            draft_id = draft.id
        flash("AI 已生成实验草稿，请检查后再进入正式编辑器。", "success")
        return redirect(url_for("teacher.experiments", draft=draft_id))
    except (RuntimeError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("teacher.experiments"))


@bp.post("/experiments/ai-draft/<draft_id>/confirm")
@role_required("teacher")
def confirm_ai_experiment_draft(draft_id):
    draft = db_session().get(ExperimentDraft, draft_id)
    if not draft or draft.teacher_id != current_user().id or draft.status != "draft":
        return "实验草稿不存在", 404
    code = request.form.get("code", "").strip().upper()[:24]
    title = request.form.get("title", "").strip()[:160]
    summary = request.form.get("summary", "").strip()[:2000]
    principle = request.form.get("principle", "").strip()[:5000]
    apparatus = request.form.get("apparatus", "").strip()[:2000]
    steps = [line.strip()[:600] for line in request.form.get("steps", "").splitlines() if line.strip()][:12]
    if not code or not title or len(summary) < 20 or len(principle) < 20 or len(steps) < 5:
        flash("实验草稿至少需要代码、名称、完整简介、原理和 5 条详细操作步骤。", "error")
        return redirect(url_for("teacher.experiments", draft=draft_id))
    if db_session().scalar(select(Experiment).where(Experiment.code == code)):
        flash("实验代码已存在，请修改后再确认。", "error")
        return redirect(url_for("teacher.experiments", draft=draft_id))
    with transaction() as tx:
        target = tx.get(ExperimentDraft, draft_id)
        order_no = tx.scalar(select(func.count()).select_from(Experiment)) + 1
        experiment = Experiment(code=code, title=title, order_no=order_no)
        tx.add(experiment); tx.flush()
        definition_data = {**target.definition, "summary": summary, "principle": principle, "apparatus": apparatus, "steps": steps}
        tx.add(ExperimentVersion(experiment_id=experiment.id, version_no=1, status="draft", definition=definition_data))
        for course in _owned_courses(tx, current_user().id):
            position = tx.scalar(select(func.max(CourseExperiment.position)).where(CourseExperiment.course_id == course.id)) or 0
            tx.add(CourseExperiment(course_id=course.id, experiment_id=experiment.id, position=position + 1, active=True))
        target.experiment_id = experiment.id; target.status = "confirmed"; target.code = code; target.title = title; target.definition = definition_data
        tx.add(AuditEvent(actor_id=current_user().id, action="experiment.draft.confirm", entity_type="experiment", entity_id=experiment.id, detail={"draft_id": draft_id, "steps": len(steps)}))
    flash("AI 实验草稿已创建，请在编辑器中检查拟合、题库与发布信息。", "success")
    return redirect(url_for("teacher.edit_experiment", experiment_id=experiment.id))


@bp.post("/experiments/ai-draft/<draft_id>/delete")
@role_required("teacher")
def delete_ai_experiment_draft(draft_id):
    with transaction() as tx:
        draft = tx.get(ExperimentDraft, draft_id)
        if not draft or draft.teacher_id != current_user().id or draft.status != "draft":
            return "实验草稿不存在", 404
        tx.delete(draft)
        tx.add(AuditEvent(actor_id=current_user().id, action="experiment.ai_draft.delete", entity_type="experiment_draft", entity_id=draft_id, detail={}))
    flash("AI 实验草稿已删除。", "success")
    return redirect(url_for("teacher.experiments"))


@bp.post("/students/<student_id>/reset-password")
@role_required("teacher")
def reset_password(student_id):
    try:
        reset_student_password(current_user().id, student_id, request.form.get("new_password", ""), request.form.get("confirm_password", ""))
        flash("学生密码已重置，请通过安全渠道告知学生临时密码。", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("teacher.students"))


@bp.route("/experiments/new", methods=["GET", "POST"])
@role_required("teacher")
def new_experiment():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        title = request.form.get("title", "").strip()
        if not code or not title or db_session().scalar(select(Experiment).where(Experiment.code == code)):
            flash("实验代码和名称必填，代码不能重复。", "error")
        else:
            with transaction() as tx:
                order_no = tx.scalar(select(func.count()).select_from(Experiment)) + 1
                exp = Experiment(code=code, title=title, order_no=order_no)
                tx.add(exp); tx.flush()
                tx.add(ExperimentVersion(experiment_id=exp.id, version_no=1, status="draft", definition={"summary": "", "principle": "", "apparatus": "", "reference_value": 1.0, "reference_unit": "", "formula": "", "fit_template": "linear", "steps": [], "questions": [], "report_sections": []}))
                for course in _owned_courses(tx, current_user().id):
                    position = tx.scalar(select(func.max(CourseExperiment.position)).where(CourseExperiment.course_id == course.id)) or 0
                    tx.add(CourseExperiment(course_id=course.id, experiment_id=exp.id, position=position + 1, active=True))
            return redirect(url_for("teacher.experiments"))
    return render_template("experiment_edit.html", user=current_user(), exp=None, version=None)


@bp.route("/experiments/<experiment_id>/draft", methods=["GET", "POST"])
@role_required("teacher")
def edit_experiment(experiment_id):
    exp = db_session().get(Experiment, experiment_id)
    version = db_session().scalar(select(ExperimentVersion).where(ExperimentVersion.experiment_id == experiment_id, ExperimentVersion.status == "draft").order_by(ExperimentVersion.version_no.desc()))
    if not exp:
        return "实验不存在", 404
    if not version:
        source = db_session().scalar(select(ExperimentVersion).where(ExperimentVersion.experiment_id == experiment_id).order_by(ExperimentVersion.version_no.desc()))
        with transaction() as tx:
            version = ExperimentVersion(experiment_id=experiment_id, version_no=source.version_no + 1, status="draft", definition=deepcopy(source.definition))
            tx.add(version); tx.flush()
    if request.method == "POST":
        try:
            value = float(request.form.get("reference_value", ""))
            steps = [line.strip() for line in request.form.get("steps", "").splitlines() if line.strip()]
            questions = json.loads(request.form.get("questions_json", "[]"))
            if not isinstance(questions, list): raise ValueError("题库必须是 JSON 数组")
            video_hash = version.definition.get("demo_video_hash", "")
            cover_hash = version.definition.get("cover_image_hash", "")
            video = request.files.get("demo_video")
            if video and video.filename:
                video_hash = save_upload(video, VIDEO_UPLOADS)
            cover = request.files.get("cover_image")
            if cover and cover.filename:
                cover_hash = save_upload(cover, IMAGE_UPLOADS)
            with transaction() as tx:
                target = tx.get(ExperimentVersion, version.id)
                target.definition = {**target.definition, "summary": request.form.get("summary", "").strip(), "principle": request.form.get("principle", "").strip(), "apparatus": request.form.get("apparatus", "").strip(), "reference_value": value, "reference_unit": request.form.get("reference_unit", "").strip(), "formula": request.form.get("formula", "").strip(), "steps": steps, "questions": questions, "demo_video_hash": video_hash, "cover_image_hash": cover_hash}
                db_exp = tx.get(Experiment, experiment_id)
                db_exp.title = request.form.get("title", exp.title).strip()
                if request.form.get("intent") == "publish":
                    publish_version(tx, target, current_user().id)
            if request.form.get("intent") == "publish":
                flash("草稿已保存、发布并锁定，新版本现在可供学生使用。", "success")
                return redirect(url_for("teacher.experiments"))
            flash("草稿已保存。", "success")
            return redirect(url_for("teacher.edit_experiment", experiment_id=experiment_id))
        except (ValueError, json.JSONDecodeError) as exc:
            flash(f"草稿保存失败：{exc}", "error")
    demo_asset = db_session().get(FileAsset, version.definition.get("demo_video_hash")) if version.definition.get("demo_video_hash") else None
    cover_asset = db_session().get(FileAsset, version.definition.get("cover_image_hash")) if version.definition.get("cover_image_hash") else None
    concept_map: dict[str, dict] = {}
    for question in version.definition.get("questions", []):
        concept_id = str(question.get("concept_id") or question.get("id") or "未分组")
        item = concept_map.setdefault(concept_id, {"id": concept_id, "title": str(question.get("concept_title") or question.get("mother_question") or concept_id), "count": 0})
        item["count"] += 1
    return render_template("experiment_edit.html", user=current_user(), exp=exp, version=version, demo_asset=demo_asset, cover_asset=cover_asset, question_concepts=list(concept_map.values()))


@bp.post("/experiments/version/<version_id>/publish")
@role_required("teacher")
def publish(version_id):
    try:
        with transaction() as tx:
            version = tx.get(ExperimentVersion, version_id)
            if not version:
                raise ValueError("草稿不存在或已经删除")
            publish_version(tx, version, current_user().id)
        flash("实验版本已发布并锁定。", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("teacher.experiments"))


@bp.post("/experiments/version/<version_id>/generate-questions")
@role_required("teacher")
def generate_questions(version_id):
    version = db_session().get(ExperimentVersion, version_id)
    if not version or version.status != "draft": return "草稿不存在", 404
    exp = db_session().get(Experiment, version.experiment_id)
    corpus = "\n".join([version.definition.get("summary", ""), version.definition.get("principle", ""), version.definition.get("apparatus", ""), *version.definition.get("steps", [])])
    mode = request.form.get("mode", "replace")
    if mode not in {"append", "replace"}:
        return "不支持的题库生成方式", 400
    try:
        requested_count = int(request.form.get("count", "5" if mode == "append" else "40"))
    except ValueError:
        requested_count = 0
    if mode == "append" and not 1 <= requested_count <= 20:
        flash("AI 单次新增题目数量应为 1 到 20 道。", "error")
        return redirect(url_for("teacher.edit_experiment", experiment_id=version.experiment_id))
    try:
        generated = generate_question_bank(exp.title, corpus, 40)
    except RuntimeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("teacher.edit_experiment", experiment_id=version.experiment_id))
    if mode == "replace":
        questions = generated
    else:
        questions = deepcopy(version.definition.get("questions", []))
        existing_text = {str(item.get("question", "")).strip() for item in questions}
        existing_ids = {str(item.get("id", "")) for item in questions}
        additions = []
        for item in generated:
            if len(additions) >= requested_count:
                break
            if str(item.get("question", "")).strip() in existing_text:
                continue
            candidate = deepcopy(item)
            base_id = str(candidate.get("id") or "ai-question")
            suffix = len(questions) + len(additions) + 1
            candidate["id"] = f"{base_id}-added-{suffix}"
            while candidate["id"] in existing_ids:
                suffix += 1
                candidate["id"] = f"{base_id}-added-{suffix}"
            candidate["reviewed_by_teacher"] = False
            additions.append(candidate)
            existing_ids.add(candidate["id"])
            existing_text.add(str(candidate.get("question", "")).strip())
        if len(additions) < requested_count:
            flash("AI 生成结果与现有题目重复较多，本次未写入任何题目，请重试。", "error")
            return redirect(url_for("teacher.edit_experiment", experiment_id=version.experiment_id))
        questions.extend(additions)
    with transaction() as tx:
        target = tx.get(ExperimentVersion, version_id); target.definition = {**target.definition, "questions": questions}
        tx.add(AuditEvent(actor_id=current_user().id, action="questions.generate", entity_type="experiment_version", entity_id=version_id, detail={"mode": mode, "generated_count": 40 if mode == "replace" else requested_count, "total_count": len(questions)}))
    flash("已重新生成 40 道候选题，请逐题审核。" if mode == "replace" else f"已新增 {requested_count} 道候选题，请逐题审核。", "success")
    return redirect(url_for("teacher.edit_experiment", experiment_id=version.experiment_id))


@bp.post("/experiments/version/<version_id>/delete")
@role_required("teacher")
def delete_draft(version_id):
    try:
        with transaction() as tx:
            version = tx.get(ExperimentVersion, version_id)
            if not version or version.status != "draft": raise ValueError("草稿不存在或已发布，不能删除")
            tx.delete(version)
            tx.add(AuditEvent(actor_id=current_user().id, action="experiment.draft.delete", entity_type="experiment_version", entity_id=version_id, detail={}))
        flash("草稿已删除，已发布版本未受影响。", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("teacher.experiments"))


@bp.post("/experiments/version/<version_id>/retire")
@role_required("teacher")
def retire_version(version_id):
    try:
        with transaction() as tx:
            version = tx.get(ExperimentVersion, version_id)
            if not version or version.status != "published":
                raise ValueError("只有已发布版本可以下架")
            version.status = "retired"
            tx.add(AuditEvent(actor_id=current_user().id, action="experiment.version.retire", entity_type="experiment_version", entity_id=version_id, detail={"version": version.version_no}))
        flash("版本已从学生端下架；历史提交、审核和报告仍完整保留。", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("teacher.experiments"))


@bp.post("/experiments/<experiment_id>/retire")
@role_required("teacher")
def retire(experiment_id):
    with transaction() as tx:
        exp = tx.get(Experiment, experiment_id)
        if not exp:
            return "实验不存在", 404
        exp.retired = True
        tx.add(AuditEvent(actor_id=current_user().id, action="experiment.retire", entity_type="experiment", entity_id=experiment_id, detail={}))
    flash("实验已退役，历史版本与提交仍可审计。", "success")
    return redirect(url_for("teacher.experiments"))


@bp.post("/experiments/<experiment_id>/delete")
@role_required("teacher")
def delete_experiment(experiment_id):
    """Hard-delete draft-only experiments; safely retire anything ever published."""
    with transaction() as tx:
        exp = tx.get(Experiment, experiment_id)
        if not exp:
            return "实验不存在", 404
        versions = tx.scalars(select(ExperimentVersion).where(ExperimentVersion.experiment_id == experiment_id)).all()
        if any(version.status != "draft" for version in versions):
            exp.retired = True
            for version in versions:
                if version.status == "published":
                    version.status = "retired"
            tx.add(AuditEvent(actor_id=current_user().id, action="experiment.safe_delete", entity_type="experiment", entity_id=experiment_id, detail={"mode": "retire", "versions": len(versions)}))
            flash("该实验已有发布历史，已安全删除出学生端并归档；历史提交与报告完整保留。", "success")
        else:
            for link in tx.scalars(select(CourseExperiment).where(CourseExperiment.experiment_id == experiment_id)).all():
                tx.delete(link)
            for version in versions:
                tx.delete(version)
            tx.flush()
            tx.delete(exp)
            tx.add(AuditEvent(actor_id=current_user().id, action="experiment.delete", entity_type="experiment", entity_id=experiment_id, detail={"mode": "hard", "versions": len(versions)}))
            flash("未发布实验及其草稿版本已彻底删除。", "success")
    return redirect(url_for("teacher.experiments"))


@bp.route("/submission/<submission_id>", methods=["GET", "POST"])
@role_required("teacher")
def review(submission_id):
    revision = db_session().get(SubmissionRevision, submission_id)
    if not revision or not _teacher_can_access_revision(db_session(), current_user().id, revision):
        return "提交不存在", 404
    if request.method == "POST":
        score = max(0, min(100, int(request.form.get("private_score", 0))))
        decision = request.form.get("decision", "approved")
        if decision not in {"approved", "returned", "draft"}:
            return "审核决定无效", 400
        with transaction() as tx:
            previous_reviews = tx.scalars(select(Review).where(Review.submission_id == submission_id, Review.superseded.is_(False))).all()
            for previous in previous_reviews:
                previous.superseded = True
            tx.add(Review(submission_id=submission_id, teacher_id=current_user().id, private_score=score, private_comment=request.form.get("private_comment", "").strip(), decision=decision))
            tx.add(AuditEvent(actor_id=current_user().id, action="review.create", entity_type="submission", entity_id=submission_id, detail={"private_score": score, "decision": decision}))
        flash("教师人工成绩与审核已保存；该成绩将进入班级 Excel，学生响应不包含内部评分。", "success")
        return redirect(url_for("teacher.review", submission_id=submission_id))
    version = db_session().get(ExperimentVersion, revision.experiment_version_id)
    exp = db_session().get(Experiment, version.experiment_id)
    student = db_session().get(User, revision.student_id)
    review = db_session().scalar(select(Review).where(Review.submission_id == submission_id).order_by(Review.created_at.desc()))
    return render_template("report.html", revision=revision, version=version, exp=exp, evaluation=None, user=current_user(), report_user=student, report_doc=report_document(revision, version, exp, student), teacher_view=True, review=review)


@bp.get("/submission/<submission_id>.<format>")
@role_required("teacher")
def export_internal_report(submission_id, format):
    revision = db_session().get(SubmissionRevision, submission_id)
    if not revision or not _teacher_can_access_revision(db_session(), current_user().id, revision) or format not in {"docx", "pdf"}: return "报告不存在", 404
    version = db_session().get(ExperimentVersion, revision.experiment_version_id); exp = db_session().get(Experiment, version.experiment_id); student = db_session().get(User, revision.student_id); latest_review = db_session().scalar(select(Review).where(Review.submission_id == submission_id).order_by(Review.created_at.desc()))
    if format == "docx": stream, mime = build_docx(revision, version, exp, None, student, latest_review, True), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else: stream, mime = build_pdf(revision, version, exp, None, student, __import__('pathlib').Path(current_app.static_folder) / "fonts" / "simhei.ttf", latest_review, True), "application/pdf"
    return send_file(stream, mimetype=mime, as_attachment=True, download_name=f"internal-{exp.code}-{student.id}-R{revision.revision_no}.{format}")
