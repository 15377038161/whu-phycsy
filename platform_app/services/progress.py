from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import Course, ExperimentVersion, ReportDraft, StudentExperimentProgress


FIELD_TYPES = {"number", "text", "single_choice", "multiple_choice", "table", "image"}


def _clean_columns(value) -> list[dict]:
    columns = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()[:64]
        label = str(raw.get("label") or key).strip()[:120]
        if key and label:
            columns.append({"key": key, "label": label, "unit": str(raw.get("unit") or "")[:40], "type": "number" if raw.get("type") != "text" else "text"})
    return columns[:12]


def _clean_fields(item: dict) -> list[dict]:
    source = item.get("fields") if isinstance(item.get("fields"), list) else None
    if source is None:
        source = []
        for raw in item.get("data_fields") if isinstance(item.get("data_fields"), list) else []:
            if isinstance(raw, dict):
                source.append({**raw, "type": "text", "required": False})
        if item.get("allow_image"):
            source.append({"key": "step_images", "label": "实验图片", "type": "image", "required": False, "max_count": 6})
    fields = []
    for position, raw in enumerate(source):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "text")
        if kind not in FIELD_TYPES:
            kind = "text"
        key = str(raw.get("key") or f"field_{position + 1}").strip()[:64]
        label = str(raw.get("label") or key).strip()[:120]
        field = {"key": key, "label": label, "type": kind, "required": bool(raw.get("required", False)), "unit": str(raw.get("unit") or "")[:40], "placeholder": str(raw.get("placeholder") or "")[:200]}
        if kind in {"single_choice", "multiple_choice"}:
            field["options"] = [str(option)[:200] for option in (raw.get("options") or []) if str(option).strip()][:20]
        if kind == "table":
            field["columns"] = _clean_columns(raw.get("columns"))
            field["min_rows"] = max(1, min(int(raw.get("min_rows") or 2), 60))
        if kind == "image":
            field["max_count"] = max(1, min(int(raw.get("max_count") or 6), 12))
        fields.append(field)
    return fields[:24]


def normalize_steps(definition: dict) -> list[dict]:
    """Return one canonical step contract while keeping frozen legacy versions readable."""
    normalized = []
    source_steps = definition.get("step_specs") or definition.get("steps", []) or []
    for raw in source_steps:
        item = {"text": raw} if isinstance(raw, str) else dict(raw) if isinstance(raw, dict) else {}
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        kind = str(item.get("kind") or "form")
        if kind not in {"instruction", "form", "fit"}:
            kind = "form"
        index = len(normalized)
        step_id = str(item.get("id") or f"step_{index + 1}").strip()[:64]
        fit_config = dict(item.get("fit_config") or {}) if kind == "fit" else {}
        if fit_config:
            fit_config = {
                "source_step_id": str(fit_config.get("source_step_id") or "")[:64], "source_field_key": str(fit_config.get("source_field_key") or "")[:64],
                "x_column": str(fit_config.get("x_column") or "")[:64], "y_column": str(fit_config.get("y_column") or "")[:64],
                "template": str(fit_config.get("template") or definition.get("fit_template") or "linear")[:40], "formula": str(fit_config.get("formula") or definition.get("formula") or "")[:500],
                "required": bool(fit_config.get("required", True)), "allow_excel_fallback": bool(fit_config.get("allow_excel_fallback", True)),
            }
        normalized.append({
            "index": index, "id": step_id, "title": str(item.get("title") or ("数据拟合" if kind == "fit" else f"实验步骤 {index + 1}"))[:160],
            "kind": kind, "text": text[:3000], "required": bool(item.get("required", True)), "fields": _clean_fields(item), "fit_config": fit_config,
            "fit_hint": str(item.get("fit_hint") or "").strip()[:1000], "report_section": str(item.get("report_section") or ("fit" if kind == "fit" else "raw_data"))[:40],
        })
    if normalized and not any(step["kind"] == "fit" for step in normalized):
        source_step = next((step for step in normalized if any(field["type"] == "table" for field in step["fields"])), None)
        source_field = next((field for field in (source_step or {}).get("fields", []) if field["type"] == "table"), None)
        fit_fields = [] if source_step else [{"key": "fit_data", "label": "拟合数据", "type": "table", "required": True, "unit": "", "placeholder": "", "min_rows": 2, "columns": [{"key": "x", "label": "x", "unit": "", "type": "number"}, {"key": "y", "label": "y", "unit": "", "type": "number"}]}]
        source_columns = (source_field or fit_fields[0]).get("columns", [])
        normalized.append({
            "index": len(normalized), "id": "fit_results", "title": "数据拟合", "kind": "fit", "text": "使用前序步骤记录的数据完成拟合并保存参数、指标和拟合图。", "required": True,
            "fields": fit_fields, "fit_hint": "在线拟合不可用时，可使用 Excel 完成拟合并上传结果图。", "report_section": "fit",
            "fit_config": {"source_step_id": source_step["id"] if source_step else "fit_results", "source_field_key": source_field["key"] if source_field else "fit_data", "x_column": source_columns[0]["key"], "y_column": source_columns[1]["key"], "template": str(definition.get("fit_template") or "linear")[:40], "formula": str(definition.get("formula") or "")[:500], "required": True, "allow_excel_fallback": True},
        })
    return normalized


