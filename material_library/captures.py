import html as html_module
import base64
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Dict, Optional

from .capture_adapter import (
    link_collected_result,
    link_pending_result,
    local_file_failed_result,
    local_file_saved_result,
)
from .capture_images import IMAGE_FORMATS, download_image, validate_image
from .database import LibraryDatabase, _has_xiaohongshu_access_params, _xiaohongshu_note_id
from .xiaohongshu_cover import renewed_cover_url
# Explanation contract: docs/EXPLAIN.md
TRACKING_QUERY_KEYS = {
    "share_app_id", "share_link_id", "timestamp", "enter_from", "previous_page",
    "source", "share_token", "sec_user_id", "from", "is_from_webapp",
}

X_PAGE_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
X_MEDIA_HOST = "video.twimg.com"
DOUYIN_MEDIA_HOST_SUFFIXES = {
    "douyinvod.com",
    "douyincdn.com",
    "bytecdn.cn",
    "zjcdn.com",
    "ibytedtos.com",
    "pstatp.com",
    "snssdk.com",
}
PLATFORM_ALIASES = {
    "douyin.com": "douyin",
    "www.douyin.com": "douyin",
    "iesdouyin.com": "douyin",
    "www.iesdouyin.com": "douyin",
    "xhslink.com": "xiaohongshu",
    "www.xhslink.com": "xiaohongshu",
    "b23.tv": "bilibili",
    "www.b23.tv": "bilibili",
    "twitter.com": "x",
    "www.twitter.com": "x",
    "x.com": "x",
    "www.x.com": "x",
    "youtu.be": "youtube",
    "www.youtu.be": "youtube",
}
MAX_PUBLIC_PAGE_BYTES = 4 * 1024 * 1024
MAX_LOCAL_SAVE_BYTES = 5 * 1024 * 1024 * 1024
REMOTE_RANGE_PATTERN = re.compile(r"bytes=(?:\d+-\d*|-\d+)", re.I)
DOUYIN_VIDEO_PATH_PATTERN = re.compile(r"/(?:video|note)/(\d{8,})", re.I)
CAPTURE_PARTIAL_PATTERN = re.compile(
    r"^\.[0-9a-f]{32}\.[0-9a-f]{32}\.(?:video|audio|merged|image)\.partial\.(?:mp4|m4a|image)$"
)


class CapturePreviewStateError(ValueError):
    """Keep a resolver failure's preview state without relying on message wording."""

    def __init__(self, message: str, preview_state: str) -> None:
        super().__init__(message)
        self.preview_state = preview_state


class _XPreviewMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.preview_images = []
        self.work_urls = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "meta":
            return
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        key = (values.get("property") or values.get("name") or "").lower()
        if key in ("og:image", "twitter:image") and values.get("content"):
            self.preview_images.append(values["content"])
        if key == "og:url" and values.get("content"):
            self.work_urls.append(values["content"])


class _XOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        hostname = (urllib.parse.urlparse(new_url).hostname or "").lower()
        if hostname not in X_PAGE_HOSTS:
            raise ValueError("公开作品页跳转到了不受信任的地址")
        return super().redirect_request(request, fp, code, msg, headers, new_url)


def _is_douyin_media_host(hostname: str) -> bool:
    host = str(hostname or "").lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in DOUYIN_MEDIA_HOST_SUFFIXES)


def _is_xiaohongshu_media_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(value or ""))
        return bool(
            parsed.scheme == "https" and not parsed.username and not parsed.password
            and parsed.port in (None, 443)
            and re.fullmatch(r"sns-video-[a-z0-9-]+\.xhscdn\.com", parsed.hostname or "", re.I)
        )
    except ValueError:
        return False


def _xiaohongshu_thumbnail_https_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(str(value or ""))
        expected_ports = (None, 80) if parsed.scheme == "http" else (None, 443)
        hostname = str(parsed.hostname or "").lower()
        if not (
            parsed.scheme in {"http", "https"}
            and not parsed.username and not parsed.password
            and parsed.port in expected_ports
            and re.fullmatch(r"sns-(?:webpic|img)-[a-z0-9-]+\.xhscdn\.com", hostname, re.I)
        ):
            return ""
        return urllib.parse.urlunsplit(("https", hostname, parsed.path, parsed.query, ""))
    except ValueError:
        return ""


