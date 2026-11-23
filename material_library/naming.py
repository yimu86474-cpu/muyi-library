import re
from pathlib import Path


OPAQUE_PREFIX = re.compile(r"^(?:[0-9a-f]{32}-)+", re.IGNORECASE)
WORKFLOW_PREFIX = re.compile(r"^\d{3}[-_]\d{6}[-_]")
DATE_ONLY = re.compile(r"^\d{1,2}月\d{1,2}日(?:\s*\(\d+\))?$")


def readable_display_name(relative_path: str, media_type: str = "video") -> str:
    original = Path(relative_path).name
    stem = Path(original).stem.strip()
    opaque_id = stem[:6]
    cleaned = OPAQUE_PREFIX.sub("", stem)
    cleaned = WORKFLOW_PREFIX.sub("", cleaned)
    cleaned = cleaned.replace("_", "-").replace("Codx", "Codex")
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip(" .-_")
    if not cleaned or re.fullmatch(r"[0-9a-f]{16,}", cleaned, re.IGNORECASE) or DATE_ONLY.fullmatch(cleaned):
        kind = {"image": "图片", "audio": "音频"}.get(media_type, "视频")
        return "待命名{} · {}".format(kind, opaque_id or "未知")
    return cleaned[:160]
