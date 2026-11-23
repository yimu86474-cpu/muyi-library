import json
import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

from .database import LibraryDatabase


# Explanation contract: docs/EXPLAIN.md
MEDIA_EXTENSIONS = {
    "video": {".mp4", ".mov", ".m4v", ".mkv", ".webm"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".apng", ".avif"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac"},
}
EXTENSION_TYPES = {
    extension: media_type
    for media_type, extensions in MEDIA_EXTENSIONS.items()
    for extension in extensions
}
EXCLUDED_DIRS = {
    "node_modules",
    "__pycache__",
    ".git",
    ".cache",
    "cache",
    "caches",
    "models",
    "model",
    "checkpoints",
    "venv",
    ".venv",
    "env",
    ".env",
    "envs",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "site-packages",
    "vendor",
    "pods",
    "deriveddata",
    "tmp",
    "temp",
    "coverage",
    ".next",
    ".nuxt",
    ".gradle",
    "target",
    "out",
    "dist",
    "build",
    "runtime",
    "audioalg",
}
EXCLUDED_DIRECTORY_SUFFIXES = {
    ".app",
    ".bundle",
    ".framework",
    ".photolibrary",
    ".photoslibrary",
}


@dataclass(frozen=True)
class MediaFile:
    path: Path
    relative_path: str
    media_type: str


def probe_media(path: Path, media_type: str) -> Dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,duration,channels",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return {"probe_error": str(error)}
    streams = data.get("streams") or []
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    format_data = data.get("format") or {}
    duration = format_data.get("duration") or video_stream.get("duration")
    return {
        "duration": float(duration) if duration else None,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "has_audio": any(item.get("codec_type") == "audio" for item in streams),
        "stream_count": len(streams),
        "media_type": media_type,
    }


def quick_fingerprint(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(128 * 1024))
        if size > 128 * 1024:
            handle.seek(max(0, size - 128 * 1024))
            digest.update(handle.read(128 * 1024))
    return digest.hexdigest()


class MediaScanner:
    def __init__(self, probe: Optional[Callable[[Path, str], Dict[str, Any]]] = None):
        self.probe = probe or probe_media

    @staticmethod
    def _relative_prefixes(values: Iterable[str]) -> List[PurePosixPath]:
        prefixes = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("排除目录前缀必须是字符串")
            raw = value.strip()
            parts = raw.split("/")
            path = PurePosixPath(raw)
            if (
                not raw
                or raw.startswith("/")
                or raw.endswith("/")
                or any(part in ("", ".", "..") for part in parts)
                or path.is_absolute()
            ):
                raise ValueError("排除目录必须是来源内的相对路径前缀")
            prefixes.append(PurePosixPath(*parts))
        return prefixes

    @staticmethod
    def _enumeration_error(error: Exception, path: str = ".") -> Dict[str, str]:
        return {
            "path": path,
            "status": "permission_required" if isinstance(error, PermissionError) else "scan_failed",
            "message": str(error),
        }

    def walk(
        self,
        root: Path,
        excluded_roots: Optional[Iterator[Path]] = None,
        excluded_relative_prefixes: Optional[Iterable[str]] = None,
        errors: Optional[List[Dict[str, str]]] = None,
    ) -> Iterator[MediaFile]:
        error_records = errors if errors is not None else []
        try:
            root = Path(root).expanduser().resolve()
            prefixes = self._relative_prefixes(excluded_relative_prefixes or ())
            root_is_directory = root.is_dir()
        except OSError as error:
            error_records.append(self._enumeration_error(error))
            return
        if not root_is_directory:
            error_records.append({
                "path": ".",
                "status": "scan_failed",
                "message": "登记来源目录不存在或不是目录",
            })
            return
        excluded = set()
        for path in excluded_roots or ():
            try:
                candidate = Path(path).expanduser()
                if candidate.is_dir():
                    excluded.add(candidate.resolve())
            except OSError as error:
                error_records.append(self._enumeration_error(error))
                return
        def record_error(error: OSError) -> None:
            raw_path = Path(getattr(error, "filename", "") or root)
            try:
                relative_path = raw_path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                relative_path = "."
            error_records.append(self._enumeration_error(error, relative_path))

        for current, directories, files in os.walk(str(root), followlinks=False, onerror=record_error):
            current_path = Path(current)
            included_directories = []
            for name in directories:
                if (
                    name.startswith(".")
                    or name.lower() in EXCLUDED_DIRS
                    or Path(name).suffix.lower() in EXCLUDED_DIRECTORY_SUFFIXES
                ):
                    continue
                candidate = current_path / name
                relative_path = candidate.relative_to(root).as_posix()
                relative_parts = PurePosixPath(relative_path).parts
                if any(
                    relative_parts[:len(prefix.parts)] == prefix.parts
                    for prefix in prefixes
                ):
                    continue
                try:
                    resolved = candidate.resolve()
                except (OSError, RuntimeError) as error:
                    error_records.append(self._enumeration_error(error, relative_path))
                    continue
                if resolved in excluded:
                    continue
                included_directories.append(name)
            directories[:] = included_directories
            for name in files:
                if name.startswith("."):
                    continue
                path = current_path / name
                media_type = EXTENSION_TYPES.get(path.suffix.lower())
                if not media_type:
                    continue
                try:
                    resolved = path.resolve(strict=True)
                except OSError as error:
                    error_records.append(self._enumeration_error(
                        error, path.relative_to(root).as_posix()
                    ))
                    continue
                try:
                    resolved.relative_to(root)
                except ValueError:
                    # 指向登记来源外部的符号链接是明确扫描排除，不是读取失败。
                    continue
                yield MediaFile(
                    path=path,
                    relative_path=path.relative_to(root).as_posix(),
                    media_type=media_type,
                )

    def sync_source(
        self,
        database: LibraryDatabase,
        source_id: str,
        progress: Optional[Callable[[Dict[str, int]], None]] = None,
        scan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        source = database.get_source(source_id)
        try:
            root = Path(source["root_path"]).resolve()
            root_is_directory = root.is_dir()
        except OSError as error:
            status = "permission_required" if isinstance(error, PermissionError) else "scan_failed"
            result = {
                "found": 0, "processed": 0, "failed": 1, "missing": 0,
                "proposed_missing": 0, "commit_status": "skipped",
                "enumeration_errors": [{"path": ".", "status": status, "message": str(error)}],
            }
            database.set_source_status(source_id, status, scanned=True)
            if scan_id:
                database.save_scan_missing_candidates(scan_id, [], commit_status="skipped")
                database.update_scan(scan_id, **result)
            return result
        if not root_is_directory:
            result = {
                "found": 0, "processed": 0, "failed": 1, "missing": 0,
                "proposed_missing": 0, "commit_status": "skipped",
                "enumeration_errors": [{"path": ".", "status": "scan_failed", "message": "登记来源目录不存在或不是目录"}],
            }
            database.set_source_status(source_id, "scan_failed", scanned=True)
            if scan_id:
                database.save_scan_missing_candidates(scan_id, [], commit_status="skipped")
                database.update_scan(scan_id, **result)
            return result
        database.set_source_status(source_id, "scanning")
        found = processed = failed = 0
        recorded_file_failures = 0
        seen_ids = []
        available_at_scan_start = database.count_available_assets(source_id)
        nested_sources = []
        enumeration_errors: List[Dict[str, str]] = []
        for other in database.list_sources():
            if other["id"] == source_id or not other.get("enabled", True):
                continue
            try:
                other_root = Path(other["root_path"]).resolve()
            except OSError as error:
                enumeration_errors.append(self._enumeration_error(error))
                continue
            try:
                relative = other_root.relative_to(root)
            except ValueError:
                continue
            if relative.parts:
                nested_sources.append(other_root)
        for item in self.walk(
            root,
            excluded_roots=iter(nested_sources),
            excluded_relative_prefixes=source.get("excluded_relative_prefixes", ()),
            errors=enumeration_errors,
        ):
            found += 1
            try:
                stat = item.path.stat()
                existing = database.get_asset_scan_state(source_id, item.relative_path)
                if (
                    existing
                    and not existing["is_missing"]
                    and int(existing["size"]) == int(stat.st_size)
                    and float(existing["modified_at"]) == float(stat.st_mtime)
                ):
                    seen_ids.append(str(existing["id"]))
                    processed += 1
                    if progress:
                        progress({"found": found, "processed": processed, "failed": failed, "missing": 0})
                    continue
                metadata = self.probe(item.path, item.media_type)
                if not isinstance(metadata, dict):
                    raise ValueError("媒体解析结果不是对象")
                if metadata.get("probe_error"):
                    raise OSError(str(metadata["probe_error"]))
                asset_id = database.upsert_asset(
                    source_id,
                    item.relative_path,
                    item.media_type,
                    stat,
                    metadata,
                    fingerprint=quick_fingerprint(item.path),
                )
                seen_ids.append(asset_id)
                processed += 1
            except Exception as error:
                failed += 1
                recorded_file_failures += 1
                enumeration_errors.append(self._enumeration_error(error, item.relative_path))
            if progress:
                progress({"found": found, "processed": processed, "failed": failed, "missing": 0})
        proposed_ids = database.list_unseen_available_asset_ids(source_id, seen_ids)
        proposed_missing = len(proposed_ids)
        try:
            directory_is_empty = not any(root.iterdir())
        except OSError as error:
            enumeration_errors.append({
                "path": ".",
                "status": "permission_required" if isinstance(error, PermissionError) else "scan_failed",
                "message": str(error),
            })
            directory_is_empty = False
        if enumeration_errors:
            commit_status = "skipped"
            missing = 0
            source_status = (
                "permission_required"
                if any(item["status"] == "permission_required" for item in enumeration_errors)
                else "scan_failed"
            )
        elif (
            not directory_is_empty
            and (
                proposed_missing > 100
                or (available_at_scan_start > 0 and proposed_missing * 2 >= available_at_scan_start)
            )
        ):
            commit_status = "review_required"
            missing = 0
            source_status = "needs_review"
        else:
            commit_status = "committed"
            missing = database.mark_unseen_missing(source_id, seen_ids)
            source_status = "ready" if failed == 0 else "needs_review"
        if scan_id:
            database.save_scan_missing_candidates(scan_id, proposed_ids, commit_status=commit_status)
        database.set_source_status(source_id, source_status, scanned=True)
        result = {
            "found": found,
            "processed": processed,
            "failed": failed + len(enumeration_errors) - recorded_file_failures,
            "missing": missing,
            "proposed_missing": proposed_missing,
            "commit_status": commit_status,
            "enumeration_errors": enumeration_errors,
        }
        if scan_id:
            database.update_scan(scan_id, **result)
        if progress:
            progress(result)
        return result
