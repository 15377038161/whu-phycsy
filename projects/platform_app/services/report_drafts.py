from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from ..models import AuditEvent, Experiment, ExperimentVersion, ReportDraft, SubmissionRevision, User
from .fitting import validate_fit_result


SCHEMA_VERSION = 1
SECTION_DEFINITIONS = (
    ("purpose", "实验目的"),
    ("apparatus", "仪器设备"),
    ("principle", "实验原理"),
    ("steps", "实验步骤"),
    ("raw_data", "原始数据"),
    ("fit", "拟合与参数"),
    ("error", "误差分析"),
    ("discussion", "讨论"),
    ("conclusion", "结论"),
    ("references", "参考资料"),
)
SECTION_IDS = {item[0] for item in SECTION_DEFINITIONS}
ENGLISH_TITLES = {
    "ION": "Ion Trap Experiment",
    "QKD": "Quantum Key Distribution Experiment",
    "ENT": "Quantum Entanglement Experiment",
    "NV": "Diamond Quantum Computer Experiment",
    "SPI": "Single-Pixel Photon Imaging Experiment",
}
MAX_TEXT = 20_000
MAX_BLOCKS = 240
MAX_TABLE_ROWS = 60
MAX_TABLE_COLUMNS = 12
MAX_ASSETS = 30


def _clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if len(text) > limit:
        raise ValueError(f"报告内容超过 {limit} 字符限制")
    return text


def _paragraph(text: Any) -> dict:
    return {"type": "paragraph", "text": _clean_text(text)}


def _section_text(document: dict, section_id: str) -> str:
    section = next((item for item in document.get("sections", []) if item.get("id") == section_id), None)
    if not section:
        return ""
    lines: list[str] = []
    for block in section.get("blocks", []):
        kind = block.get("type")
        if kind in {"paragraph", "heading", "quote"}:
            lines.append(str(block.get("text", "")))
        elif kind == "formula":
            lines.append(str(block.get("latex", "")))
        elif kind == "list":
            lines.extend(str(item) for item in block.get("items", []))
        elif kind == "table":
            lines.extend("\t".join(str(cell) for cell in row) for row in block.get("rows", []))
        elif kind == "image" and block.get("caption"):
            lines.append(str(block["caption"]))
    return "\n".join(line for line in lines if line).strip()


def default_document(version: ExperimentVersion, experiment: Experiment, student: User) -> dict:
    definition = version.definition or {}
    fit_formula = _clean_text(definition.get("formula"), 500)
    steps = [_clean_text(item, 1000) for item in definition.get("steps", []) if _clean_text(item, 1000)]
    initial = {
        "purpose": [_paragraph(definition.get("summary"))],
        "apparatus": [_paragraph(definition.get("apparatus"))],
        "principle": [_paragraph(definition.get("principle"))],
        "steps": [{"type": "list", "ordered": True, "items": steps}],
        "raw_data": [_paragraph("")],
        "fit": ([{"type": "formula", "latex": fit_formula}] if fit_formula else []) + [_paragraph("")],
        "error": [_paragraph("请结合测量分辨率、拟合残差和实验操作分析误差来源。")],
        "discussion": [_paragraph("")],
        "conclusion": [_paragraph("")],
        "references": [{"type": "list", "ordered": True, "items": [f"{experiment.title} V{version.version_no} 实验教学材料", "本次实验原始测量数据与浏览器端拟合结果"]}],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "title_zh": experiment.title,
        "title_en": ENGLISH_TITLES.get(experiment.code, experiment.title),
        "author_name": student.name,
        "student_id": student.id,
        "affiliation_zh": "武汉大学物理科学与技术学院，武汉 430072",
        "affiliation_en": "School of Physical Science and Technology, Wuhan University, Wuhan 430072, China",
        "abstract_zh": "",
        "keywords_zh": "",
        "abstract_en": "",
        "keywords_en": "",
        "sections": [{"id": key, "title": title, "blocks": initial[key]} for key, title in SECTION_DEFINITIONS],
        "fit_result": {},
        "result_value": "",
        "steps_complete": False,
    }


