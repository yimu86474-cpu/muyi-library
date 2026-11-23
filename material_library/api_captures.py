"""Resource handlers for captures; existing application services own side effects."""
import logging
import re
import secrets
import urllib.parse
from http import HTTPStatus
from .xiaohongshu_preview import validate_note_url


_LOGGER = logging.getLogger(__name__)


def list_categories(self, app, parsed, query, match):
    return self._json({"items": app.database.list_capture_categories()})


def create_category(self, app, parsed, query, match):
    return self._json(
        app.database.create_capture_category(str(self._body().get("name", ""))),
        status=HTTPStatus.CREATED,
    )


def rename_category(self, app, parsed, query, match):
    return self._json(app.database.rename_capture_category(
        match.group(1), str(self._body().get("name", ""))
    ))


def delete_category(self, app, parsed, query, match):
    data = self._body()
    return self._json(app.database.delete_capture_category(
        match.group(1),
        replacement_id=str(
            data.get("replacement_id")
            or query.get("replacement_id", [""])[0]
            or ""
        ) or None,
    ))


def list_captures(self, app, parsed, query, match):
    favorite_values = urllib.parse.parse_qs(
        parsed.query, keep_blank_values=True
    ).get("favorite")
    favorite = None
    if favorite_values is not None:
        favorite_value = favorite_values[0]
        if favorite_value not in ("true", "false"):
            raise ValueError("收藏筛选必须是 true 或 false")
        favorite = favorite_value == "true"
    return self._json(app.database.query_captures(
        query=query.get("q", [""])[0],
        platform=query.get("platform", [""])[0],
        status=query.get("status", [""])[0],
        content_kind=query.get("content_kind", [""])[0],
        category=query.get("category", [""])[0],
        favorite=favorite,
        created_from=float(query["created_from"][0]) if "created_from" in query else None,
        created_before=float(query["created_before"][0]) if "created_before" in query else None,
        limit=int(query.get("limit", [48])[0]),
        offset=int(query.get("offset", [0])[0]),
    ))


def _validate_video_identity(data, capture_platform, capture_kind):
    if capture_platform in {"douyin", "xiaohongshu"} and capture_kind == "video":
        if data.get("source_identity_verified") is not True:
            raise ValueError("无法确认你点的是哪条作品，本次未入库；请刷新抖音页后再点一次")
        if capture_platform == "xiaohongshu":
            validate_note_url(str(data.get("page_url", "")), str(data.get("external_id", "")))
            return
        capture_external_id = str(data.get("external_id", ""))
        capture_page_url = str(data.get("page_url", ""))
        parsed_capture_url = urllib.parse.urlparse(capture_page_url)
        if (
            not re.fullmatch(r"\d{8,}", capture_external_id)
            or (parsed_capture_url.hostname or "").lower() != "www.douyin.com"
            or parsed_capture_url.path != "/video/{}".format(capture_external_id)
        ):
            raise ValueError("点击的抖音作品与作品 ID 不一致，本次未入库")


def _enqueue_capture_preview(app, result, *, force=False):
    try:
        preview = app.capture_previews.prepare(
            str(result["id"]), force=force
        )
        preview_state = str(preview.get("state") or "needs_activation")
        result["preview_state"] = preview_state
        if preview_state == "ready":
            result["message"] = "已进入链接收集箱；预览已经准备好"
        elif preview_state == "resolving":
            result["message"] = "已进入链接收集箱；后台正在准备预览"
        elif preview_state == "needs_login":
            result["message"] = "已进入链接收集箱；后台预览需要登录"
        else:
            result["message"] = "已进入链接收集箱；预览可稍后手动加载"
        result["preview_message"] = result["message"]
    except (KeyError, RuntimeError, ValueError):
        # 入库成功与后台预览解耦：后台暂不可用时仍保留链接卡，
        # 由卡片上的“加载预览”继续重试。
        result["preview_state"] = "needs_activation"
        result["message"] = "已进入链接收集箱；预览可稍后手动加载"
        result["preview_message"] = result["message"]


def _require_capture_token(self, app):
    origin = self.headers.get("Origin", "")
    if origin and not self._capture_cors_origin():
        raise PermissionError("只允许已配对的 Chrome 扩展收集")
    supplied = self.headers.get("X-Muyi-Capture-Token", "")
    if not app.capture_token or not secrets.compare_digest(supplied, app.capture_token):
        raise PermissionError("浏览器扩展配对令牌不正确")


def check_pairing(self, app, parsed, query, match):
    _require_capture_token(self, app)
    return self._json({"ok": True})


def create_capture(self, app, parsed, query, match):
    _require_capture_token(self, app)
    data = self._body()
    capture_platform = str(data.get("platform", ""))
    capture_kind = str(data.get("content_kind", "video")).strip().lower()
    _validate_video_identity(data, capture_platform, capture_kind)
    result = app.captures.capture(
        str(data.get("page_title", "")),
        str(data.get("page_url", "")),
        str(data["media_url"]) if data.get("media_url") else None,
        save_only=bool(data.get("save_only")),
        platform=capture_platform,
        author_name=str(data.get("author_name", "")),
        thumbnail_url=(
            str(data["thumbnail_url"]) if data.get("thumbnail_url") else None
        ),
        thumbnail_external_id=str(data.get("thumbnail_external_id", "")),
        external_id=str(data.get("external_id", "")),
        like_count_text=str(data.get("like_count_text", "")),
        published_at_text=str(data.get("published_at_text", "")),
        content_kind=capture_kind,
        source_identity_verified=(data.get("source_identity_verified") is True),
    )
    if capture_platform in {"douyin", "xiaohongshu"} and capture_kind == "video":
        # A new explicit click may supply a fresh URL even during the earlier retry cooldown.
        supplied_new_media = getattr(app, "standalone", False) and bool(data.get("media_url"))
        _enqueue_capture_preview(app, result, force=supplied_new_media)
    return self._json(result)