def _douyin_video_id(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    match = DOUYIN_VIDEO_PATH_PATTERN.search(parsed.path)
    if match:
        return match.group(1)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("modal_id", "vid", "item_id", "video_id"):
        candidate = str((query.get(key) or [""])[0])
        if re.fullmatch(r"\d{8,}", candidate):
            return candidate
    return ""


def _is_trusted_capture_media_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    hostname = (parsed.hostname or "").lower()
    if hostname == X_MEDIA_HOST:
        return parsed.path.lower().endswith(".mp4")
    return _is_douyin_media_host(hostname) or _is_xiaohongshu_media_url(url)


class _CaptureMediaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        if not _is_trusted_capture_media_url(new_url):
            raise ValueError("远程媒体跳转到了不受信任的地址")
        if _is_xiaohongshu_media_url(request.full_url) and not _is_xiaohongshu_media_url(new_url):
            raise ValueError("小红书媒体跳转离开了视频 CDN")
        return super().redirect_request(request, fp, code, msg, headers, new_url)


def open_capture_remote_media(request: urllib.request.Request, timeout: int = 20):
    opener = urllib.request.build_opener(_CaptureMediaRedirectHandler())
    return opener.open(request, timeout=timeout)


def download_capture_remote_media(url: str, target: Path) -> None:
    """Download one trusted media track into a caller-owned partial file."""
    if not _is_trusted_capture_media_url(url):
        raise ValueError("这张卡没有可安全保存的受信任媒体地址")
    parsed = urllib.parse.urlparse(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Accept": "video/mp4,audio/mp4,video/*;q=0.9,audio/*;q=0.8,*/*;q=0.1",
        "Accept-Encoding": "identity",
    }
    if _is_douyin_media_host(parsed.hostname or ""):
        headers["Referer"] = "https://www.douyin.com/"
    elif _is_xiaohongshu_media_url(url):
        headers["Referer"] = "https://www.xiaohongshu.com/"
    request = urllib.request.Request(url, headers=headers)
    response = open_capture_remote_media(request, timeout=90)
    try:
        status = int(getattr(response, "status", 0) or response.getcode() or 200)
        if status != 200:
            raise ValueError("远程媒体没有返回完整文件")
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length > MAX_LOCAL_SAVE_BYTES:
            raise ValueError("视频超过 5GB，本次未保存")
        written = 0
        with target.open("xb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_LOCAL_SAVE_BYTES:
                    raise ValueError("视频超过 5GB，本次未保存")
                handle.write(chunk)
        if written == 0:
            raise ValueError("远程媒体返回了空文件")
    finally:
        response.close()


def validate_local_video(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("下载结果为空")
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=index", "-of", "csv=p=0", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        reason = (result.stderr or "没有检测到可播放的视频轨道").strip()
        raise ValueError("视频完整性校验失败：{}".format(reason[:300]))


def merge_local_video_audio(video_path: Path, audio_path: Path, target: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(video_path), "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
        reason = (result.stderr or "音画合并没有生成文件").strip()
        raise ValueError("抖音音画合并失败：{}".format(reason[:300]))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_capture_track_url(record: Dict[str, object], track: str) -> str:
    if record.get("content_kind") != "video":
        raise ValueError("只有视频链接卡支持媒体操作")
    if track not in ("video", "audio"):
        raise ValueError("远程媒体轨道无效")
    platform = str(record.get("platform") or "")
    if track == "audio" and platform != "douyin":
        raise ValueError("只有抖音分轨视频包含独立音频")
    media_url = str(
        record.get("audio_url") if track == "audio" else record.get("media_url") or ""
    ).strip()
    parsed = urllib.parse.urlparse(media_url)
    hostname = (parsed.hostname or "").lower()
    if platform == "x":
        trusted = (
            parsed.scheme == "https"
            and hostname == X_MEDIA_HOST
            and parsed.path.lower().endswith(".mp4")
            and not parsed.username
            and not parsed.password
        )
    elif platform == "douyin":
        trusted = (
            parsed.scheme == "https"
            and _is_douyin_media_host(hostname)
            and not parsed.username
            and not parsed.password
        )
    elif platform == "xiaohongshu":
        trusted = _is_xiaohongshu_media_url(media_url)
    else:
        trusted = False
    if not trusted:
        raise ValueError("这张卡没有可安全保存的受信任媒体地址")
    return media_url


def _decode_embedded_urls(page_html: str) -> str:
    return (
        html_module.unescape(str(page_html or ""))
        .replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u0026", "&")
        .replace("\\u003D", "=")
        .replace("\\u003d", "=")
    )


def extract_x_public_media_url(
    page_html: str, preview_hint_url: Optional[str] = None
) -> Optional[str]:
    """Return a browser-playable URL for the X post represented by the main poster."""
    decoded = _decode_embedded_urls(page_html)
    parser = _XPreviewMetaParser()
    parser.feed(decoded)
    media_id = ""
    preview_urls = [str(preview_hint_url or "").strip(), *parser.preview_images]
    for preview_url in preview_urls:
        match = re.search(
            r"/(?:amplify_video_thumb|ext_tw_video_thumb|tweet_video_thumb)/(\d+)/",
            preview_url,
        )
        if match:
            media_id = match.group(1)
            break
    if not media_id:
        status_id = ""
        for work_url in parser.work_urls:
            match = re.search(r"/(?:status|statuses)/(\d{8,})(?:[/?#]|$)", work_url)
            if match:
                status_id = match.group(1)
                break
        if status_id:
            encoded_tweet_id = base64.b64encode(
                "Tweet:{}".format(status_id).encode("ascii")
            ).decode("ascii")
            entity_pattern = re.compile(
                r'"client:' + re.escape(encoded_tweet_id)
                + r':media_entities2:\d+":\$R\[\d+\]=\{(.{0,5000}?)(?=\},"client:)',
                re.S,
            )
            main_video_entities = []
            for entity_match in entity_pattern.finditer(decoded):
                entity = entity_match.group(1)
                type_match = re.search(r'type:"([^"]+)"', entity)
                id_match = re.search(r'id_str:"(\d{8,})"', entity)
                image_match = re.search(r'media_url_https:"([^"]+)"', entity)
                if not id_match or not type_match or type_match.group(1) not in ("video", "animated_gif"):
                    continue
                item = (id_match.group(1), image_match.group(1) if image_match else "")
                if item not in main_video_entities:
                    main_video_entities.append(item)

            def preview_key(value: str) -> str:
                try:
                    parsed = urllib.parse.urlparse(str(value or ""))
                except ValueError:
                    return ""
                if (parsed.hostname or "").lower() != "pbs.twimg.com":
                    return ""
                return re.sub(r"\.(?:jpe?g|png|webp)$", "", parsed.path, flags=re.I)

            hint_keys = {preview_key(value) for value in preview_urls} - {""}
            matched_entities = [
                item for item in main_video_entities if preview_key(item[1]) in hint_keys
            ]
            if len(matched_entities) == 1:
                media_id = matched_entities[0][0]
            elif len(main_video_entities) == 1:
                media_id = main_video_entities[0][0]
    if not media_id:
        return None

    candidates = []
    for match in re.finditer(r"https://video\.twimg\.com/[^\s\"'<>\\]+", decoded):
        raw_url = match.group(0).rstrip("),;]")
        parsed = urllib.parse.urlparse(raw_url)
        if (parsed.hostname or "").lower() != X_MEDIA_HOST:
            continue
        if "/{}/".format(media_id) not in parsed.path:
            continue
        path = parsed.path.lower()
        if not (path.endswith(".mp4") or path.endswith(".m3u8")):
            continue
        resolution = re.search(r"/(\d+)x(\d+)/", path)
        if path.endswith(".mp4") and resolution:
            width, height = (int(resolution.group(1)), int(resolution.group(2)))
            area = width * height
            score = (3, area) if max(width, height) <= 1280 else (1, -area)
        elif path.endswith(".mp4"):
            score = (2, 1)
        else:
            score = (2, 0)
        candidates.append((score, raw_url))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def load_x_public_page(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in X_PAGE_HOSTS:
        raise ValueError("只支持补全 X 作品页")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    opener = urllib.request.build_opener(_XOnlyRedirectHandler())
    with opener.open(request, timeout=20) as response:
        body = response.read(MAX_PUBLIC_PAGE_BYTES + 1)
        if len(body) > MAX_PUBLIC_PAGE_BYTES:
            raise ValueError("公开作品页内容过大")
        charset = response.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def _capture_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()[:500]
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", cleaned):
        return ""
    if re.fullmatch(r"(?:Tag\s*[:：]\s*)?(?:置顶|广告|直播|搜索|综合|视频|用户|经验|商品)", cleaned, re.I):
        return ""
    return cleaned


def _capture_author(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()[:300]
    if re.fullmatch(r"[\d.,]+\s*(?:万|亿|[kKmMwW])?", cleaned):
        return ""
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", cleaned):
        return ""
    return cleaned


def _platform_for_url(url: str) -> str:
    hostname = (urllib.parse.urlparse(url).hostname or "").lower()
    if hostname.endswith("douyin.com") or hostname.endswith("iesdouyin.com"):
        return "douyin"
    if hostname.endswith("xiaohongshu.com") or hostname.endswith("xhslink.com"):
        return "xiaohongshu"
    if hostname.endswith("bilibili.com") or hostname.endswith("b23.tv"):
        return "bilibili"
    if hostname.endswith("x.com") or hostname.endswith("twitter.com"):
        return "x"
    if hostname.endswith("youtube.com") or hostname.endswith("youtu.be"):
        return "youtube"
    return hostname.removeprefix("www.")[:80] or "web"


def _normalize_capture_platform(value: str, page_url: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "", str(value or "")).lower()[:80]
    return PLATFORM_ALIASES.get(clean, clean) or _platform_for_url(page_url)


def _canonical_page_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        query.append((key, value))
    return urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, urllib.parse.urlencode(query), "")
    )


def _safe_remote_url(value: Optional[str], allow_blob: bool = False) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urllib.parse.urlparse(raw)
    schemes = ("http", "https", "blob") if allow_blob else ("http", "https")
    return raw[:8000] if parsed.scheme in schemes else None


def _capture_local_filename(record: Dict[str, object], suffix: str = ".mp4") -> str:
    title = _capture_title(str(record.get("page_title") or ""))
    clean = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", title, flags=re.UNICODE)
    clean = clean.replace("_", "-").strip(" .-")[:80].rstrip(" .-")
    if not clean:
        clean = "网页图片" if record.get("content_kind") == "image" else "网页视频"
    capture_id = str(record.get("id") or "")
    return f"{clean}-{capture_id[:8]}{suffix}"


class CaptureService:
    def __init__(
        self,
        database: LibraryDatabase,
        inbox_dir: Path,
        downloader: Optional[Callable[[str, Path], None]] = None,
        page_loader: Optional[Callable[[str], str]] = None,
        remote_media_opener: Optional[Callable[..., object]] = None,
        media_validator: Optional[Callable[[Path], None]] = None,
        media_merger: Optional[Callable[[Path, Path, Path], None]] = None,
        media_cache=None,
    ):
        self.database = database
        self.inbox_dir = Path(inbox_dir).expanduser().resolve()
        # 普通 capture 永远只收链接；只有显式 save_local 才调用下载器。
        self.downloader = downloader or download_capture_remote_media
        self.page_loader = page_loader or load_x_public_page
        self.remote_media_opener = remote_media_opener or open_capture_remote_media
        self.media_validator = media_validator or validate_local_video
        self.media_merger = media_merger or merge_local_video_audio
        self.media_cache = media_cache
        self._local_save_lock = threading.Lock()
        self.database.recover_interrupted_capture_downloads()
        self._cleanup_interrupted_partials()

    def _cleanup_interrupted_partials(self) -> None:
        if not self.inbox_dir.is_dir():
            return
        for candidate in self.inbox_dir.iterdir():
            if candidate.is_file() and CAPTURE_PARTIAL_PATTERN.fullmatch(candidate.name):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass

    def open_remote_media(
        self, capture_id: str, range_header: str = "", *, track: str = "video"
    ):
        record = self.database.get_capture(capture_id)
        platform = str(record.get("platform") or "")
        media_url = _trusted_capture_track_url(record, track)
        clean_range = str(range_header or "").strip()
        if clean_range and not REMOTE_RANGE_PATTERN.fullmatch(clean_range):
            raise ValueError("远程媒体 Range 参数无效")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "identity",
        }
        if platform == "douyin":
            headers["Referer"] = "https://www.douyin.com/"
        elif platform == "xiaohongshu":
            headers["Referer"] = "https://www.xiaohongshu.com/"
        if clean_range:
            headers["Range"] = clean_range
        request = urllib.request.Request(media_url, headers=headers)
        return self.remote_media_opener(request, timeout=20)

    def _probe_remote_url(self, url: str, *, platform: str, track: str) -> None:
        if track not in ("video", "audio"):
            raise ValueError("远程媒体轨道无效")
        if track == "audio" and platform != "douyin":
            raise ValueError("只有抖音分轨视频包含独立音频")
        parsed = urllib.parse.urlparse(str(url or "").strip())
        trusted = (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and (
                (platform == "x" and (parsed.hostname or "").lower() == X_MEDIA_HOST
                 and parsed.path.lower().endswith(".mp4"))
                or (platform == "douyin" and _is_douyin_media_host(parsed.hostname or ""))
                or (platform == "xiaohongshu" and _is_xiaohongshu_media_url(url))
            )
        )
        if not trusted:
            raise ValueError("这张卡没有可安全预检的受信任媒体地址")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept": "audio/mp4,audio/*;q=0.9,*/*;q=0.1" if track == "audio"
            else "video/mp4,video/*;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Range": "bytes=0-0",
        }
        if platform == "douyin":
            headers["Referer"] = "https://www.douyin.com/"
        elif platform == "xiaohongshu":
            headers["Referer"] = "https://www.xiaohongshu.com/"
        response = None
        try:
            request = urllib.request.Request(str(url), headers=headers)
            response = self.remote_media_opener(request, timeout=20)
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            if status not in (200, 206):
                raise ValueError("远程媒体预检失败（HTTP {}）".format(status))
        except urllib.error.HTTPError as error:
            try:
                error.close()
            finally:
                raise ValueError("远程媒体预检失败（HTTP {}）".format(error.code)) from error
        except TimeoutError as error:
            raise ValueError("远程媒体预检超时") from error
        except urllib.error.URLError as error:
            reason = str(getattr(error, "reason", "") or "连接失败")
            raise ValueError("远程媒体预检失败：{}".format(reason[:240])) from error
        finally:
            if response is not None:
                response.close()

    def probe_remote_media(self, capture_id: str, *, track: str = "video") -> None:
        record = self.database.get_capture(capture_id)
        try:
            media_url = _trusted_capture_track_url(record, track)
            self._probe_remote_url(media_url, platform=str(record.get("platform") or ""), track=track)
        except Exception as error:
            self.database.update_capture_preview_state(
                capture_id, "unavailable", error=str(error) or "远程媒体预检失败",
            )
            raise
        self.database.update_capture_preview_state(
            capture_id, "ready", verified_at=time.time(), error=None,
        )

    def local_file_path(self, capture_id: str) -> Optional[Path]:
        record = self.database.get_capture(capture_id)
        expected = self._registered_local_path(record)
        if record.get("status") == "downloaded" and expected is not None and expected.is_file():
            return expected
        return None

    def _registered_local_path(self, record: Dict[str, object]) -> Optional[Path]:
        raw = str(record.get("target_path") or "").strip()
        if not raw:
            return None
        candidate = Path(raw).expanduser().resolve()
        try:
            candidate.relative_to(self.inbox_dir)
        except ValueError:
            return None
        capture_id = str(record.get("id") or "")
        suffixes = IMAGE_FORMATS if record.get("content_kind") == "image" else {".mp4"}
        if candidate.suffix not in suffixes or not (
            candidate.stem == capture_id or candidate.stem.endswith(f"-{capture_id[:8]}")
        ):
            return None
        return candidate

    def save_local(self, capture_id: str) -> Dict[str, object]:
        with self._local_save_lock:
            return self._save_local_locked(capture_id)

    def _save_local_locked(self, capture_id: str) -> Dict[str, object]:
        record = self.database.get_capture(capture_id)
        if record.get("content_kind") == "image":
            return self._save_image(record)
        registered_target = self._registered_local_path(record)
        target = registered_target or (self.inbox_dir / _capture_local_filename(record))
        if target.is_file() and registered_target == target:
            try:
                self.media_validator(target)
                self.database.update_capture(capture_id, "downloaded", str(target), None)
                return self._local_save_result(capture_id, target)
            except Exception as error:
                return self._local_save_failure(
                    capture_id, "已有本地文件校验失败，未覆盖：{}".format(str(error) or "未知错误")
                )
        if target.exists():
            return self._local_save_failure(
                capture_id, "保存位置已有未登记的同名文件，为保护现有文件，本次未覆盖"
            )
        try:
            video_url = _trusted_capture_track_url(record, "video")
            audio_url = (
                _trusted_capture_track_url(record, "audio")
                if str(record.get("audio_url") or "").strip()
                else ""
            )
        except Exception as error:
            return self._local_save_failure(capture_id, str(error) or "媒体地址待补全")

        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        nonce = uuid.uuid4().hex
        video_partial = self.inbox_dir / ".{}.{}.video.partial.mp4".format(capture_id, nonce)
        audio_partial = self.inbox_dir / ".{}.{}.audio.partial.m4a".format(capture_id, nonce)
        merged_partial = self.inbox_dir / ".{}.{}.merged.partial.mp4".format(capture_id, nonce)
        partials = (video_partial, audio_partial, merged_partial)
        self.database.update_capture(capture_id, "downloading", None, None)
        try:
            self.downloader(video_url, video_partial)
            candidate = video_partial
            if audio_url:
                self.downloader(audio_url, audio_partial)
                self.media_merger(video_partial, audio_partial, merged_partial)
                candidate = merged_partial
            self.media_validator(candidate)
            adapter = local_file_saved_result(
                candidate.stat().st_size,
                _sha256_file(candidate),
            )
            os.replace(str(candidate), str(target))
            self.database.update_capture(capture_id, "downloaded", str(target), None)
            return self._local_save_result(capture_id, target, adapter=adapter)
        except Exception as error:
            return self._local_save_failure(capture_id, str(error) or "本地保存失败")
        finally:
            for partial in partials:
                try:
                    partial.unlink()
                except FileNotFoundError:
                    pass

    def _save_image(self, record: Dict[str, object]) -> Dict[str, object]:
        capture_id = str(record["id"])
        partial = self.inbox_dir / f".{capture_id}.{uuid.uuid4().hex}.image.partial.image"
        try:
            existing = self.local_file_path(capture_id)
            if existing is not None:
                validate_image(existing, existing.suffix)
                return self._local_save_result(capture_id, existing)
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
            self.database.update_capture(capture_id, "downloading", None, None)
            suffix = download_image(str(record.get("media_url") or ""), str(record.get("page_url") or ""), partial)
            target = self.inbox_dir / _capture_local_filename(record, suffix)
            if target.exists():
                raise ValueError("保存位置已有同名文件，请修改卡片名称后重试")
            os.replace(partial, target)
            self.database.update_capture(capture_id, "downloaded", str(target), None)
            return self._local_save_result(capture_id, target)
        except Exception as error:
            return self._local_save_failure(capture_id, str(error) or "原图保存失败")
        finally:
            partial.unlink(missing_ok=True)

    def _local_save_result(
        self,
        capture_id: str,
        target: Path,
        *,
        adapter: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        record = self.database.get_capture(capture_id)
        record["adapter"] = adapter or local_file_saved_result(
            target.stat().st_size,
            _sha256_file(target),
        )
        record["message"] = "原件已校验并保存到本地"
        return record

    def _local_save_failure(self, capture_id: str, reason: str) -> Dict[str, object]:
        clean_reason = str(reason or "本地保存失败").strip()[:500]
        self.database.update_capture(capture_id, "download_failed", None, clean_reason)
        record = self.database.get_capture(capture_id)
        record["adapter"] = local_file_failed_result()
        record["message"] = "链接卡已保留，可以重新保存"
        return record

    def refresh_remote_media(self, capture_id: str) -> Dict[str, object]:
        record = self.database.get_capture(capture_id)
        platform = str(record.get("platform") or "")
        if platform != "x" or record.get("content_kind") != "video":
            raise ValueError("此操作用于补全 X 视频卡片")
        current_media = str(record.get("media_url") or "")
        if (
            platform == "x"
            and current_media.startswith("https://")
            and _is_trusted_capture_media_url(current_media)
        ):
            return self._external_preview_result(record)
        media_url = None
        last_error = None
        page_loaded = False
        for _attempt in range(3):
            try:
                page_html = self.page_loader(str(record["page_url"]))
                page_loaded = True
                media_url = extract_x_public_media_url(
                    page_html, str(record.get("thumbnail_url") or "")
                )
                if media_url:
                    break
            except Exception as error:
                last_error = error
        if not media_url:
            reason = (
                "公开作品页没有暴露与所选视频对应的真实媒体地址"
                if page_loaded
                else "公开作品页暂时无法读取，真实媒体地址仍待补全"
            )
            self.database.update_capture(capture_id, "capture_pending", failure_reason=reason)
            raise ValueError(reason) from last_error
        self.database.update_capture_media(capture_id, media_url, platform="x")
        return self._external_preview_result(self.database.get_capture(capture_id))

    def _external_preview_result(self, record: Dict[str, object]) -> Dict[str, object]:
        record["adapter"] = link_collected_result()
        record["message"] = "外部预览地址已更新；仍未创建本地文件"
        return record

    def refresh_thumbnail(self, capture_id: str) -> Dict[str, object]:
        record = self.database.get_capture(capture_id)
        platform = str(record.get("platform") or "")
        if record.get("content_kind") != "video" and not (
            platform == "xiaohongshu" and record.get("content_kind") == "image"
        ):
            raise ValueError("仅支持视频或小红书图片链接卡的封面")
        media_url = str(record.get("media_url") or "").strip()
        thumbnail_url = str(record.get("thumbnail_url") or "").strip()
        source_thumbnail_url = _xiaohongshu_thumbnail_https_url(thumbnail_url)
        if platform == "xiaohongshu" and not source_thumbnail_url:
            raise ValueError("这张卡没有可核对的小红书原封面地址")
        if platform != "xiaohongshu" and not _is_trusted_capture_media_url(media_url):
            raise ValueError("这张卡还没有可用于修复封面的可信媒体地址")
        if self.media_cache is None:
            raise ValueError("封面缓存尚未就绪")
        try:
            if platform == "xiaohongshu":
                try:
                    self.media_cache.capture_source_thumbnail_path(
                        capture_id, source_thumbnail_url, platform,
                    )
                except Exception:
                    fresh_url = renewed_cover_url(
                        str(record["page_url"]), str(record.get("external_id") or ""),
                        source_thumbnail_url,
                    )
                    self.media_cache.capture_source_thumbnail_path(capture_id, fresh_url, platform)
                self.database.update_capture_thumbnail(capture_id, "source_cached", error=None)
            else:
                self.media_cache.capture_thumbnail_path(capture_id, media_url)
                self.database.update_capture_thumbnail(capture_id, "generated", error=None)
        except Exception as error:
            reason = ("封面暂时无法缓存，请重试或打开原笔记重新采集" if platform == "xiaohongshu" else str(error)) or (
                "原封面缓存失败" if platform == "xiaohongshu" else "视频取帧失败"
            )
            self.database.update_capture_thumbnail(capture_id, "failed", error=reason)
            label = "小红书原封面缓存失败" if platform == "xiaohongshu" else "封面修复失败"
            raise ValueError("{}：{}".format(label, reason[:300])) from error
        return self.database.get_capture(capture_id)

    def capture(
        self,
        page_title: str,
        page_url: str,
        media_url: Optional[str],
        *,
        save_only: bool = False,
        platform: str = "",
        author_name: str = "",
        thumbnail_url: Optional[str] = None,
        thumbnail_external_id: str = "",
        external_id: str = "",
        like_count_text: str = "",
        published_at_text: str = "",
        content_kind: str = "video",
        source_identity_verified: bool = False,
    ) -> Dict[str, object]:
        self._validate_page_url(page_url)
        page_url = _canonical_page_url(page_url)
        clean_platform = _normalize_capture_platform(platform, page_url)
        clean_author = _capture_author(author_name)
        clean_external_id = re.sub(r"[^a-zA-Z0-9._-]+", "", str(external_id or ""))[:300]
        clean_thumbnail = _safe_remote_url(thumbnail_url)
        clean_thumbnail_external_id = re.sub(
            r"[^a-zA-Z0-9._-]+", "", str(thumbnail_external_id or "")
        )[:300]
        clean_media = _safe_remote_url(media_url, allow_blob=True)
        clean_content_kind = str(content_kind or "video").strip().lower()
        if clean_content_kind not in ("video", "image"):
            raise ValueError("采集类型只能是视频或图片")
        if clean_platform == "xiaohongshu":
            note_id = _xiaohongshu_note_id(page_url)
            if not note_id or (clean_external_id and clean_external_id.lower() != note_id):
                raise ValueError("无法核对小红书笔记身份，请打开原笔记详情后重新点选")
            clean_external_id = note_id
            if clean_content_kind == "video" and not _is_xiaohongshu_media_url(clean_media):
                clean_media = None
        if clean_platform == "douyin" and clean_content_kind == "video":
            clean_external_id = clean_external_id or _douyin_video_id(page_url)
            if clean_external_id:
                page_url = "https://www.douyin.com/video/{}".format(clean_external_id)
            parsed_douyin_media = urllib.parse.urlparse(clean_media or "")
            if parsed_douyin_media.scheme in ("http", "https") and not (
                parsed_douyin_media.scheme == "https"
                and not parsed_douyin_media.username
                and not parsed_douyin_media.password
                and _is_douyin_media_host(parsed_douyin_media.hostname or "")
            ):
                clean_media = None
        clean_title = _capture_title(page_title)
        clean_like_count = re.sub(r"\s+", " ", str(like_count_text or "")).strip()[:120]
        clean_published_at = re.sub(r"\s+", " ", str(published_at_text or "")).strip()[:160]
        thumbnail_status = "unverified"
        thumbnail_requires_identity = (
            clean_content_kind == "video"
            and clean_platform in {"douyin", "xiaohongshu"}
        )
        if clean_thumbnail and (
            not thumbnail_requires_identity
            or (
                clean_external_id
                and clean_thumbnail_external_id == clean_external_id
            )
        ):
            thumbnail_status = "verified_remote"
        # save_only 现仅作为旧扩展兼容字段；无论它是否传入，都只写链接记录。
        record = self.database.upsert_capture_link(
            clean_title,
            page_url,
            clean_media,
            platform=clean_platform,
            author_name=clean_author,
            thumbnail_url=clean_thumbnail,
            thumbnail_status=thumbnail_status,
            external_id=clean_external_id,
            like_count_text=clean_like_count,
            published_at_text=clean_published_at,
            content_kind=clean_content_kind,
        )
        duplicate = bool(record.pop("duplicate", False))
        parsed_media = urllib.parse.urlparse(clean_media)
        verified_douyin_recapture = (
            duplicate
            and source_identity_verified
            and clean_platform == "douyin"
            and clean_content_kind == "video"
            and bool(clean_external_id)
            and parsed_media.scheme == "https"
            and not parsed_media.username
            and not parsed_media.password
            and _is_douyin_media_host(parsed_media.hostname or "")
        )
        if (
            verified_douyin_recapture
            and str(record.get("media_refresh_status") or "") in {"needs_login", "unavailable"}
        ):
            record = self.database.update_capture_preview_state(
                str(record["id"]),
                "needs_activation",
                error=None,
            )
        failure_reason = ""
        preview_message = None
        effective_media = str(record.get("media_url") or "")
        if (
            clean_content_kind == "video"
            and not effective_media.startswith(("http://", "https://"))
        ):
            if clean_platform == "douyin":
                preview_message = "当前仅有 Blob 或空地址；可在需要时手动激活真实媒体预览"
                self.database.update_capture_preview_state(
                    str(record["id"]), "needs_activation", error=preview_message,
                )
            else:
                failure_reason = "没有取得可预览的真实媒体地址（当前仅有 Blob 或空地址），只保留了作品页"
                if clean_platform == "xiaohongshu":
                    failure_reason = "已收藏视频笔记，尚未取得视频地址；请打开同一小红书笔记、播放视频后按 Alt 或 Option 点画面重新采集"
                self.database.update_capture(
                    str(record["id"]), "capture_pending", failure_reason=failure_reason
                )
            record = self.database.get_capture(str(record["id"]))
        return {
            "id": record["id"],
            "status": record["status"],
            "adapter": (
                link_pending_result() if failure_reason else link_collected_result()
            ),
            "duplicate": duplicate,
            "favorite": bool(record.get("favorite")),
            "seen_count": int(record.get("seen_count") or 1),
            "message": (
                "已进入链接收集箱；真实媒体预览待激活"
                if preview_message
                else "作品页已保留，真实媒体地址待补全"
                if failure_reason
                else "已更新收集记录" if duplicate else "已进入链接收集箱"
            ),
            "failure_reason": failure_reason or None,
            "preview_message": preview_message,
            "source_warning": (
                "已收藏，但原笔记链接缺少访问参数，可能无法打开；请从可正常浏览的笔记详情重新采集"
                if clean_platform == "xiaohongshu" and not _has_xiaohongshu_access_params(str(record.get("page_url") or ""))
                else None
            ),
        }

    @staticmethod
    def _validate_page_url(url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("网页地址无效")
