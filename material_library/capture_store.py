"""浏览器链接卡的持久化与预览身份保护；不下载媒体或操作原文件。"""
import json
import math
import re
import urllib.parse
import uuid
from typing import Any, Dict, Iterable, List, Optional

from .capture_categories import CaptureCategoryStore
from .storage_support import _json, _now, synchronized


CAPTURE_PREVIEW_STATES = {
    "ready",
    "needs_activation",
    "resolving",
    "needs_login",
    "unavailable",
}


DOUYIN_MEDIA_HOST_SUFFIXES = {
    "douyinvod.com",
    "douyincdn.com",
    "bytecdn.cn",
    "zjcdn.com",
    "ibytedtos.com",
    "pstatp.com",
    "snssdk.com",
}


def _trusted_capture_media_host(platform: str, hostname: str) -> bool:
    host = str(hostname or "").lower().rstrip(".")
    if platform == "x":
        return host == "video.twimg.com"
    if platform == "xiaohongshu":
        return bool(re.fullmatch(r"sns-video-[a-z0-9-]+\.xhscdn\.com", host))
    if platform == "douyin":
        return any(
            host == suffix or host.endswith("." + suffix)
            for suffix in DOUYIN_MEDIA_HOST_SUFFIXES
        )
    return False


def _xiaohongshu_note_id(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(str(value or ""))
        if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password
                or parsed.port not in (None, 443 if parsed.scheme == "https" else 80)
                or (parsed.hostname or "").lower() not in ("xiaohongshu.com", "www.xiaohongshu.com")):
            return ""
        match = re.fullmatch(r"/(?:explore|discovery/item|search_result|user/profile/[0-9a-f]{24})/([0-9a-f]{24})/?", parsed.path, re.I)
        return match.group(1).lower() if match else ""
    except ValueError:
        return ""


def _has_xiaohongshu_access_params(value: str) -> bool:
    if not _xiaohongshu_note_id(value):
        return False
    params = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
    return bool(str((params.get("xsec_token") or [""])[0]).strip())


def _preferred_capture_page_url(existing: str, incoming: str, platform: str, external_id: str) -> str:
    if (platform == "xiaohongshu" and external_id
            and _xiaohongshu_note_id(existing) == _xiaohongshu_note_id(incoming) == external_id
            and _has_xiaohongshu_access_params(existing) and not _has_xiaohongshu_access_params(incoming)):
        return existing
    return incoming