def prepare_preview(self, app, parsed, query, match):
    self._require_same_loopback_origin()
    data = self._body()
    unknown_fields = set(data) - {"force"}
    if unknown_fields:
        raise ValueError("预览准备请求包含未知字段")
    force = data.get("force", False)
    if not isinstance(force, bool):
        raise ValueError("force 必须是布尔值")
    preview = app.capture_previews.prepare(
        match.group(1), force=force
    )
    status = (
        HTTPStatus.ACCEPTED
        if preview["state"] == "resolving"
        else HTTPStatus.OK
    )
    return self._json(preview, status=status)


def preview_status(self, app, parsed, query, match):
    return self._json(
        app.capture_previews.status(match.group(1))
    )


def get_video(self, app, parsed, query, match):
    return self._remote_capture_media(match.group(1), track="video")


def get_audio(self, app, parsed, query, match):
    return self._remote_capture_media(match.group(1), track="audio")


def get_thumbnail(self, app, parsed, query, match):
    capture_id = match.group(1)
    capture = app.database.get_capture(capture_id)
    if capture.get("thumbnail_status") not in {"source_cached", "generated"}:
        raise FileNotFoundError("这张链接卡还没有可读取的本机封面")
    target = app.media_cache.capture_thumbnail_target(capture_id)
    if not target.is_file():
        raise FileNotFoundError("链接卡封面缓存不存在")
    return self._file(target)


def refresh_thumbnail(self, app, parsed, query, match):
    return self._json(
        app.captures.refresh_thumbnail(match.group(1))
    )


def refresh_media(self, app, parsed, query, match):
    capture_id = match.group(1)
    capture = app.database.get_capture(capture_id)
    if str(capture.get("platform") or "") == "douyin":
        return self._error(
            HTTPStatus.CONFLICT,
            "抖音预览已改为后台准备，请调用 /api/captures/{}/preview/prepare".format(
                capture_id
            ),
        )
    return self._json(
        app.captures.refresh_remote_media(capture_id)
    )


def save_local(self, app, parsed, query, match):
    if not app.media_tools_ready:
        return self._error(HTTPStatus.SERVICE_UNAVAILABLE, "保存媒体需要 FFmpeg 和 FFprobe，请安装后重新打开素材库。")
    result = app.captures.save_local(match.group(1))
    if getattr(app, "standalone", False) and result.get("status") == "downloaded":
        try:
            source = app.database.add_source("网页采集", app.captures.inbox_dir)
            result["library_scan_id"] = app.scans.start(source["id"])
        except Exception:
            _LOGGER.exception("Failed to index a saved capture")
            result["message"] = "原件已保存到本地，素材索引刷新失败。"
    return self._json(result)


def update_metadata(self, app, parsed, query, match):
    data = self._body()
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError("标签必须是列表")
    categories = data.get("categories") if "categories" in data else None
    if categories is not None and not isinstance(categories, list):
        raise ValueError("用途分类必须是列表")
    capture_id = match.group(1)
    updated = app.database.update_capture_metadata(
        capture_id,
        str(data.get("note", "")),
        tags,
        str(data.get("page_title", "")) if "page_title" in data else None,
        categories,
    )
    return self._json(updated)


def set_favorite(self, app, parsed, query, match):
    data = self._body()
    favorite = data.get("favorite")
    if not isinstance(favorite, bool):
        raise ValueError("favorite 必须是 JSON 布尔值")
    capture_id = match.group(1)
    app.database.set_capture_favorite(capture_id, favorite)
    return self._json(app.database.get_capture(capture_id))


def remove_capture(self, app, parsed, query, match):
    app.database.remove_capture(match.group(1))
    return self._json({"ok": True, "original_file_changed": False})


ROUTES = (
    ('GET', re.compile('/api/capture\\-categories'), list_categories),
    ('POST', re.compile('/api/capture\\-categories'), create_category),
    ('PATCH', re.compile('/api/capture-categories/([0-9a-f]+)'), rename_category),
    ('DELETE', re.compile('/api/capture-categories/([0-9a-f]+)'), delete_category),
    ('GET', re.compile('/api/captures'), list_captures),
    ('POST', re.compile('/api/captures/pair'), check_pairing),
    ('POST', re.compile('/api/captures'), create_capture),
    ('POST', re.compile('/api/captures/([0-9a-f]+)/preview/prepare'), prepare_preview),
    ('GET', re.compile('/api/captures/([0-9a-f]+)/preview/status'), preview_status),
    ('GET', re.compile('/api/captures/([0-9a-f]+)/media'), get_video),
    ('GET', re.compile('/api/captures/([0-9a-f]+)/audio'), get_audio),
    ('GET', re.compile('/api/captures/([0-9a-f]+)/thumbnail'), get_thumbnail),
    ('POST', re.compile('/api/captures/([0-9a-f]+)/refresh-thumbnail'), refresh_thumbnail),
    ('POST', re.compile('/api/captures/([0-9a-f]+)/refresh-media'), refresh_media),
    ('POST', re.compile('/api/captures/([0-9a-f]+)/save-local'), save_local),
    ('PATCH', re.compile('/api/captures/([0-9a-f]+)/metadata'), update_metadata),
    ('PATCH', re.compile('/api/captures/([0-9a-f]+)/favorite'), set_favorite),
    ('DELETE', re.compile('/api/captures/([0-9a-f]+)'), remove_capture),
)