def validate_step_contract(steps: list[dict]) -> None:
    if not steps:
        raise ValueError("至少需要配置一个实验小关卡")
    ids = [step.get("id") for step in steps]
    if len(ids) != len(set(ids)):
        raise ValueError("小关卡 id 不能重复")
    by_id = {step["id"]: step for step in steps}
    for step in steps:
        keys = [field["key"] for field in step.get("fields", [])]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{step['title']}中的字段 key 不能重复")
        for field in step.get("fields", []):
            if field["type"] == "table" and len(field.get("columns") or []) < 2:
                raise ValueError(f"{step['title']}的数据表至少需要两列")
        if step.get("kind") != "fit":
            continue
        config = step.get("fit_config") or {}
        source = by_id.get(config.get("source_step_id"))
        field = next((item for item in (source or {}).get("fields", []) if item["key"] == config.get("source_field_key") and item["type"] == "table"), None)
        if not source or not field:
            raise ValueError(f"{step['title']}必须绑定一个已配置的数据表字段")
        columns = {column["key"] for column in field.get("columns", [])}
        if config.get("x_column") not in columns or config.get("y_column") not in columns or config.get("x_column") == config.get("y_column"):
            raise ValueError(f"{step['title']}必须明确配置不同的横坐标列和纵坐标列")


def clean_step_data(step: dict, value) -> dict:
    source = value if isinstance(value, dict) else {}
    cleaned = {}
    for field in step.get("fields", []):
        key, kind, raw = field["key"], field["type"], source.get(field["key"])
        if kind == "multiple_choice":
            allowed = set(field.get("options") or [])
            cleaned[key] = [str(item)[:200] for item in (raw if isinstance(raw, list) else []) if str(item) in allowed]
        elif kind == "table":
            configured_columns = field.get("columns", [])
            configured_keys = {column["key"] for column in configured_columns}
            dynamic_columns = []
            raw_columns = (source.get("__table_columns__") or {}).get(key, []) if isinstance(source.get("__table_columns__"), dict) else []
            for column in _clean_columns(raw_columns):
                if column["key"].startswith("extra_") and column["key"] not in configured_keys and column["key"] not in {item["key"] for item in dynamic_columns}:
                    dynamic_columns.append(column)
            all_columns = configured_columns + dynamic_columns
            rows = []
            for raw_row in raw if isinstance(raw, list) else []:
                if not isinstance(raw_row, dict):
                    continue
                row = {column["key"]: str(raw_row.get(column["key"], ""))[:1000] for column in all_columns}
                if any(item.strip() for item in row.values()):
                    rows.append(row)
            cleaned[key] = rows[:60]
            if dynamic_columns:
                cleaned.setdefault("__table_columns__", {})[key] = dynamic_columns
        elif kind == "single_choice":
            value = str(raw or "")[:200]
            cleaned[key] = value if value in set(field.get("options") or []) else ""
        elif kind != "image":
            cleaned[key] = str(raw or "")[:1000]
    return cleaned


def validate_step(step: dict, data: dict, image_hashes: list[str], fit_result: dict | None = None) -> list[dict]:
    errors = []
    for field in step.get("fields", []):
        if not field.get("required"):
            continue
        value = data.get(field["key"])
        if field["type"] == "image":
            valid = bool(image_hashes)
        elif field["type"] == "table":
            rows, columns = value if isinstance(value, list) else [], field.get("columns") or []
            def valid_cell(row, column):
                cell = str(row.get(column["key"], "")).strip()
                if not cell: return False
                if column.get("type") != "number": return True
                try: return math.isfinite(float(cell))
                except ValueError: return False
            valid = len([row for row in rows if all(valid_cell(row, column) for column in columns)]) >= int(field.get("min_rows") or 2)
        elif field["type"] == "multiple_choice":
            valid = bool(value)
        elif field["type"] == "number":
            try:
                valid = bool(str(value or "").strip()) and math.isfinite(float(value))
            except (TypeError, ValueError):
                valid = False
        else:
            valid = bool(str(value or "").strip())
        if not valid:
            errors.append({"field": field["key"], "message": f"请完成“{field['label']}”后再进入下一关"})
    if step.get("kind") == "fit" and step.get("fit_config", {}).get("required", True) and not fit_result:
        errors.append({"field": "fit_result", "message": "请先完成在线拟合，或提交 Excel 拟合结果"})
    return errors