class CaptureStore(CaptureCategoryStore):
    """使用调用方提供的连接及同一 RLock；嵌套方法复用它们。"""

    def __init__(self, connection, lock):
        self.connection = connection
        self.lock = lock

    def create_capture(
        self,
        page_title: str,
        page_url: str,
        media_url: Optional[str],
        status: str,
        target_path: Optional[str] = None,
        failure_reason: Optional[str] = None,
        platform: str = "web",
        author_name: str = "",
        thumbnail_url: Optional[str] = None,
        thumbnail_status: str = "unverified",
        external_id: str = "",
        like_count_text: str = "",
        published_at_text: str = "",
        content_kind: str = "video",
    ) -> str:
        capture_id = uuid.uuid4().hex
        now = _now()
        with self.lock, self.connection.transaction():
            self.connection.execute(
                """
                INSERT INTO captures(
                    id, content_kind, page_title, page_url, media_url, platform, author_name,
                    thumbnail_url, thumbnail_status, external_id, like_count_text, published_at_text,
                    note, tags_json, categories_json, target_path, status, failure_reason,
                    seen_count, last_seen_at, created_at, updated_at
                ) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '', '[]', '["待分类"]', %s, %s, %s, 1, %s, %s, %s)
                """,
                (
                    capture_id,
                    content_kind if content_kind in ("video", "image") else "video",
                    page_title[:500],
                    page_url[:4000],
                    media_url[:8000] if media_url else None,
                    platform[:80] or "web",
                    author_name[:300],
                    thumbnail_url[:8000] if thumbnail_url else None,
                    thumbnail_status if thumbnail_status in ("unverified", "verified_remote", "source_cached", "generated", "failed") else "unverified",
                    external_id[:300],
                    like_count_text[:120],
                    published_at_text[:160],
                    target_path,
                    status,
                    failure_reason,
                    now,
                    now,
                    now,
                ),
            )
        return capture_id


    def upsert_capture_link(
        self,
        page_title: str,
        page_url: str,
        media_url: Optional[str],
        platform: str = "web",
        author_name: str = "",
        thumbnail_url: Optional[str] = None,
        thumbnail_status: str = "unverified",
        external_id: str = "",
        like_count_text: str = "",
        published_at_text: str = "",
        content_kind: str = "video",
    ) -> Dict[str, Any]:
        now = _now()
        clean_content_kind = content_kind if content_kind in ("video", "image") else "video"
        clean_platform = (platform or "web")[:80]
        clean_external_id = (external_id or "")[:300]
        with self.lock, self.connection.transaction():
            if (clean_platform == "xiaohongshu" and _has_xiaohongshu_access_params(page_url)
                    and _xiaohongshu_note_id(page_url) == clean_external_id):
                # 同一笔记重采一次即可更新旧图文卡的来源；不改类型、媒体、收藏或整理信息。
                siblings = self.connection.execute(
                    "SELECT id, page_url FROM captures WHERE platform=%s AND external_id=%s",
                    (clean_platform, clean_external_id),
                ).fetchall()
                for sibling in siblings:
                    if (_xiaohongshu_note_id(sibling["page_url"]) == clean_external_id
                            and sibling["page_url"] != page_url):
                        self.connection.execute(
                            "UPDATE captures SET page_url=%s, updated_at=%s WHERE id=%s",
                            (page_url[:4000], now, sibling["id"]),
                        )
            row = None
            if clean_content_kind == "image" and media_url:
                row = self.connection.execute(
                    """
                    SELECT * FROM captures
                    WHERE content_kind='image' AND media_url=%s
                      AND (%s != 'xiaohongshu' OR (platform=%s AND external_id=%s))
                    ORDER BY created_at LIMIT 1
                    """,
                    (media_url[:8000], clean_platform, clean_platform, clean_external_id),
                ).fetchone()
            elif clean_external_id:
                row = self.connection.execute(
                    """
                    SELECT * FROM captures
                    WHERE content_kind=%s AND platform=%s AND external_id=%s
                    ORDER BY created_at LIMIT 1
                    """,
                    (clean_content_kind, clean_platform, clean_external_id),
                ).fetchone()
                if (row is None and clean_platform == "xiaohongshu"
                        and clean_content_kind == "video" and media_url):
                    # 同一笔记取得真实视频后，原图片卡就地升级；备注、标签、分类和收藏不动。
                    row = self.connection.execute(
                        """
                        SELECT * FROM captures
                        WHERE content_kind='image' AND platform=%s AND external_id=%s
                        ORDER BY created_at LIMIT 1
                        """,
                        (clean_platform, clean_external_id),
                    ).fetchone()
            if row is None and not (clean_content_kind == "image" and media_url):
                row = self.connection.execute(
                    "SELECT * FROM captures WHERE content_kind=%s AND page_url=%s ORDER BY created_at LIMIT 1",
                    (clean_content_kind, page_url[:4000]),
                ).fetchone()
            if row is None:
                capture_id = self.create_capture(
                    page_title,
                    page_url,
                    media_url,
                    "saved",
                    platform=clean_platform,
                    author_name=author_name,
                    thumbnail_url=thumbnail_url,
                    thumbnail_status=thumbnail_status,
                    external_id=clean_external_id,
                    like_count_text=like_count_text,
                    published_at_text=published_at_text,
                    content_kind=clean_content_kind,
                )
                result = self.get_capture(capture_id)
                result["duplicate"] = False
                return result

            capture_id = str(row["id"])
            status = row["status"] if row["status"] in ("downloaded", "downloading") else "saved"
            existing_media = str(row["media_url"] or "")
            incoming_media = str(media_url or "")
            preferred_media = (
                incoming_media
                if incoming_media.startswith(("http://", "https://")) or not existing_media
                else existing_media
            )
            incoming_thumbnail_status = (
                thumbnail_status
                if thumbnail_status in ("unverified", "verified_remote", "source_cached", "generated", "failed")
                else "unverified"
            )
            existing_thumbnail_status = str(row["thumbnail_status"] or "unverified")
            accept_thumbnail = bool(thumbnail_url) and (
                incoming_thumbnail_status in ("verified_remote", "source_cached", "generated")
                or not row["thumbnail_url"]
            )
            preferred_thumbnail = thumbnail_url if accept_thumbnail else row["thumbnail_url"]
            preferred_thumbnail_status = (
                incoming_thumbnail_status if accept_thumbnail else existing_thumbnail_status
            )
            preferred_page_url = _preferred_capture_page_url(
                str(row["page_url"] or ""), page_url, clean_platform, clean_external_id
            )
            self.connection.execute(
                """
                UPDATE captures SET
                    content_kind=%s, page_title=%s, page_url=%s, media_url=%s, platform=%s, author_name=%s,
                    thumbnail_url=%s, thumbnail_status=%s, thumbnail_error=NULL,
                    external_id=%s, like_count_text=%s, published_at_text=%s,
                    status=%s, failure_reason=%s,
                    seen_count=seen_count + 1, last_seen_at=%s, updated_at=%s
                WHERE id=%s
                """,
                (
                    clean_content_kind,
                    (page_title or row["page_title"])[:500],
                    preferred_page_url[:4000],
                    preferred_media,
                    clean_platform,
                    (author_name or row["author_name"])[:300],
                    preferred_thumbnail,
                    preferred_thumbnail_status,
                    clean_external_id or row["external_id"],
                    (like_count_text or row["like_count_text"])[:120],
                    (published_at_text or row["published_at_text"])[:160],
                    status,
                    None if status == "saved" else row["failure_reason"],
                    now,
                    now,
                    capture_id,
                ),
            )
            result = self._capture_dict(self.connection.execute(
                "SELECT * FROM captures WHERE id=%s", (capture_id,)
            ).fetchone())
            result["duplicate"] = True
            return result


    def update_capture_thumbnail(
        self,
        capture_id: str,
        status: str,
        *,
        thumbnail_url: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        if status not in ("unverified", "verified_remote", "source_cached", "generated", "failed"):
            raise ValueError("未知链接封面状态")
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE captures SET thumbnail_url=COALESCE(%s, thumbnail_url), "
                "thumbnail_status=%s, thumbnail_error=%s, updated_at=%s WHERE id=%s",
                (thumbnail_url, status, str(error or "")[:500] or None, _now(), capture_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(capture_id)


    def update_capture(
        self,
        capture_id: str,
        status: str,
        target_path: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                """
                UPDATE captures SET status=%s, target_path=%s, failure_reason=%s, updated_at=%s
                WHERE id=%s
                """,
                (status, target_path, failure_reason, _now(), capture_id),
            )


    def update_capture_media(
        self,
        capture_id: str,
        media_url: str,
        *,
        audio_url: str = "",
        platform: str = "",
        external_id: str = "",
        page_url: str = "",
        page_title: str = "",
        published_at_text: str = "",
        obtained_at: Optional[float] = None,
        verified_at: Optional[float] = None,
    ) -> None:
        clean_url = str(media_url or "").strip()[:8000]
        parsed = urllib.parse.urlparse(clean_url)
        now = _now()
        clean_obtained_at = now if obtained_at is None else float(obtained_at)
        clean_verified_at = now if verified_at is None else float(verified_at)
        with self.lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT * FROM captures WHERE id=%s", (capture_id,)
            ).fetchone()
            if row is None:
                raise KeyError(capture_id)
            clean_platform = str(platform or row["platform"] or "")[:80]
            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or not _trusted_capture_media_host(clean_platform, parsed.hostname or "")
                or (clean_platform == "xiaohongshu" and parsed.port not in (None, 443))
            ):
                raise ValueError("真实媒体地址不受信任")
            clean_audio_url = str(audio_url or "").strip()[:8000]
            if clean_audio_url:
                audio_parsed = urllib.parse.urlparse(clean_audio_url)
                if (
                    clean_platform != "douyin"
                    or audio_parsed.scheme != "https"
                    or audio_parsed.username
                    or audio_parsed.password
                    or not _trusted_capture_media_host(clean_platform, audio_parsed.hostname or "")
                ):
                    raise ValueError("真实音频地址不受信任")
            cursor = self.connection.execute(
                """
                UPDATE captures SET
                    media_url=%s, audio_url=%s, platform=%s, external_id=%s, page_url=%s, page_title=%s,
                    published_at_text=%s, media_obtained_at=%s, media_last_verified_at=%s,
                    media_refresh_status='ready', media_refresh_error=NULL,
                    status='saved', failure_reason=NULL, updated_at=%s
                WHERE id=%s
                """,
                (
                    clean_url,
                    clean_audio_url or row["audio_url"],
                    clean_platform,
                    str(external_id or row["external_id"] or "")[:300],
                    str(page_url or row["page_url"] or "")[:4000],
                    str(page_title or row["page_title"] or "")[:500],
                    str(published_at_text or row["published_at_text"] or "")[:160],
                    clean_obtained_at,
                    clean_verified_at,
                    now,
                    capture_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(capture_id)


    def update_capture_preview_state(
        self,
        capture_id: str,
        state: str,
        *,
        obtained_at: Optional[float] = None,
        verified_at: Optional[float] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        if state not in CAPTURE_PREVIEW_STATES:
            raise ValueError("未知链接预览状态")
        clean_error = str(error or "")[:500] or None
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                """
                UPDATE captures SET
                    media_obtained_at=COALESCE(%s, media_obtained_at),
                    media_last_verified_at=COALESCE(%s, media_last_verified_at),
                    media_refresh_status=%s, media_refresh_error=%s, updated_at=%s
                WHERE id=%s
                """,
                (obtained_at, verified_at, state, clean_error, _now(), capture_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(capture_id)
            row = self.connection.execute(
                "SELECT * FROM captures WHERE id=%s", (capture_id,)
            ).fetchone()
            return self._capture_dict(row)


    @synchronized
    def get_capture(self, capture_id: str) -> Dict[str, Any]:
        row = self.connection.execute("SELECT * FROM captures WHERE id=%s", (capture_id,)).fetchone()
        if row is None:
            raise KeyError(capture_id)
        return self._capture_dict(row)


    @synchronized
    def list_captures(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM captures ORDER BY created_at DESC LIMIT %s",
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [self._capture_dict(row) for row in rows]


    @synchronized
    def list_capture_source_metadata(self) -> List[Dict[str, str]]:
        rows = self.connection.execute(
            """
            SELECT id, page_url, platform, author_name, external_id,
                   like_count_text, published_at_text
            FROM captures
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


    def _capture_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(row)
        result["favorite"] = bool(result["favorite"])
        try:
            tags = json.loads(result.pop("tags_json", "[]") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            tags = []
        result["tags"] = [str(tag) for tag in tags if str(tag).strip()]
        try:
            categories = json.loads(result.pop("categories_json", "[]") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            categories = []
        known_categories = {
            str(item["name"])
            for item in self.connection.execute("SELECT name FROM capture_categories").fetchall()
        }
        result["categories"] = [
            str(category) for category in categories if str(category) in known_categories
        ]
        return result


    def update_capture_metadata(
        self,
        capture_id: str,
        note: str,
        tags: Iterable[str],
        page_title: Optional[str] = None,
        categories: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        clean_note = str(note or "").strip()[:4000]
        clean_title = None if page_title is None else " ".join(str(page_title or "").split())[:500]
        clean_tags = []
        for raw_tag in tags:
            tag = " ".join(str(raw_tag or "").split())[:40]
            if tag and tag not in clean_tags:
                clean_tags.append(tag)
            if len(clean_tags) >= 30:
                break
        clean_categories = None
        if categories is not None:
            known_categories = {
                str(row["name"])
                for row in self.connection.execute("SELECT name FROM capture_categories").fetchall()
            }
            clean_categories = []
            for raw_category in categories:
                category = " ".join(str(raw_category or "").split())
                if category not in known_categories:
                    raise ValueError("用途分类不存在")
                if category not in clean_categories:
                    clean_categories.append(category)
            if any(category != "待分类" for category in clean_categories):
                clean_categories = [
                    category for category in clean_categories if category != "待分类"
                ]
        with self.lock, self.connection.transaction():
            exists = self.connection.execute(
                "SELECT 1 FROM captures WHERE id=%s", (capture_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(capture_id)
            self.connection.execute(
                "UPDATE captures SET page_title=COALESCE(%s, page_title), note=%s, tags_json=%s, "
                "categories_json=COALESCE(%s, categories_json), updated_at=%s WHERE id=%s",
                (
                    clean_title,
                    clean_note,
                    _json(clean_tags),
                    None if clean_categories is None else _json(clean_categories),
                    _now(),
                    capture_id,
                ),
            )
        return self.get_capture(capture_id)


    def set_capture_favorite(self, capture_id: str, favorite: bool) -> None:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE captures SET favorite=%s, updated_at=%s WHERE id=%s",
                (int(favorite), _now(), capture_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(capture_id)


    def remove_capture(self, capture_id: str) -> None:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute("DELETE FROM captures WHERE id=%s", (capture_id,))
            if cursor.rowcount == 0:
                raise KeyError(capture_id)


    @synchronized
    def query_captures(
        self,
        query: str = "",
        platform: str = "",
        status: str = "",
        content_kind: str = "",
        category: str = "",
        favorite: Optional[bool] = None,
        limit: int = 48,
        offset: int = 0,
        created_from: Optional[float] = None,
        created_before: Optional[float] = None,
    ) -> Dict[str, Any]:
        clauses = []
        values: List[Any] = []
        if query.strip():
            pattern = "%{}%".format(query.strip()[:300])
            clauses.append(
                "(page_title LIKE %s OR author_name LIKE %s OR page_url LIKE %s OR external_id LIKE %s "
                "OR note LIKE %s OR tags_json LIKE %s)"
            )
            values.extend([pattern, pattern, pattern, pattern, pattern, pattern])
        if platform:
            clauses.append("platform=%s")
            values.append(platform[:80])
        if status:
            clauses.append("status=%s")
            values.append(status[:80])
        if content_kind:
            if content_kind not in ("video", "image"):
                raise ValueError("链接素材类型只能是视频或图片")
            clauses.append("content_kind=%s")
            values.append(content_kind)
        if category:
            known = self.connection.execute(
                "SELECT 1 FROM capture_categories WHERE name=%s", (category,)
            ).fetchone()
            if known is None:
                raise ValueError("用途分类不存在")
            clauses.append("categories_json LIKE %s")
            escaped = _json(category).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses[-1] += " ESCAPE '\\'"
            values.append("%{}%".format(escaped))
        if favorite is not None:
            clauses.append("favorite=%s")
            values.append(int(favorite))
        for boundary, operator in ((created_from, ">="), (created_before, "<")):
            if boundary is not None:
                if not math.isfinite(boundary) or boundary < 0:
                    raise ValueError("入库时间必须是有效时间")
                clauses.append("created_at " + operator + " %s")
                values.append(boundary)
        if created_from is not None and created_before is not None and created_from >= created_before:
            raise ValueError("开始日期不能晚于结束日期")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = int(self.connection.execute(
            "SELECT COUNT(*) AS count FROM captures" + where, values
        ).fetchone()["count"])
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, int(offset))
        rows = self.connection.execute(
            "SELECT * FROM captures" + where +
            " ORDER BY last_seen_at DESC, created_at DESC LIMIT %s OFFSET %s",
            [*values, safe_limit, safe_offset],
        ).fetchall()
        platform_rows = self.connection.execute(
            "SELECT platform, COUNT(*) AS count FROM captures GROUP BY platform ORDER BY count DESC"
        ).fetchall()
        status_rows = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM captures GROUP BY status ORDER BY count DESC"
        ).fetchall()
        kind_rows = self.connection.execute(
            "SELECT content_kind, COUNT(*) AS count FROM captures "
            "GROUP BY content_kind ORDER BY count DESC"
        ).fetchall()
        return {
            "items": [self._capture_dict(row) for row in rows],
            "total": total,
            "stats": {
                "platforms": {row["platform"]: int(row["count"]) for row in platform_rows},
                "statuses": {row["status"]: int(row["count"]) for row in status_rows},
                "kinds": {row["content_kind"]: int(row["count"]) for row in kind_rows},
            },
        }


    @synchronized
    def capture_count(self) -> int:
        return int(self.connection.execute(
            "SELECT COUNT(*) AS count FROM captures"
        ).fetchone()["count"])