def _sanitize_block(block: Any, allowed_assets: set[str]) -> dict:
    if not isinstance(block, dict):
        raise ValueError("报告内容块格式错误")
    kind = str(block.get("type", ""))
    if kind in {"paragraph", "heading", "quote"}:
        runs = block.get("runs")
        cleaned_runs = []
        if isinstance(runs, list):
            if len(runs) > 500:
                raise ValueError("单个段落的格式片段过多")
            for run in runs:
                if not isinstance(run, dict):
                    raise ValueError("段落格式片段错误")
                marks = [str(mark) for mark in (run.get("marks") or []) if str(mark) in {"bold", "italic", "underline", "superscript", "subscript"}]
                cleaned_runs.append({"text": _clean_text(run.get("text"), 5000), "marks": list(dict.fromkeys(marks))})
        text = "".join(run["text"] for run in cleaned_runs) if cleaned_runs else _clean_text(block.get("text"))
        if len(text) > MAX_TEXT:
            raise ValueError(f"报告内容超过 {MAX_TEXT} 字符限制")
        result = {"type": kind, "text": text}
        if cleaned_runs:
            result["runs"] = cleaned_runs
        marks = block.get("marks")
        if isinstance(marks, list):
            result["marks"] = [str(mark) for mark in marks if str(mark) in {"bold", "italic", "underline", "superscript", "subscript"}]
        alignment = str(block.get("alignment", "left"))
        if alignment in {"left", "center", "right", "justify"}:
            result["alignment"] = alignment
        return result
    if kind == "formula":
        return {"type": kind, "latex": _clean_text(block.get("latex"), 1000), "caption": _clean_text(block.get("caption"), 500)}
    if kind == "list":
        items = block.get("items")
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("报告列表格式错误或项目过多")
        return {"type": kind, "ordered": bool(block.get("ordered")), "items": [_clean_text(item, 2000) for item in items]}
    if kind == "table":
        rows = block.get("rows")
        if not isinstance(rows, list) or len(rows) > MAX_TABLE_ROWS:
            raise ValueError("报告表格行数超过限制")
        cleaned: list[list[str]] = []
        width = None
        for row in rows:
            if not isinstance(row, list) or not row or len(row) > MAX_TABLE_COLUMNS:
                raise ValueError("报告表格列数或结构错误")
            if width is None:
                width = len(row)
            if len(row) != width:
                raise ValueError("报告表格每行列数必须一致")
            cleaned.append([_clean_text(cell, 1000) for cell in row])
        return {"type": kind, "rows": cleaned, "caption": _clean_text(block.get("caption"), 500)}
    if kind == "image":
        asset_hash = _clean_text(block.get("asset_hash"), 64)
        if asset_hash not in allowed_assets:
            raise ValueError("报告图片不属于当前草稿")
        width = max(20, min(100, int(block.get("width", 80))))
        alignment = str(block.get("alignment", "center"))
        if alignment not in {"left", "center", "right"}:
            alignment = "center"
        return {"type": kind, "asset_hash": asset_hash, "caption": _clean_text(block.get("caption"), 500), "width": width, "alignment": alignment}
    raise ValueError(f"不支持的报告内容类型：{kind or '空'}")


def validate_document(document: Any, allowed_assets: Iterable[str] = ()) -> dict:
    if not isinstance(document, dict):
        raise ValueError("报告文档格式错误")
    assets = set(allowed_assets)
    if len(assets) > MAX_ASSETS:
        raise ValueError("报告图片数量超过限制")
    result = {
        "schema_version": SCHEMA_VERSION,
        "title_zh": _clean_text(document.get("title_zh"), 200),
        "title_en": _clean_text(document.get("title_en"), 300),
        "author_name": _clean_text(document.get("author_name"), 120),
        "student_id": _clean_text(document.get("student_id"), 64),
        "affiliation_zh": _clean_text(document.get("affiliation_zh"), 300),
        "affiliation_en": _clean_text(document.get("affiliation_en"), 500),
        "abstract_zh": _clean_text(document.get("abstract_zh"), 5000),
        "keywords_zh": _clean_text(document.get("keywords_zh"), 500),
        "abstract_en": _clean_text(document.get("abstract_en"), 8000),
        "keywords_en": _clean_text(document.get("keywords_en"), 800),
        "fit_result": validate_fit_result(document.get("fit_result") or {}),
        "result_value": _clean_text(document.get("result_value"), 100),
        "steps_complete": bool(document.get("steps_complete")),
        "system_sync": {str(key)[:160]: str(value)[:64] for key, value in (document.get("system_sync") or {}).items()} if isinstance(document.get("system_sync"), dict) else {},
    }
    sections = document.get("sections")
    if not isinstance(sections, list):
        raise ValueError("报告章节格式错误")
    by_id: dict[str, dict] = {}
    block_count = 0
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("报告章节格式错误")
        section_id = str(section.get("id", ""))
        if section_id not in SECTION_IDS or section_id in by_id:
            raise ValueError("报告章节缺失、重复或不受支持")
        blocks = section.get("blocks")
        if not isinstance(blocks, list):
            raise ValueError("报告章节内容格式错误")
        block_count += len(blocks)
        by_id[section_id] = {"id": section_id, "title": dict(SECTION_DEFINITIONS)[section_id], "blocks": [_sanitize_block(block, assets) for block in blocks]}
    if block_count > MAX_BLOCKS:
        raise ValueError("报告内容块数量超过限制")
    result["sections"] = [by_id.get(key, {"id": key, "title": title, "blocks": []}) for key, title in SECTION_DEFINITIONS]
    return result