def get_progress(session, course_id: str, student_id: str, version_id: str) -> StudentExperimentProgress:
    row = session.scalar(select(StudentExperimentProgress).where(StudentExperimentProgress.course_id == course_id, StudentExperimentProgress.student_id == student_id, StudentExperimentProgress.experiment_version_id == version_id))
    if row:
        return row
    row = StudentExperimentProgress(course_id=course_id, student_id=student_id, experiment_version_id=version_id)
    session.add(row); session.flush()
    return row


def selection_summary(session, course: Course, student_id: str, versions: list[ExperimentVersion]) -> dict:
    rows = session.scalars(select(StudentExperimentProgress).where(StudentExperimentProgress.course_id == course.id, StudentExperimentProgress.student_id == student_id, StudentExperimentProgress.experiment_version_id.in_([version.id for version in versions]))).all() if versions else []
    by_version = {row.experiment_version_id: row for row in rows}
    selected = [version.id for version in versions if by_version.get(version.id) and by_version[version.id].selected]
    required = max(1, min(int(course.min_experiments_required or 3), len(versions) or 1))
    return {"required": required, "selected": selected, "count": len(selected), "ready": len(selected) >= required, "by_version": by_version}


def _block_hash(blocks: list[dict]) -> str:
    return hashlib.sha256(json.dumps(blocks, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def update_report_from_step(draft: ReportDraft, step: dict, step_no: int, data: dict, image_hashes: list[str], fit_result: dict | None = None, fallback_chart_hash: str = "", force: bool = False) -> bool:
    """Merge a stable system-owned block set; return False when student edits would be overwritten."""
    content = deepcopy(draft.content or {})
    sections = content.setdefault("sections", [])
    section_id = step.get("report_section") or ("fit" if step.get("kind") == "fit" else "raw_data")
    section = next((item for item in sections if item.get("id") == section_id), None)
    if section is None:
        section = {"id": section_id, "title": "拟合与参数" if section_id == "fit" else "原始数据", "blocks": []}; sections.append(section)
    source_id, caption_prefix = f"step:{step.get('id') or step_no}", f"系统同步·step:{step.get('id') or step_no}·"
    old_blocks = [block for block in section.get("blocks", []) if str(block.get("caption") or "").startswith(caption_prefix)]
    sync_state = dict(content.get("system_sync") or {})
    if old_blocks and sync_state.get(source_id) and _block_hash(old_blocks) != sync_state[source_id] and not force:
        return False
    generated, scalar_rows = [], [["字段", "数值", "单位"]]
    for field in step.get("fields", []):
        key, kind = field["key"], field["type"]
        if kind == "table" and data.get(key):
            dynamic = (data.get("__table_columns__") or {}).get(key, []) if isinstance(data.get("__table_columns__"), dict) else []
            configured_keys = {item.get("key") for item in field.get("columns") or []}
            columns = list(field.get("columns") or []) + [column for column in dynamic if column.get("key") not in configured_keys]
            rows = [[f"{column['label']}{'（' + column['unit'] + '）' if column.get('unit') else ''}" for column in columns]]
            rows.extend([[str(row.get(column["key"], "")) for column in columns] for row in data[key]])
            generated.append({"type": "table", "rows": rows, "caption": f"{caption_prefix}{field['label']}"})
        elif kind not in {"image", "table"}:
            value = data.get(key, "")
            if isinstance(value, list): value = "、".join(value)
            if str(value).strip(): scalar_rows.append([field["label"], str(value), field.get("unit", "")])
    if len(scalar_rows) > 1:
        generated.append({"type": "table", "rows": scalar_rows, "caption": f"{caption_prefix}步骤数据"})
    generated.extend({"type": "image", "asset_hash": asset_hash, "caption": f"{caption_prefix}实验图片 {position}", "width": 80, "alignment": "center"} for position, asset_hash in enumerate(image_hashes, 1))
    if fit_result:
        parameter_rows = [["拟合参数", "数值"], *[[str(key), str(value)] for key, value in (fit_result.get("final_parameters") or {}).items()]]
        if len(parameter_rows) > 1: generated.append({"type": "table", "rows": parameter_rows, "caption": f"{caption_prefix}拟合参数"})
        content["fit_result"] = fit_result
    if fallback_chart_hash:
        generated.append({"type": "image", "asset_hash": fallback_chart_hash, "caption": f"{caption_prefix}Excel 拟合结果图", "width": 88, "alignment": "center"})
    section["blocks"] = [block for block in section.get("blocks", []) if not str(block.get("caption") or "").startswith(caption_prefix)] + generated
    sync_state[source_id] = _block_hash(generated); content["system_sync"] = sync_state
    draft.content = content; draft.lock_version += 1; draft.updated_at = datetime.now(timezone.utc)
    return True
