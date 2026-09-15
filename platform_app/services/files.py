from __future__ import annotations
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Mapping

from flask import current_app
from werkzeug.utils import secure_filename

from ..db import transaction
from ..models import FileAsset

UploadPolicy = Mapping[str, frozenset[str]]

IMAGE_UPLOADS: UploadPolicy = {
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".png": frozenset({"image/png"}),
    ".webp": frozenset({"image/webp"}),
}
VIDEO_UPLOADS: UploadPolicy = {
    ".mp4": frozenset({"video/mp4"}),
    ".webm": frozenset({"video/webm"}),
    ".mov": frozenset({"video/quicktime"}),
    ".m4v": frozenset({"video/mp4", "video/x-m4v"}),
}
TEACHING_MATERIAL_UPLOADS: UploadPolicy = {
    ".pdf": frozenset({"application/pdf"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
}
REFERENCE_UPLOADS: UploadPolicy = {
    **TEACHING_MATERIAL_UPLOADS,
    ".ppt": frozenset({"application/vnd.ms-powerpoint", "application/octet-stream"}),
    ".pptx": frozenset({"application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/octet-stream"}),
}
STUDENT_ATTACHMENT_UPLOADS: UploadPolicy = {
    **IMAGE_UPLOADS,
    ".pdf": frozenset({"application/pdf"}),
    ".csv": frozenset({"text/csv", "application/csv", "application/vnd.ms-excel"}),
    ".txt": frozenset({"text/plain"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ".xlsx": frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
}


def save_upload(upload, allowed: UploadPolicy) -> str:
    safe_name = secure_filename(upload.filename or "")
    suffix = Path(safe_name).suffix.lower()
    mimetype = (upload.mimetype or "application/octet-stream").split(";", 1)[0].strip().lower()
    if suffix not in allowed or mimetype not in allowed[suffix]:
        raise ValueError("不支持的上传文件类型或文件扩展名与类型不匹配")
    data_dir = Path(current_app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    digestor = hashlib.sha256(); size = 0
    with tempfile.NamedTemporaryFile(prefix="upload-", dir=data_dir, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        while chunk := upload.stream.read(1024 * 1024):
            digestor.update(chunk); temporary.write(chunk); size += len(chunk)
    if not size:
        temporary_path.unlink(missing_ok=True)
        raise ValueError("上传文件为空")
    digest = digestor.hexdigest()
    object_key = f"files/{digest[:2]}/{digest}{suffix}"; target = data_dir / object_key
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists(): temporary_path.unlink()
    else: os.replace(temporary_path, target)
    with transaction() as session:
        if not session.get(FileAsset, digest): session.add(FileAsset(sha256=digest, object_key=object_key, original_name=(upload.filename or "file")[:240], content_type=mimetype[:120], size=size))
    return digest