def validate_submission_document(document: Any, allowed_assets: Iterable[str] = ()) -> dict:
    result = validate_document(document, allowed_assets)
    required = ("title_zh", "title_en", "abstract_zh", "keywords_zh", "abstract_en", "keywords_en", "result_value")
    missing = [key for key in required if not str(result.get(key, "")).strip()]
    if missing:
        raise ValueError("正式提交前请完整填写中英文题名、摘要、关键词和关键结果")
    if not result["steps_complete"]:
        raise ValueError("必须确认已完成全部必做步骤")
    for section_id in ("principle", "raw_data", "discussion", "conclusion"):
        if not _section_text(result, section_id):
            raise ValueError(f"正式提交前请完成{dict(SECTION_DEFINITIONS)[section_id]}")
    return result


def payload_from_document(document: dict, *, file_hashes: list[str] | None = None) -> dict:
    return {
        "abstract": document.get("abstract_zh", ""),
        "principle": _section_text(document, "principle"),
        "raw_data": _section_text(document, "raw_data"),
        "discussion": "\n".join(filter(None, (_section_text(document, "error"), _section_text(document, "discussion")))),
        "conclusion": _section_text(document, "conclusion"),
        "result_value": document.get("result_value", ""),
        "fit_result": document.get("fit_result") or {},
        "steps_complete": bool(document.get("steps_complete")),
        "file_hashes": list(file_hashes or []),
        "report_document": deepcopy(document),
    }


def document_from_payload(payload: dict, version: ExperimentVersion, experiment: Experiment, student: User) -> dict:
    existing = payload.get("report_document") if isinstance(payload, dict) else None
    if isinstance(existing, dict):
        try:
            return validate_document(existing, payload.get("file_hashes") or [])
        except ValueError:
            pass
    document = default_document(version, experiment, student)
    document["abstract_zh"] = _clean_text(payload.get("abstract"))
    document["result_value"] = _clean_text(payload.get("result_value"), 100)
    document["fit_result"] = payload.get("fit_result") if isinstance(payload.get("fit_result"), dict) else {}
    document["steps_complete"] = bool(payload.get("steps_complete", True))
    replacements = {
        "principle": payload.get("principle"),
        "raw_data": payload.get("raw_data"),
        "discussion": payload.get("discussion"),
        "conclusion": payload.get("conclusion"),
    }
    for section in document["sections"]:
        if section["id"] in replacements and replacements[section["id"]] is not None:
            section["blocks"] = [_paragraph(replacements[section["id"]])]
    return validate_document(document, payload.get("file_hashes") or [])


def get_or_create_draft(session, student: User, course_id: str, version: ExperimentVersion, experiment: Experiment) -> ReportDraft:
    draft = session.scalar(select(ReportDraft).where(ReportDraft.course_id == course_id, ReportDraft.student_id == student.id, ReportDraft.experiment_version_id == version.id))
    if draft:
        return draft
    draft = ReportDraft(student_id=student.id, course_id=course_id, experiment_version_id=version.id, content=default_document(version, experiment, student), asset_hashes=[])
    session.add(draft)
    session.flush()
    session.add(AuditEvent(actor_id=student.id, action="report_draft.create", entity_type="report_draft", entity_id=draft.id, detail={"course_id": course_id, "experiment_version_id": version.id}))
    return draft


def save_draft(session, draft: ReportDraft, document: dict, expected_version: int) -> ReportDraft:
    if draft.status != "active":
        raise ValueError("当前草稿已随正式提交冻结，请复制历史报告后继续修改")
    if expected_version != draft.lock_version:
        raise RuntimeError("report_draft_conflict")
    draft.content = validate_document(document, draft.asset_hashes or [])
    draft.lock_version += 1
    draft.updated_at = datetime.now(timezone.utc)
    session.add(AuditEvent(actor_id=draft.student_id, action="report_draft.save", entity_type="report_draft", entity_id=draft.id, detail={"lock_version": draft.lock_version}))
    session.flush()
    return draft


def copy_revision_to_draft(session, revision: SubmissionRevision, version: ExperimentVersion, experiment: Experiment, student: User) -> ReportDraft:
    draft = session.scalar(select(ReportDraft).where(ReportDraft.course_id == revision.course_id, ReportDraft.student_id == student.id, ReportDraft.experiment_version_id == version.id))
    content = document_from_payload(revision.payload or {}, version, experiment, student)
    assets = list(dict.fromkeys((revision.payload or {}).get("file_hashes") or []))[:MAX_ASSETS]
    if not draft:
        draft = ReportDraft(student_id=student.id, course_id=revision.course_id, experiment_version_id=version.id)
        session.add(draft)
    draft.source_revision_id = revision.id
    draft.status = "active"
    draft.content = content
    draft.asset_hashes = assets
    draft.lock_version = (draft.lock_version or 0) + 1
    draft.updated_at = datetime.now(timezone.utc)
    session.flush()
    session.add(AuditEvent(actor_id=student.id, action="report_draft.copy_revision", entity_type="report_draft", entity_id=draft.id, detail={"source_revision_id": revision.id, "lock_version": draft.lock_version}))
    return draft
