from __future__ import annotations

import hashlib
import os
import random
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import func, select
from flask import current_app

from ..content import EXPERIMENTS, definition
from ..db import transaction
from ..models import AuditEvent, Course, CourseExperiment, Enrollment, Experiment, ExperimentVersion, QuizAssignment, User


def published_experiments(session, course_id: str | None = None):
    versions = session.scalars(select(ExperimentVersion).where(ExperimentVersion.status == "published")).all()
    newest = {}
    for version in versions:
        current = newest.get(version.experiment_id)
        if current is None or version.version_no > current.version_no:
            newest[version.experiment_id] = version
    if course_id:
        experiments = session.scalars(
            select(Experiment)
            .join(CourseExperiment, CourseExperiment.experiment_id == Experiment.id)
            .where(
                CourseExperiment.course_id == course_id,
                CourseExperiment.active.is_(True),
                Experiment.retired.is_(False),
            )
            .order_by(CourseExperiment.position, Experiment.order_no, Experiment.id)
        ).all()
    else:
        experiments = session.scalars(
            select(Experiment)
            .where(Experiment.retired.is_(False))
            .order_by(Experiment.order_no, Experiment.id)
        ).all()
    return [(exp, newest[exp.id]) for exp in experiments if exp.id in newest]


def course_for_student(session, student_id: str):
    enrollment = session.scalar(
        select(Enrollment)
        .join(Course, Course.id == Enrollment.course_id)
        .where(Enrollment.student_id == student_id)
        .order_by(Course.created_at, Course.id)
    )
    return session.get(Course, enrollment.course_id) if enrollment else None


def ensure_course_experiments(session, course: Course) -> None:
    existing = set(
        session.scalars(
            select(CourseExperiment.experiment_id).where(
                CourseExperiment.course_id == course.id
            )
        ).all()
    )
    experiments = session.scalars(
        select(Experiment)
        .where(Experiment.retired.is_(False))
        .order_by(Experiment.order_no, Experiment.id)
    ).all()
    next_position = (
        session.scalar(
            select(func.max(CourseExperiment.position)).where(
                CourseExperiment.course_id == course.id
            )
        )
        or 0
    )
    for experiment in experiments:
        if experiment.id in existing:
            continue
        next_position += 1
        session.add(
            CourseExperiment(
                course_id=course.id,
                experiment_id=experiment.id,
                position=next_position,
                active=True,
            )
        )


def _quiz_candidate(
    session,
    *,
    student_id: str,
    course_id: str,
    version: ExperimentVersion,
    attempt_no: int,
    excluded_ids: set[str],
    assignment_id: str | None = None,
) -> tuple[list[dict], str]:
    groups: dict[str, list[dict]] = {}
    for question in version.definition.get("questions", []):
        question_id = str(question.get("id", ""))
        if not question_id or question_id in excluded_ids:
            continue
        groups.setdefault(str(question.get("concept_id") or question_id), []).append(question)
    if len(groups) < 10:
        raise ValueError("没有足够的新题用于重做，请联系教师扩充母题变式")
    used_signatures: set[str] = set()
    assignments = session.scalars(
        select(QuizAssignment).where(
            QuizAssignment.course_id == course_id,
            QuizAssignment.experiment_version_id == version.id,
        )
    ).all()
    for existing in assignments:
        if existing.id != assignment_id and existing.signature:
            used_signatures.add(existing.signature)
        for attempt in existing.history or []:
            ids = sorted(str(question.get("id")) for question in (attempt.get("questions") or []) if question.get("id"))
            if ids:
                used_signatures.add(hashlib.sha256("|".join(ids).encode()).hexdigest())
    for salt in range(10000):
        seed = hashlib.sha256(f"{student_id}:{course_id}:{version.id}:{attempt_no}:{salt}".encode()).hexdigest()
        rng = random.Random(seed)
        concepts = rng.sample(sorted(groups), 10)
        questions = [deepcopy(rng.choice(groups[concept])) for concept in concepts]
        for question in questions:
            options = list(question.get("options") or [])
            rng.shuffle(options)
            question["options"] = options
        rng.shuffle(questions)
        signature = hashlib.sha256("|".join(sorted(str(q["id"]) for q in questions)).encode()).hexdigest()
        if signature not in used_signatures:
            return questions, signature
    raise ValueError("可用题目组合已经耗尽，请联系教师扩充母题变式")


