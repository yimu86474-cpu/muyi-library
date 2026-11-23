# Explanation contract: docs/EXPLAIN.md

import mimetypes
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple


DOUYIN_MEDIA_HOST_SUFFIXES = (
    "douyinvod.com",
    "douyincdn.com",
    "bytecdn.cn",
    "zjcdn.com",
    "ibytedtos.com",
    "pstatp.com",
    "snssdk.com",
)
CAPTURE_MEDIA_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class RangeNotSatisfiable(ValueError):
    pass


def parse_range_header(header: str, size: int) -> Tuple[int, int]:
    if size <= 0 or not header.startswith("bytes=") or "," in header:
        raise RangeNotSatisfiable("无效分段范围")
    value = header[6:].strip()
    if "-" not in value:
        raise RangeNotSatisfiable("无效分段范围")
    start_text, end_text = value.split("-", 1)
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                raise RangeNotSatisfiable("无效尾部分段")
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_text)
            end = size - 1 if not end_text else min(int(end_text), size - 1)
    except ValueError as error:
        raise RangeNotSatisfiable("无效分段数字") from error
    if start < 0 or start >= size or end < start:
        raise RangeNotSatisfiable("分段超出文件")
    return start, end


def media_mime(path: Path) -> str:
    overrides = {
        ".mkv": "video/x-matroska",
        ".m4v": "video/mp4",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".heic": "image/heic",
    }
    return overrides.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"


class PreviewError(RuntimeError):
    pass


