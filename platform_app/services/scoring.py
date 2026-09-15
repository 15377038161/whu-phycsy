from __future__ import annotations

import hashlib
import json

def fingerprint(version_id: str, payload: dict, file_hashes: list[str] | None = None) -> str:
    canonical = {"version": version_id, "payload": payload, "files": sorted(file_hashes or [])}
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
