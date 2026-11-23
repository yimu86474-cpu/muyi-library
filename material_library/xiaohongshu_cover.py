"""Renew an expiring cover only from the same note and selected image."""

import json
import re
import urllib.parse
import urllib.request

from .database import _xiaohongshu_note_id


def _validate_note_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"www.xiaohongshu.com", "xiaohongshu.com"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("原笔记地址不受信任")


class _NoteRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _validate_note_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def load_note_page(url):
    _validate_note_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.build_opener(_NoteRedirectHandler()).open(request, timeout=15) as response:
        body = response.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024:
        raise ValueError("原笔记页面超出读取上限")
    return body.decode("utf-8", errors="replace")


def _image_key(url):
    parsed = urllib.parse.urlsplit(str(url or ""))
    if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
            or parsed.port not in (None, 80, 443)
            or not re.fullmatch(r"sns-(?:webpic|img)-[a-z0-9-]+\.xhscdn\.com", parsed.hostname or "", re.I)):
        return ""
    return parsed.path.rsplit("/", 1)[-1].split("!", 1)[0]


def renewed_cover_url(page_url, note_id, previous_url, *, page_loader=load_note_page):
    """Require hydrated note identity and the original image key; never guess a cover."""
    _validate_note_url(page_url)
    if not note_id or _xiaohongshu_note_id(page_url) != note_id:
        raise ValueError("原笔记 ID 不匹配，已拒绝替换封面")
    image_key = _image_key(previous_url)
    if not image_key:
        raise ValueError("没有可核对的原图片标识")
    page = page_loader(page_url)
    state = re.search(r"window\.__INITIAL_STATE__\s*=([\s\S]*?)</script>", page)
    marker = re.search(r'"noteDetailMap"\s*:\s*', state[1]) if state else None
    if not marker:
        raise ValueError("原笔记暂时无法读取，请打开原笔记重新采集")
    try:
        detail = json.JSONDecoder().raw_decode(state[1][marker.end():])[0]
        note = detail.get(note_id, {}).get("note", {})
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("原笔记数据无法核验") from error
    if note.get("noteId") != note_id:
        raise ValueError("原笔记 ID 不匹配，已拒绝替换封面")
    for item in note.get("imageList", []):
        candidates = [item.get("urlDefault"), item.get("urlPre"), item.get("url")]
        candidates.extend(info.get("url") for info in item.get("infoList", []))
        for candidate in candidates:
            if candidate and _image_key(candidate) == image_key:
                parsed = urllib.parse.urlsplit(candidate)
                return urllib.parse.urlunsplit(("https", parsed.hostname, parsed.path, parsed.query, ""))
    raise ValueError("原笔记中未找到原来选中的图片，已保留旧记录")