def frozen_quiz(session, student_id: str, course_id: str, version: ExperimentVersion) -> QuizAssignment:
    existing = session.scalar(
        select(QuizAssignment).where(
            QuizAssignment.course_id == course_id,
            QuizAssignment.student_id == student_id,
            QuizAssignment.experiment_version_id == version.id,
        )
    )
    if existing:
        return existing
    bank = version.definition.get("questions", [])
    if len(bank) < 40:
        raise ValueError("题库不足 40 题，教师需要先扩充母题变式")
    groups = {str(question.get("concept_id") or question.get("id")) for question in bank}
    if len(groups) < 10:
        raise ValueError("题库独立知识点不足 10 个，教师需要补充母题方向")
    questions, signature = _quiz_candidate(
        session,
        student_id=student_id,
        course_id=course_id,
        version=version,
        attempt_no=1,
        excluded_ids=set(),
    )
    assignment = QuizAssignment(
        course_id=course_id,
        student_id=student_id,
        experiment_version_id=version.id,
        questions=questions,
        answers={},
        attempt_no=1,
        history=[],
        signature=signature,
    )
    session.add(assignment)
    session.flush()
    return assignment


def restart_quiz(session, assignment: QuizAssignment, version: ExperimentVersion, actor_id: str) -> QuizAssignment:
    if not assignment.completed_at or len(assignment.answers or {}) != len(assignment.questions or []):
        raise ValueError("当前预习题尚未完成，不能重新抽题")
    history = list(assignment.history or [])
    history.append(
        {
            "attempt_no": assignment.attempt_no or 1,
            "questions": deepcopy(assignment.questions or []),
            "answers": deepcopy(assignment.answers or {}),
            "completed_at": assignment.completed_at.isoformat(),
        }
    )
    excluded_ids = {
        str(question.get("id"))
        for attempt in history
        for question in (attempt.get("questions") or [])
        if question.get("id")
    }
    attempt_no = (assignment.attempt_no or 1) + 1
    questions, signature = _quiz_candidate(
        session,
        student_id=assignment.student_id,
        course_id=assignment.course_id,
        version=version,
        attempt_no=attempt_no,
        excluded_ids=excluded_ids,
        assignment_id=assignment.id,
    )
    assignment.history = history
    assignment.attempt_no = attempt_no
    assignment.questions = questions
    assignment.answers = {}
    assignment.signature = signature
    assignment.frozen_at = datetime.now(timezone.utc)
    assignment.completed_at = None
    session.add(
        AuditEvent(
            actor_id=actor_id,
            action="quiz.restart",
            entity_type="quiz_assignment",
            entity_id=assignment.id,
            detail={"attempt_no": attempt_no, "excluded_question_count": len(excluded_ids)},
        )
    )
    session.flush()
    return assignment


def publish_version(session, version: ExperimentVersion, actor_id: str):
    from .progress import normalize_steps, validate_step_contract
    if version.status != "draft":
        raise ValueError("只能发布草稿版本")
    if len(version.definition.get("questions", [])) < 40:
        raise ValueError("发布前题库必须不少于 40 题")
    concept_counts: dict[str, int] = {}
    for question in version.definition.get("questions", []):
        concept_id = str(question.get("concept_id") or "").strip()
        if not concept_id:
            raise ValueError("每道候选题必须标注母题方向 concept_id")
        concept_counts[concept_id] = concept_counts.get(concept_id, 0) + 1
    if len(concept_counts) < 10 or sum(size >= 2 for size in concept_counts.values()) < 10:
        raise ValueError("发布前至少需要 10 个母题方向，并且每个方向至少有 2 道不同考法")
    if not version.definition.get("steps") or version.definition.get("reference_value") is None:
        raise ValueError("发布前必须配置步骤和参考结果")
    validate_step_contract(normalize_steps(version.definition))
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    experiment = session.get(Experiment, version.experiment_id)
    if experiment:
        experiment.retired = False
    session.add(AuditEvent(actor_id=actor_id, action="experiment.publish", entity_type="experiment_version", entity_id=version.id, detail={"version": version.version_no}))


