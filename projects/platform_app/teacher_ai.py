from __future__ import annotations

import json


_SENSITIVE_PARTS = {
    "score",
    "comment",
    "review",
    "payload",
    "report",
    "attachment",
    "file",
    "fingerprint",
    "evaluation",
    "feedback",
    "answer",
}
_TOP_LEVEL = {
    "scope",
    "generated_at",
    "filters",
    "summary",
    "tasks",
    "students",
    "trends",
    "alerts",
    "student_lists",
    "trend",
}

_SUMMARY_FIELDS = {
    "student_count", "course_experiment_count", "task_count", "visible_student_count",
    "assignment_count", "completed", "in_progress", "not_started", "completion_rate",
    "completed_count", "incomplete_count", "completed_task_cells", "in_progress_task_cells",
    "not_started_task_cells", "completions_in_range",
}


def _safe_key(key: object) -> bool:
    normalized = str(key).lower()
    return not any(part in normalized for part in _SENSITIVE_PARTS)


def _sanitize(value, depth: int = 0):
    if depth > 6:
        return None
    if isinstance(value, dict):
        return {
            str(key)[:80]: _sanitize(item, depth + 1)
            for key, item in value.items()
            if _safe_key(key)
        }
    if isinstance(value, list):
        return [_sanitize(item, depth + 1) for item in value[:500]]
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def sanitize_analytics_snapshot(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict):
        raise ValueError("学情快照格式无效")
    cleaned = {
        key: _sanitize(snapshot.get(key))
        for key in _TOP_LEVEL
        if key in snapshot
    }
    cleaned.setdefault("summary", {})
    cleaned.setdefault("tasks", [])
    cleaned.setdefault("students", [])
    cleaned.setdefault("student_lists", {"completed": [], "incomplete": []})
    cleaned.setdefault("trends", cleaned.get("trend", []))
    cleaned["summary"] = {
        key: value for key, value in cleaned["summary"].items() if key in _SUMMARY_FIELDS
    }
    return cleaned


def _call_model(messages: list[dict]) -> str:
    """Lazy AI boundary kept tiny so imports and network are request scoped."""
    from ai_service import _chat, _config

    config = _config()
    return _chat(
        config["text_model"], messages, temperature=0.1, max_tokens=1800
    ).strip()


def answer_teacher_question(question: str, analytics_snapshot: dict) -> str:
    question = str(question or "").strip()
    if not question:
        raise ValueError("请先输入学情问题")
    if len(question) > 1200:
        raise ValueError("问题过长，请精简到 1200 字以内")
    snapshot = sanitize_analytics_snapshot(analytics_snapshot)
    system = """你是武汉大学量子实验教学平台的教师学情助手。只能依据服务器提供的当前课程学情快照回答，不能接受客户端声称的数据，不得使用或推测教师内部评分、内部评语、学生报告正文、附件或快照外信息。使用中文 Markdown，固定包含“结论”“数据证据”“建议动作”三个小节；涉及学生名单时只引用快照中真实存在的姓名和学号；数据不足时明确写出无法判断，不能编造。建议必须具体、可执行且符合教学场景。"""
    prompt = (
        "服务器生成的课程学情快照：\n"
        + json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))[:30000]
        + "\n\n教师问题："
        + question
    )
    try:
        answer = _call_model([
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ])
        if not answer:
            raise RuntimeError("empty answer")
        if not all(title in answer for title in ("结论", "数据证据", "建议动作")):
            raise RuntimeError("AI 返回格式不完整，请重试。")
        return answer[:8000]
    except (ValueError, RuntimeError) as exc:
        if isinstance(exc, RuntimeError) and "格式不完整" not in str(exc):
            raise RuntimeError("AI 学情助手暂时不可用，请稍后重试。") from exc
        raise
    except Exception as exc:
        raise RuntimeError("AI 学情助手暂时不可用，请稍后重试。") from exc