class MediaCache:
    def __init__(self, runtime_dir: Path):
        self.runtime_dir = Path(runtime_dir)
        self.thumbnail_dir = self.runtime_dir / "thumbnails"
        self.preview_dir = self.runtime_dir / "previews"
        self.frame_dir = self.runtime_dir / "classification-frames"
        self.capture_thumbnail_dir = self.runtime_dir / "capture-thumbnails"
        for directory in (
            self.thumbnail_dir,
            self.preview_dir,
            self.frame_dir,
            self.capture_thumbnail_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def capture_thumbnail_target(self, capture_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", str(capture_id or "")):
            raise PreviewError("链接卡片 ID 无效")
        return self.capture_thumbnail_dir / "{}.jpg".format(capture_id)

    def capture_source_thumbnail_path(
        self, capture_id: str, thumbnail_url: str, platform: str,
    ) -> Path:
        parsed = urllib.parse.urlparse(str(thumbnail_url or ""))
        trusted_xiaohongshu_cover = (
            platform == "xiaohongshu"
            and parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and re.fullmatch(
                r"sns-(?:webpic|img)-[a-z0-9-]+\.xhscdn\.com",
                parsed.hostname or "",
                re.I,
            )
        )
        if not trusted_xiaohongshu_cover:
            raise PreviewError("小红书原封面地址不在受信图片 CDN")
        target = self.capture_thumbnail_target(capture_id)
        temporary = self.capture_thumbnail_dir / "{}.tmp.jpg".format(capture_id)
        temporary.unlink(missing_ok=True)
        headers = (
            "Referer: https://www.xiaohongshu.com/\r\n"
            "Accept: image/avif,image/webp,image/apng,image/*,*/*;q=0.8\r\n"
            "Accept-Encoding: identity\r\n"
        )
        try:
            self._run(
                [
                    "ffmpeg", "-y", "-v", "error", "-rw_timeout", "15000000",
                    "-user_agent", CAPTURE_MEDIA_USER_AGENT,
                    "-headers", headers,
                    "-i", str(thumbnail_url), "-frames:v", "1", "-vf",
                    "scale=1280:1280:force_original_aspect_ratio=decrease",
                    "-q:v", "3", str(temporary),
                ],
                "小红书原封面缓存失败",
                timeout=45,
            )
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise PreviewError("小红书原封面缓存失败：没有生成图片")
            temporary.replace(target)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    def capture_thumbnail_path(self, capture_id: str, media_url: str) -> Path:
        if not str(media_url or "").startswith("https://"):
            raise PreviewError("链接卡片没有可信的 HTTPS 媒体地址")
        target = self.capture_thumbnail_target(capture_id)
        temporary = self.capture_thumbnail_dir / "{}.tmp.jpg".format(capture_id)
        temporary.unlink(missing_ok=True)
        hostname = (urllib.parse.urlparse(str(media_url)).hostname or "").lower()
        input_options = []
        if any(
            hostname == suffix or hostname.endswith("." + suffix)
            for suffix in DOUYIN_MEDIA_HOST_SUFFIXES
        ):
            input_options = [
                "-user_agent",
                CAPTURE_MEDIA_USER_AGENT,
                "-headers",
                "Referer: https://www.douyin.com/\r\n"
                "Accept: video/mp4,video/*;q=0.9,*/*;q=0.1\r\n"
                "Accept-Encoding: identity\r\n",
            ]
        try:
            self._run(
                [
                    "ffmpeg", "-y", "-v", "error", "-rw_timeout", "15000000",
                    *input_options,
                    "-ss", "0.200", "-i", str(media_url), "-frames:v", "1", "-vf",
                    "scale=640:360:force_original_aspect_ratio=decrease,"
                    "pad=640:360:(ow-iw)/2:(oh-ih)/2:color=#111111",
                    "-q:v", "4", str(temporary),
                ],
                "链接视频封面生成失败",
                timeout=90,
            )
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise PreviewError("链接视频封面生成失败：没有生成图片")
            temporary.replace(target)
            return target
        finally:
            temporary.unlink(missing_ok=True)

    def thumbnail_path(self, asset_id: str, source: Path, media_type: str, duration: Optional[float]) -> Path:
        if media_type == "audio":
            target = self.thumbnail_dir / "{}.svg".format(asset_id)
            if not target.exists():
                target.write_text(
                    """<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#1b1830"/><stop offset="1" stop-color="#5639ca"/></linearGradient></defs><rect width="640" height="360" rx="24" fill="url(#g)"/><g fill="#fff" opacity=".9"><rect x="170" y="145" width="12" height="70" rx="6"/><rect x="194" y="115" width="12" height="130" rx="6"/><rect x="218" y="135" width="12" height="90" rx="6"/><rect x="242" y="90" width="12" height="180" rx="6"/><rect x="266" y="125" width="12" height="110" rx="6"/><rect x="290" y="105" width="12" height="150" rx="6"/><rect x="314" y="140" width="12" height="80" rx="6"/><rect x="338" y="120" width="12" height="120" rx="6"/><rect x="362" y="145" width="12" height="70" rx="6"/><rect x="386" y="130" width="12" height="100" rx="6"/><rect x="410" y="150" width="12" height="60" rx="6"/><rect x="434" y="140" width="12" height="80" rx="6"/></g></svg>""",
                    encoding="utf-8",
                )
            return target
        target = self.thumbnail_dir / "{}.jpg".format(asset_id)
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            return target
        command = ["ffmpeg", "-y", "-v", "error"]
        if media_type == "video":
            seek = max(0.0, float(duration or 0) * 0.2)
            command += ["-ss", "{:.3f}".format(seek)]
        command += [
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:color=#111111",
            "-q:v",
            "4",
            str(target),
        ]
        self._run(command, "缩略图生成失败")
        return target

    def preview_path(self, asset_id: str, source: Path, media_type: str) -> Path:
        extension = source.suffix.lower()
        compatible = {
            "video": {".mp4", ".webm", ".m4v"},
            "image": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".apng", ".avif"},
            "audio": {".mp3", ".wav", ".m4a"},
        }
        if extension in compatible.get(media_type, set()):
            return source
        if media_type == "video":
            target = self.preview_dir / "{}.mp4".format(asset_id)
            command = [
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "24", "-c:a", "aac",
                "-movflags", "+faststart", str(target),
            ]
        elif media_type == "audio":
            target = self.preview_dir / "{}.mp3".format(asset_id)
            command = [
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-vn", "-c:a", "libmp3lame", "-q:a", "4", str(target),
            ]
        elif media_type == "image":
            target = self.preview_dir / "{}.jpg".format(asset_id)
            command = [
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-frames:v", "1", "-q:v", "3", str(target),
            ]
        else:
            raise PreviewError("不支持的素材类型")
        if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
            self._run(command, "兼容预览生成失败")
        return target

    def extract_classification_frames(
        self, asset_id: str, source: Path, duration: Optional[float]
    ) -> list:
        target_dir = self.frame_dir / asset_id
        target_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, ratio in enumerate((0.2, 0.5, 0.8), start=1):
            target = target_dir / "{}.jpg".format(index)
            if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
                seek = max(0.0, float(duration or 0) * ratio)
                self._run(
                    [
                        "ffmpeg", "-y", "-v", "error", "-ss", "{:.3f}".format(seek),
                        "-i", str(source), "-frames:v", "1", "-vf",
                        "scale=768:-2:force_original_aspect_ratio=decrease", "-q:v", "4", str(target),
                    ],
                    "分类取帧失败",
                )
            frames.append(target)
        return frames

    @staticmethod
    def _run(command: list, message: str, timeout: int = 900) -> None:
        try:
            subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            detail = getattr(error, "stderr", "") or str(error)
            raise PreviewError("{}：{}".format(message, detail.strip()[:500])) from error