def copy_experiment(session, source: Experiment, actor_id: str) -> Experiment:
    """Create an independent draft experiment from the latest source definition."""
    latest = session.scalar(
        select(ExperimentVersion)
        .where(ExperimentVersion.experiment_id == source.id)
        .order_by(ExperimentVersion.version_no.desc())
    )
    if not latest:
        raise ValueError("源实验没有可复制的内容")
    suffix = 1
    while True:
        marker = "_COPY" if suffix == 1 else f"_COPY{suffix}"
        code = f"{source.code[:24-len(marker)]}{marker}"
        if not session.scalar(select(Experiment).where(Experiment.code == code)):
            break
        suffix += 1
    title_suffix = "（副本）" if suffix == 1 else f"（副本 {suffix}）"
    order_no = (session.scalar(select(func.max(Experiment.order_no))) or 0) + 1
    copied = Experiment(code=code, title=f"{source.title}{title_suffix}"[:160], order_no=order_no)
    session.add(copied)
    session.flush()
    session.add(ExperimentVersion(experiment_id=copied.id, version_no=1, status="draft", definition=deepcopy(latest.definition)))
    for course in session.scalars(select(Course).where(Course.teacher_id == actor_id).order_by(Course.created_at, Course.id)).all():
        position = session.scalar(select(func.max(CourseExperiment.position)).where(CourseExperiment.course_id == course.id)) or 0
        session.add(CourseExperiment(course_id=course.id, experiment_id=copied.id, position=position + 1, active=True))
    session.add(AuditEvent(actor_id=actor_id, action="experiment.copy", entity_type="experiment", entity_id=copied.id, detail={"source_experiment_id": source.id, "source_version": latest.version_no}))
    return copied


def seed_defaults(password_hash):
    with transaction() as session:
        if session.scalar(select(func.count()).select_from(User)):
            for item in EXPERIMENTS:
                existing = session.scalar(select(Experiment).where(Experiment.code == item["code"]))
                if existing and existing.title != item["title"]:
                    existing.title = item["title"]
                if existing:
                    latest = session.scalar(select(ExperimentVersion).where(ExperimentVersion.experiment_id == existing.id, ExperimentVersion.status == "published").order_by(ExperimentVersion.version_no.desc()))
                    question_upgrade = latest and int(latest.definition.get("question_bank_revision", 0)) < 4
                    steps_upgrade = latest and int(latest.definition.get("operation_steps_revision", 0)) < 3
                    materials_upgrade = latest and (not latest.definition.get("materials") or not latest.definition.get("step_specs"))
                    if latest and (question_upgrade or steps_upgrade or materials_upgrade):
                        newest_no = session.scalar(select(func.max(ExperimentVersion.version_no)).where(ExperimentVersion.experiment_id == existing.id)) or latest.version_no
                        upgraded = deepcopy(latest.definition)
                        source_definition = definition(item)
                        if question_upgrade:
                            upgraded.update({"questions": source_definition["questions"], "question_bank_revision": 4})
                        if steps_upgrade:
                            upgraded.update({"steps": source_definition["steps"], "step_specs": source_definition["step_specs"], "operation_steps_revision": 3})
                        if materials_upgrade:
                            upgraded.update({"materials": source_definition["materials"], "step_specs": source_definition["step_specs"]})
                        session.add(ExperimentVersion(experiment_id=existing.id, version_no=newest_no + 1, status="published", definition=upgraded, published_at=datetime.now(timezone.utc)))
            for course in session.scalars(select(Course)).all():
                ensure_course_experiments(session, course)
            return
        production = current_app.config["APP_ENV"] == "production"
        admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "") if production else "admin123"
        if production and len(admin_password) < 12: raise RuntimeError("INITIAL_ADMIN_PASSWORD must contain at least 12 characters on first production start")
        admin = User(id="T001", username=os.getenv("INITIAL_ADMIN_USERNAME", "admin"), name="实验教师", role="teacher", password_hash=password_hash(admin_password))
        session.add(admin)
        course = None
        if not production:
            student = User(id="S001", username="S001", name="演示学生", role="student", password_hash=password_hash("123456")); course = Course(id="C001", teacher_id=admin.id, name="量子实验演示班")
            session.add_all([student, course, Enrollment(course_id=course.id, student_id=student.id)])
        for order, item in enumerate(EXPERIMENTS, 1):
            exp = Experiment(code=item["code"], title=item["title"], order_no=order)
            session.add(exp)
            session.flush()
            session.add(ExperimentVersion(experiment_id=exp.id, version_no=1, status="published", definition=definition(item), published_at=datetime.now(timezone.utc)))
        if course:
            session.flush()
            ensure_course_experiments(session, course)
