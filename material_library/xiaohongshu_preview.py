"""Refresh one verified note's MP4 URL in an owned browser tab; never download."""

# Explanation contract: docs/INTERFACE_CONTRACT.md
import re
import time
import uuid
from urllib.parse import urlsplit, urlunsplit


class XiaohongshuPreviewError(ValueError):
    def __init__(self, message, state="needs_activation"):
        super().__init__(message)
        self.preview_state = state


def validate_note_url(page_url, expected_id):
    parsed = urlsplit(page_url)
    if (parsed.scheme != "https" or parsed.hostname != "www.xiaohongshu.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise XiaohongshuPreviewError("小红书作品链接不受信任", "unavailable")
    match = re.fullmatch(r"/(?:explore|discovery/item|search_result)/([0-9a-f]{24})/?", parsed.path, re.I)
    if not match:
        match = re.fullmatch(r"/user/profile/[0-9a-f]{24}/([0-9a-f]{24})/?", parsed.path, re.I)
    if not match or match.group(1).lower() != expected_id.lower():
        raise XiaohongshuPreviewError("小红书作品 ID 不匹配", "unavailable")


def normalize_media_url(value):
    try:
        parsed = urlsplit(str(value or ""))
        ports = (None, 80) if parsed.scheme == "http" else (None, 443)
        if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
                or parsed.port not in ports
                or not re.fullmatch(r"sns-video-[a-z0-9-]+\.xhscdn\.com", parsed.hostname or "")):
            return ""
        return urlunsplit(("https", parsed.hostname, parsed.path, parsed.query, ""))
    except ValueError:
        return ""
