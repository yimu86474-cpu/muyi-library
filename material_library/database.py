import hashlib
import json
import math
import re
from .postgres import connect
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

from .naming import readable_display_name
from .capture_store import (
    CaptureStore, CAPTURE_PREVIEW_STATES, DOUYIN_MEDIA_HOST_SUFFIXES,
    _trusted_capture_media_host, _xiaohongshu_note_id, _has_xiaohongshu_access_params,
    _preferred_capture_page_url,
)
from .library_schema import DEFAULT_CATEGORIES, initialize_library
from .storage_support import _json, _now, synchronized


# Explanation contract: docs/EXPLAIN.md
ASSET_LIFECYCLE_STAGES = (
    "needs_review",
    "source",
    "process",
    "candidate",
    "approved",
    "cleanup",
)


def _normalize_folder(value: str) -> str:
    raw = str(value or "").strip().strip("/")
    if not raw:
        return ""
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("项目文件夹路径不合法")
    return "/".join(path.parts)


def _folder_display_sort_key(item: Dict[str, Any]):
    name = str(item.get("name") or "")
    leading_number = re.match(r"^(\d+)", name)
    if leading_number:
        return (0, -int(leading_number.group(1)), name.casefold())
    return (1, -int(item.get("asset_count") or 0), name.casefold())


class LibraryDatabase(CaptureStore):
    def __init__(self, path: Path, *, dsn=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if dsn is None and self.path.resolve() != (Path(__file__).resolve().parents[1]/'runtime/library.sqlite'):
            raise ValueError('Non-production runtime requires an explicit PostgreSQL DSN')
        super().__init__(connect(dsn), threading.RLock())

    def close(self) -> None:
        self.connection.close()

    def initialize(self) -> None:
        initialize_library(self.connection, self.lock)

    def _source_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "root_path": row["root_path"],
            "default_category": row["default_category"],
            "enabled": bool(row["enabled"]),
            "status": row["status"],
            "excluded_relative_prefixes": json.loads(row["excluded_relative_prefixes_json"] or "[]"),
            "last_scan_at": row["last_scan_at"],
        }

    def add_source(
        self,
        name: str,
        root_path: Path,
        default_category: Optional[str] = None,
        excluded_relative_prefixes: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        root = str(Path(root_path).expanduser().resolve())
        source_id = hashlib.sha256(root.encode("utf-8")).hexdigest()[:24]
        prefixes = self._normalize_excluded_relative_prefixes(excluded_relative_prefixes or ())
        with self.lock, self.connection.transaction():
            self.connection.execute(
                """
                INSERT INTO sources(id, name, root_path, default_category, excluded_relative_prefixes_json, created_at)
                VALUES(%s, %s, %s, %s, %s, %s)
                ON CONFLICT(root_path) DO UPDATE SET
                    name=excluded.name,
                    default_category=COALESCE(excluded.default_category, sources.default_category),
                    excluded_relative_prefixes_json=excluded.excluded_relative_prefixes_json,
                    enabled=1
                """,
                (source_id, name.strip() or Path(root).name, root, default_category, _json(prefixes), _now()),
            )
        return self.get_source(source_id)

    @staticmethod
    def _normalize_excluded_relative_prefixes(values: Iterable[str]) -> List[str]:
        normalized = []
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
            normalized.append("/".join(parts))
        return list(dict.fromkeys(normalized))

    def set_source_excluded_relative_prefixes(
        self, source_id: str, excluded_relative_prefixes: Iterable[str]
    ) -> None:
        prefixes = self._normalize_excluded_relative_prefixes(excluded_relative_prefixes)
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "UPDATE sources SET excluded_relative_prefixes_json=%s WHERE id=%s",
                (_json(prefixes), source_id),
            )

    @synchronized
    def get_source(self, source_id: str) -> Dict[str, Any]:
        row = self.connection.execute("SELECT * FROM sources WHERE id=%s", (source_id,)).fetchone()
        if row is None:
            raise KeyError(source_id)
        return self._source_dict(row)

    @synchronized
    def list_sources(self) -> List[Dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM sources ORDER BY created_at").fetchall()
        return [self._source_dict(row) for row in rows]

    def set_source_status(self, source_id: str, status: str, scanned: bool = False) -> None:
        with self.lock, self.connection.transaction():
            if scanned:
                self.connection.execute(
                    "UPDATE sources SET status=%s, last_scan_at=%s WHERE id=%s",
                    (status, _now(), source_id),
                )
            else:
                self.connection.execute(
                    "UPDATE sources SET status=%s WHERE id=%s", (status, source_id)
                )

    def remove_source(self, source_id: str) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute("DELETE FROM sources WHERE id=%s", (source_id,))

    @synchronized
    def list_categories(self) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT c.name, c.sort_order,
                COUNT(DISTINCT CASE
                    WHEN a.is_missing=0 AND ac.status='confirmed' THEN ac.asset_id
                END) AS count,
                COUNT(DISTINCT CASE
                    WHEN a.is_missing=0 AND ac.status='candidate' THEN ac.asset_id
                END) AS candidate_count
            FROM categories c
            LEFT JOIN asset_categories ac
                ON ac.category_name=c.name
            LEFT JOIN assets a ON a.id=ac.asset_id
            GROUP BY c.name, c.sort_order
            ORDER BY c.sort_order
            """
        ).fetchall()
        return [dict(row) for row in rows]


    def upsert_asset(
        self,
        source_id: str,
        relative_path: str,
        media_type: str,
        stat: Any,
        metadata: Dict[str, Any],
        fingerprint: Optional[str] = None,
    ) -> str:
        source = self.get_source(source_id)
        candidate = Path(source["root_path"]) / relative_path
        resolved = candidate.resolve()
        path_hash = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
        asset_id = path_hash[:32]
        width = metadata.get("width")
        height = metadata.get("height")
        orientation = metadata.get("orientation")
        if not orientation and width and height:
            orientation = "vertical" if height > width else "horizontal" if width > height else "square"
        now = _now()
        display_name = readable_display_name(relative_path, media_type)
        with self.lock, self.connection.transaction():
            existing = self.connection.execute(
                "SELECT id FROM assets WHERE real_path_hash=%s", (path_hash,)
            ).fetchone()
            if existing and existing["id"] != asset_id:
                return str(existing["id"])
            self.connection.execute(
                """
                INSERT INTO assets(
                    id, source_id, relative_path, real_path_hash, fingerprint, media_type, extension,
                    size, modified_at, duration, width, height, orientation, has_audio,
                    metadata_json, is_missing, display_name, display_name_source,
                    display_name_status, created_at, updated_at
                ) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, 'filename_rule', 'derived', %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    source_id=excluded.source_id,
                    relative_path=excluded.relative_path,
                    fingerprint=excluded.fingerprint,
                    content_hash=CASE
                        WHEN assets.size=excluded.size AND assets.modified_at=excluded.modified_at
                        THEN assets.content_hash ELSE NULL END,
                    content_hash_error=CASE
                        WHEN assets.size=excluded.size AND assets.modified_at=excluded.modified_at
                        THEN assets.content_hash_error ELSE NULL END,
                    media_type=excluded.media_type,
                    extension=excluded.extension,
                    size=excluded.size,
                    modified_at=excluded.modified_at,
                    duration=excluded.duration,
                    width=excluded.width,
                    height=excluded.height,
                    orientation=excluded.orientation,
                    has_audio=excluded.has_audio,
                    metadata_json=excluded.metadata_json,
                    is_missing=0,
                    trashed_at=NULL,
                    updated_at=excluded.updated_at
                """,
                (
                    asset_id,
                    source_id,
                    relative_path,
                    path_hash,
                    fingerprint,
                    media_type,
                    candidate.suffix.lower(),
                    int(stat.st_size),
                    float(stat.st_mtime),
                    metadata.get("duration"),
                    width,
                    height,
                    orientation,
                    None if metadata.get("has_audio") is None else int(bool(metadata.get("has_audio"))),
                    _json(metadata),
                    display_name,
                    now,
                    now,
                ),
            )
            if media_type == "audio":
                self.set_category(asset_id, "音频素材", "rule", "confirmed", "文件类型为音频")
            elif source.get("default_category"):
                self.set_category(
                    asset_id,
                    str(source["default_category"]),
                    "rule",
                    "confirmed",
                    "来源预设用途",
                )
            else:
                self.set_category(asset_id, "待分类", "rule", "confirmed", "新素材等待确认用途")
        return asset_id

    def mark_unseen_missing(self, source_id: str, seen_ids: Iterable[str]) -> int:
        seen = list(seen_ids)
        with self.lock, self.connection.transaction():
            if seen:
                placeholders = ",".join("%s" for _ in seen)
                query = (
                    "UPDATE assets SET is_missing=1, updated_at=%s "
                    f"WHERE source_id=%s AND id NOT IN ({placeholders}) AND is_missing=0"
                )
                cursor = self.connection.execute(query, (_now(), source_id, *seen))
            else:
                cursor = self.connection.execute(
                    "UPDATE assets SET is_missing=1, updated_at=%s WHERE source_id=%s AND is_missing=0",
                    (_now(), source_id),
                )
        return int(cursor.rowcount)

    @synchronized
    def list_unseen_available_asset_ids(self, source_id: str, seen_ids: Iterable[str]) -> List[str]:
        seen = list(seen_ids)
        if seen:
            placeholders = ",".join("%s" for _ in seen)
            rows = self.connection.execute(
                "SELECT id FROM assets WHERE source_id=%s AND is_missing=0 AND id NOT IN ({})".format(placeholders),
                (source_id, *seen),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT id FROM assets WHERE source_id=%s AND is_missing=0", (source_id,)
            ).fetchall()
        return [str(row["id"]) for row in rows]

    @synchronized
    def count_available_assets(self, source_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM assets WHERE source_id=%s AND is_missing=0", (source_id,)
        ).fetchone()
        return int(row["count"])

    def save_scan_missing_candidates(
        self, scan_id: str, asset_ids: Iterable[str], commit_status: str = "review_required"
    ) -> None:
        candidates = list(dict.fromkeys(asset_ids))
        if commit_status not in ("skipped", "review_required", "committed"):
            raise ValueError("扫描提交状态不合法")
        with self.lock, self.connection.transaction():
            scan = self.connection.execute(
                "SELECT source_id FROM scans WHERE id=%s", (scan_id,)
            ).fetchone()
            if scan is None:
                raise KeyError(scan_id)
            candidate_token = hashlib.sha256(
                (str(scan["source_id"]) + "\0" + "\0".join(sorted(candidates))).encode("utf-8")
            ).hexdigest()
            self.connection.execute("DELETE FROM scan_missing_candidates WHERE scan_id=%s", (scan_id,))
            with self.connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO scan_missing_candidates(scan_id, asset_id) VALUES(%s, %s)",
                    [(scan_id, asset_id) for asset_id in candidates],
                )
            self.connection.execute(
                "UPDATE scans SET proposed_missing=%s, commit_status=%s, missing_candidate_token=%s WHERE id=%s",
                (len(candidates), commit_status, candidate_token, scan_id),
            )

    @synchronized
    def count_scan_missing_candidates(self, scan_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM scan_missing_candidates WHERE scan_id=%s", (scan_id,)
        ).fetchone()
        return int(row["count"])

    def confirm_scan_missing(self, scan_id: str) -> Dict[str, Any]:
        with self.lock, self.connection.transaction():
            scan = self.connection.execute(
                """
                SELECT sc.scan_order AS scan_rowid, sc.source_id, sc.status AS scan_status,
                       sc.commit_status, sc.proposed_missing,
                       sc.missing_candidate_token, sc.started_at,
                       s.root_path, s.status AS source_status, s.enabled AS source_enabled
                FROM scans sc JOIN sources s ON s.id=sc.source_id
                WHERE sc.id=%s
                """,
                (scan_id,),
            ).fetchone()
            if scan is None:
                raise KeyError(scan_id)
            if scan["commit_status"] != "review_required":
                raise ValueError("这次扫描不需要确认拟失效清单")
            if scan["scan_status"] != "completed":
                raise ValueError("这份拟失效清单尚未完成，当前不能确认")
            newer = self.connection.execute(
                """
                SELECT 1 FROM scans
                WHERE source_id=%s AND (
                    started_at > %s OR (started_at = %s AND scan_order > %s)
                )
                LIMIT 1
                """,
                (scan["source_id"], scan["started_at"], scan["started_at"], scan["scan_rowid"]),
            ).fetchone()
            if newer is not None:
                raise ValueError("这份拟失效清单已过期：该来源已有更新扫描")
            if not bool(scan["source_enabled"]) or scan["source_status"] != "needs_review":
                raise ValueError("这份拟失效清单已过期：来源状态已发生变化")
            candidates = self.connection.execute(
                """
                SELECT a.id, a.source_id, a.relative_path, a.is_missing
                FROM scan_missing_candidates c
                JOIN assets a ON a.id=c.asset_id
                WHERE c.scan_id=%s
                ORDER BY a.id
                """,
                (scan_id,),
            ).fetchall()
            candidate_ids = [str(row["id"]) for row in candidates]
            current_token = hashlib.sha256(
                (str(scan["source_id"]) + "\0" + "\0".join(sorted(candidate_ids))).encode("utf-8")
            ).hexdigest()
            if (
                not candidates
                or len(candidates) != int(scan["proposed_missing"])
                or not scan["missing_candidate_token"]
                or current_token != scan["missing_candidate_token"]
                or any(
                    row["source_id"] != scan["source_id"] or bool(row["is_missing"])
                    for row in candidates
                )
            ):
                raise ValueError("这份拟失效清单已过期：候选集已发生变化")
            try:
                root = Path(scan["root_path"]).resolve(strict=True)
            except OSError:
                raise ValueError("这份拟失效清单已过期：来源当前无法完整校验")
            for candidate in candidates:
                relative_path = candidate["relative_path"]
                parts = relative_path.split("/") if isinstance(relative_path, str) else []
                normalized = PurePosixPath(relative_path) if isinstance(relative_path, str) else None
                if (
                    not relative_path
                    or normalized is None
                    or normalized.is_absolute()
                    or any(part in ("", ".", "..") for part in parts)
                ):
                    raise ValueError("这份拟失效清单已过期：候选相对路径不安全")
                path = root.joinpath(*parts)
                try:
                    resolved = path.resolve(strict=True)
                    resolved.relative_to(root)
                except FileNotFoundError:
                    continue
                except (OSError, ValueError):
                    raise ValueError("这份拟失效清单已过期：候选路径当前无法安全校验")
                raise ValueError(
                    "这份拟失效清单已过期：{} 已恢复或发生变化".format(
                        candidate["relative_path"]
                    )
                )
            cursor = self.connection.execute(
                """
                UPDATE assets SET is_missing=1, updated_at=%s
                WHERE is_missing=0 AND id IN (
                    SELECT asset_id FROM scan_missing_candidates WHERE scan_id=%s
                )
                """,
                (_now(), scan_id),
            )
            self.connection.execute(
                "UPDATE scans SET missing=%s, commit_status='committed' WHERE id=%s",
                (int(cursor.rowcount), scan_id),
            )
            self.connection.execute(
                "UPDATE sources SET status='ready', last_scan_at=%s WHERE id=%s",
                (_now(), scan["source_id"]),
            )
        return {"committed": int(cursor.rowcount), "message": "已确认拟失效清单，仅更新素材库索引"}

    def recover_missing_assets(self, source_id: str = "", dry_run: bool = True) -> Dict[str, Any]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT a.id, a.source_id, a.relative_path, a.size, a.modified_at, s.root_path
                FROM assets a JOIN sources s ON s.id=a.source_id
                WHERE a.is_missing=1 {} ORDER BY a.relative_path
                """.format("AND a.source_id=%s" if source_id else ""),
                (source_id,) if source_id else (),
            ).fetchall()
        eligible, rejected = [], []
        for row in rows:
            root = Path(row["root_path"]).resolve()
            candidate = root / row["relative_path"]
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
                stat = resolved.stat()
            except (FileNotFoundError, OSError, ValueError):
                rejected.append({"id": row["id"], "relative_path": row["relative_path"], "reason": "原路径不存在或已离开登记来源"})
                continue
            if not resolved.is_file() or int(stat.st_size) != int(row["size"]) or float(stat.st_mtime) != float(row["modified_at"]):
                rejected.append({"id": row["id"], "relative_path": row["relative_path"], "reason": "文件大小或修改时间与索引不一致"})
                continue
            eligible.append(str(row["id"]))
        restored = 0
        if not dry_run and eligible:
            with self.lock, self.connection.transaction():
                placeholders = ",".join("%s" for _ in eligible)
                fresh_rows = self.connection.execute(
                    """
                    SELECT a.id, a.relative_path, a.size, a.modified_at, s.root_path
                    FROM assets a JOIN sources s ON s.id=a.source_id
                    WHERE a.is_missing=1 AND a.id IN ({})
                    """.format(placeholders),
                    eligible,
                ).fetchall()
                verified_ids = []
                for row in fresh_rows:
                    root = Path(row["root_path"]).resolve()
                    candidate = root / row["relative_path"]
                    try:
                        resolved = candidate.resolve(strict=True)
                        resolved.relative_to(root)
                        stat = resolved.stat()
                    except (FileNotFoundError, OSError, ValueError):
                        rejected.append({"id": row["id"], "relative_path": row["relative_path"], "reason": "提交前原路径不存在或已离开登记来源"})
                        continue
                    if not resolved.is_file() or int(stat.st_size) != int(row["size"]) or float(stat.st_mtime) != float(row["modified_at"]):
                        rejected.append({"id": row["id"], "relative_path": row["relative_path"], "reason": "提交前文件大小或修改时间已变化"})
                        continue
                    verified_ids.append(str(row["id"]))
                if verified_ids:
                    verified_placeholders = ",".join("%s" for _ in verified_ids)
                    cursor = self.connection.execute(
                        "UPDATE assets SET is_missing=0, updated_at=%s WHERE is_missing=1 AND id IN ({})".format(verified_placeholders),
                        (_now(), *verified_ids),
                    )
                    restored = int(cursor.rowcount)
        return {
            "dry_run": bool(dry_run),
            "would_restore": len(eligible),
            "restored": restored,
            "rejected": rejected,
            "message": "仅审计索引，未修改原文件" if dry_run else "已恢复匹配索引的误失效记录，未修改原文件",
        }

    def relocate_asset(
        self,
        asset_id: str,
        source_id: str,
        relative_path: str,
        media_type: str,
        stat: Any,
        metadata: Dict[str, Any],
        fingerprint: Optional[str] = None,
    ) -> None:
        source = self.get_source(source_id)
        root = Path(source["root_path"]).resolve()
        candidate = (root / relative_path).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("新位置不在登记来源内") from error
        path_hash = hashlib.sha256(str(candidate).encode("utf-8")).hexdigest()
        with self.lock, self.connection.transaction():
            conflict = self.connection.execute(
                "SELECT id FROM assets WHERE real_path_hash=%s AND id<>%s", (path_hash, asset_id)
            ).fetchone()
            if conflict:
                raise ValueError("新位置已经是另一条素材，未自动合并")
            width = metadata.get("width")
            height = metadata.get("height")
            orientation = metadata.get("orientation")
            if not orientation and width and height:
                orientation = "vertical" if height > width else "horizontal" if width > height else "square"
            cursor = self.connection.execute(
                """
                UPDATE assets SET
                    source_id=%s, relative_path=%s, real_path_hash=%s, fingerprint=%s,
                    media_type=%s, extension=%s, size=%s, modified_at=%s, duration=%s,
                    width=%s, height=%s, orientation=%s, has_audio=%s, metadata_json=%s,
                    is_missing=0, preview_status='pending', thumbnail_status='pending', updated_at=%s
                WHERE id=%s
                """,
                (
                    source_id, relative_path, path_hash, fingerprint, media_type,
                    candidate.suffix.lower(), int(stat.st_size), float(stat.st_mtime),
                    metadata.get("duration"), width, height, orientation,
                    None if metadata.get("has_audio") is None else int(bool(metadata.get("has_audio"))),
                    _json(metadata), _now(), asset_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(asset_id)

    def remove_asset(self, asset_id: str) -> None:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute("DELETE FROM assets WHERE id=%s", (asset_id,))
            if cursor.rowcount == 0:
                raise KeyError(asset_id)

    def mark_asset_trashed(self, asset_id: str) -> None:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE assets SET is_missing=1, trashed_at=%s, updated_at=%s "
                "WHERE id=%s AND is_missing=0",
                (_now(), _now(), asset_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(asset_id)

    def _asset_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        asset_id = row["id"]
        tags = [
            item["tag"]
            for item in self.connection.execute(
                "SELECT tag FROM asset_tags WHERE asset_id=%s ORDER BY tag", (asset_id,)
            ).fetchall()
        ]
        candidate_tags = [
            dict(item)
            for item in self.connection.execute(
                "SELECT tag, evidence, source_ref FROM asset_tag_candidates WHERE asset_id=%s ORDER BY tag",
                (asset_id,),
            ).fetchall()
        ]
        categories = [
            dict(item)
            for item in self.connection.execute(
                """
                SELECT category_name AS name, source_type, status, evidence, prompt_version
                FROM asset_categories WHERE asset_id=%s
                ORDER BY CASE status WHEN 'confirmed' THEN 0 ELSE 1 END, category_name
                """,
                (asset_id,),
            ).fetchall()
        ]
        collection_ids = [
            item["collection_id"]
            for item in self.connection.execute(
                "SELECT collection_id FROM collection_assets WHERE asset_id=%s ORDER BY sort_order",
                (asset_id,),
            ).fetchall()
        ]
        latest_job = self.connection.execute(
            "SELECT status, error FROM classification_jobs WHERE asset_id=%s ORDER BY created_at DESC LIMIT 1",
            (asset_id,),
        ).fetchone()
        result = dict(row)
        result["favorite"] = bool(result["favorite"])
        result["is_missing"] = bool(result["is_missing"])
        result["is_trashed"] = result.get("trashed_at") is not None
        result["has_audio"] = None if result["has_audio"] is None else bool(result["has_audio"])
        result["tags"] = tags
        result["candidate_tags"] = candidate_tags
        result["categories"] = categories
        result["collection_ids"] = collection_ids
        result["classification_status"] = latest_job["status"] if latest_job else "not_started"
        result["classification_error"] = latest_job["error"] if latest_job else None
        if result.get("fingerprint"):
            duplicate_row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM assets WHERE fingerprint=%s AND id<>%s",
                (result["fingerprint"], asset_id),
            ).fetchone()
            result["suspected_duplicate_count"] = int(duplicate_row["count"])
        else:
            result["suspected_duplicate_count"] = 0
        if result.get("content_hash"):
            exact_row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM assets "
                "WHERE content_hash=%s AND id<>%s AND is_missing=0",
                (result["content_hash"], asset_id),
            ).fetchone()
            result["exact_duplicate_count"] = int(exact_row["count"])
        else:
            result["exact_duplicate_count"] = 0
        result.pop("real_path_hash", None)
        result.pop("fingerprint", None)
        result.pop("content_hash", None)
        result.pop("content_hash_error", None)
        result.pop("metadata_json", None)
        result.pop("trashed_at", None)
        result.pop("root_path", None)
        result.pop("duplicate_rank", None)
        return result

    def set_content_hash(
        self, asset_id: str, content_hash: Optional[str], error: Optional[str] = None
    ) -> None:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE assets SET content_hash=%s, content_hash_error=%s, updated_at=%s WHERE id=%s",
                (content_hash, error[:1000] if error else None, _now(), asset_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(asset_id)

    @synchronized
    def list_duplicate_group(self, asset_id: str) -> List[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT content_hash FROM assets WHERE id=%s", (asset_id,)
        ).fetchone()
        if row is None:
            raise KeyError(asset_id)
        if not row["content_hash"]:
            return []
        rows = self.connection.execute(
            """
            SELECT a.*, s.name AS source_name
            FROM assets a JOIN sources s ON s.id=a.source_id
            WHERE a.content_hash=%s AND a.is_missing=0
            ORDER BY a.modified_at DESC, a.relative_path
            """,
            (row["content_hash"],),
        ).fetchall()
        return [self._asset_dict(item) for item in rows]

    @synchronized
    def list_duplicate_verification_candidates(self) -> List[str]:
        rows = self.connection.execute(
            """
            SELECT a.id
            FROM assets a
            WHERE a.is_missing=0
              AND a.fingerprint IS NOT NULL
              AND a.content_hash IS NULL
              AND a.content_hash_error IS NULL
              AND EXISTS (
                  SELECT 1 FROM assets b
                  WHERE b.id<>a.id AND b.is_missing=0
                    AND b.fingerprint=a.fingerprint
              )
            ORDER BY a.size, a.id
            """
        ).fetchall()
        return [str(row["id"]) for row in rows]

    @synchronized
    def duplicate_summary(self) -> Dict[str, int]:
        candidate_row = self.connection.execute(
            """
            SELECT
                COUNT(*) AS suspect_assets,
                SUM(CASE WHEN a.content_hash IS NULL AND a.content_hash_error IS NULL THEN 1 ELSE 0 END)
                    AS pending_assets,
                SUM(CASE WHEN a.content_hash IS NOT NULL THEN 1 ELSE 0 END) AS verified_assets,
                SUM(CASE WHEN a.content_hash_error IS NOT NULL THEN 1 ELSE 0 END) AS failed_assets
            FROM assets a
            WHERE a.is_missing=0 AND a.fingerprint IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM assets b
                  WHERE b.id<>a.id AND b.is_missing=0 AND b.fingerprint=a.fingerprint
              )
            """
        ).fetchone()
        group_row = self.connection.execute(
            """
            SELECT COUNT(*) AS exact_groups,
                   COALESCE(SUM(copies - 1), 0) AS hidden_copies,
                   COALESCE(SUM((copies - 1) * size), 0) AS reclaimable_bytes
            FROM (
                SELECT content_hash, COUNT(*) AS copies, MAX(size) AS size
                FROM assets
                WHERE is_missing=0 AND content_hash IS NOT NULL
                GROUP BY content_hash HAVING COUNT(*)>1
            )
            """
        ).fetchone()
        return {
            "suspect_assets": int(candidate_row["suspect_assets"] or 0),
            "pending_assets": int(candidate_row["pending_assets"] or 0),
            "verified_assets": int(candidate_row["verified_assets"] or 0),
            "failed_assets": int(candidate_row["failed_assets"] or 0),
            "exact_groups": int(group_row["exact_groups"] or 0),
            "hidden_copies": int(group_row["hidden_copies"] or 0),
            "reclaimable_bytes": int(group_row["reclaimable_bytes"] or 0),
        }

    @synchronized
    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT a.*, s.name AS source_name
            FROM assets a JOIN sources s ON s.id=a.source_id WHERE a.id=%s
            """,
            (asset_id,),
        ).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return self._asset_dict(row)

    @synchronized
    def get_asset_record(self, asset_id: str) -> Dict[str, Any]:
        row = self.connection.execute("SELECT * FROM assets WHERE id=%s", (asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        return row

    @synchronized
    def get_asset_scan_state(self, source_id: str, relative_path: str) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT id, size, modified_at, is_missing FROM assets "
            "WHERE source_id=%s AND relative_path=%s",
            (source_id, relative_path),
        ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _normalize_asset_lifecycle_stage(stage: str) -> str:
        value = str(stage or "").strip()
        if value not in ASSET_LIFECYCLE_STAGES:
            raise ValueError("素材状态必须是已登记的六种状态之一")
        return value

    def set_asset_lifecycle_stage(self, asset_id: str, stage: str) -> None:
        self.set_assets_lifecycle_stage([asset_id], stage)

    def set_assets_lifecycle_stage(self, asset_ids: Iterable[str], stage: str) -> int:
        lifecycle_stage = self._normalize_asset_lifecycle_stage(stage)
        clean_ids = list(dict.fromkeys(str(asset_id) for asset_id in asset_ids if str(asset_id)))
        if not clean_ids:
            raise ValueError("至少选择一条素材")
        placeholders = ",".join("%s" for _item in clean_ids)
        with self.lock, self.connection.transaction():
            rows = self.connection.execute(
                "SELECT id FROM assets WHERE id IN ({})".format(placeholders), clean_ids
            ).fetchall()
            found = {row["id"] for row in rows}
            missing = next((asset_id for asset_id in clean_ids if asset_id not in found), None)
            if missing is not None:
                raise KeyError(missing)
            self.connection.execute(
                "UPDATE assets SET lifecycle_stage=%s, updated_at=%s "
                "WHERE id IN ({})".format(placeholders),
                [lifecycle_stage, _now(), *clean_ids],
            )
        return len(clean_ids)

    @synchronized
    def list_lifecycle_stages(
        self, availability: str = "available", media_type: str = ""
    ) -> List[Dict[str, Any]]:
        if availability not in ("available", "missing", "all"):
            raise ValueError("可用性必须是 available、missing 或 all")
        clauses = ["trashed_at IS NULL"]
        params: List[Any] = []
        if availability == "available":
            clauses.append("is_missing=0")
        elif availability == "missing":
            clauses.append("is_missing=1")
        if media_type:
            clauses.append("media_type=%s")
            params.append(str(media_type))
        rows = self.connection.execute(
            "SELECT lifecycle_stage, COUNT(*) AS count FROM assets WHERE {} "
            "GROUP BY lifecycle_stage".format(" AND ".join(clauses)),
            params,
        ).fetchall()
        counts = {row["lifecycle_stage"]: int(row["count"]) for row in rows}
        return [{"id": stage, "count": counts.get(stage, 0)} for stage in ASSET_LIFECYCLE_STAGES]

    def _asset_filter_parts(
        self,
        query: str = "",
        media_type: str = "",
        category: str = "",
        collection_id: str = "",
        source_id: str = "",
        orientation: str = "",
        status: str = "",
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
        favorite: Optional[bool] = None,
        folder: str = "",
        folder_scope: str = "recursive",
        availability: str = "all",
        lifecycle_stage: str = "",
    ):
        clauses = ["a.trashed_at IS NULL"]
        params: List[Any] = []
        if folder_scope not in ("recursive", "direct"):
            raise ValueError("文件夹范围必须是 direct 或 recursive")
        if availability not in ("available", "missing", "all"):
            raise ValueError("可用性必须是 available、missing 或 all")
        if availability == "available":
            clauses.append("a.is_missing=0")
        elif availability == "missing":
            clauses.append("a.is_missing=1")
        if lifecycle_stage:
            clauses.append("a.lifecycle_stage=%s")
            params.append(self._normalize_asset_lifecycle_stage(lifecycle_stage))
        if query:
            clauses.append(
                "(a.relative_path LIKE %s OR a.display_name LIKE %s OR a.note LIKE %s OR EXISTS "
                "(SELECT 1 FROM asset_tags t WHERE t.asset_id=a.id AND t.tag LIKE %s))"
            )
            term = "%{}%".format(query)
            params.extend([term, term, term, term])
        if media_type:
            clauses.append("a.media_type=%s")
            params.append(media_type)
        if source_id:
            clauses.append("a.source_id=%s")
            params.append(source_id)
        if folder:
            normalized_folder = _normalize_folder(folder)
            escaped_folder = (
                normalized_folder.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            clauses.append("a.relative_path LIKE %s ESCAPE '\\'")
            params.append(escaped_folder + "/%")
            if folder_scope == "direct":
                clauses.append("strpos(substr(a.relative_path, %s), '/')=0")
                params.append(len(normalized_folder) + 2)
        elif folder_scope == "direct":
            clauses.append("strpos(a.relative_path, '/')=0")
        if orientation:
            clauses.append("a.orientation=%s")
            params.append(orientation)
        if favorite is not None:
            clauses.append("a.favorite=%s")
            params.append(int(favorite))
        if category:
            category_status = "candidate" if status == "candidate" else "confirmed"
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_categories ac WHERE ac.asset_id=a.id "
                "AND ac.category_name=%s AND ac.status=%s)"
            )
            params.extend([category, category_status])
        if collection_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM collection_assets ca "
                "WHERE ca.asset_id=a.id AND ca.collection_id=%s)"
            )
            params.append(collection_id)
        if status == "missing":
            clauses.append("a.is_missing=1")
        elif status == "candidate":
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_categories ac WHERE ac.asset_id=a.id AND ac.status='candidate')"
            )
        elif status == "confirmed":
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_categories ac WHERE ac.asset_id=a.id AND ac.status='confirmed')"
            )
        if date_from is not None:
            clauses.append("a.modified_at>=%s")
            params.append(float(date_from))
        if date_to is not None:
            clauses.append("a.modified_at<%s")
            params.append(float(date_to))
        return clauses, params

    @synchronized
    def list_assets(
        self,
        query: str = "",
        media_type: str = "",
        category: str = "",
        collection_id: str = "",
        source_id: str = "",
        orientation: str = "",
        status: str = "",
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
        favorite: Optional[bool] = None,
        dedupe: bool = False,
        folder: str = "",
        folder_scope: str = "recursive",
        availability: str = "all",
        lifecycle_stage: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        clauses, params = self._asset_filter_parts(
            query, media_type, category, collection_id, source_id, orientation,
            status, date_from, date_to, favorite, folder, folder_scope, availability,
            lifecycle_stage,
        )
        if dedupe:
            sql = """
                SELECT * FROM (
                    SELECT a.*, s.name AS source_name,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(a.content_hash, a.id)
                            ORDER BY a.is_missing, a.modified_at DESC, a.relative_path
                        ) AS duplicate_rank
                    FROM assets a JOIN sources s ON s.id=a.source_id
                    WHERE {}
                ) WHERE duplicate_rank=1
                ORDER BY is_missing, modified_at DESC, relative_path
                LIMIT %s OFFSET %s
            """.format(" AND ".join(clauses))
        else:
            sql = """
                SELECT a.*, s.name AS source_name
                FROM assets a JOIN sources s ON s.id=a.source_id
                WHERE {}
                ORDER BY a.is_missing, a.modified_at DESC, a.relative_path
                LIMIT %s OFFSET %s
            """.format(" AND ".join(clauses))
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        rows = self.connection.execute(sql, params).fetchall()
        return [self._asset_dict(row) for row in rows]

    @synchronized
    def count_assets(
        self,
        query: str = "",
        media_type: str = "",
        category: str = "",
        collection_id: str = "",
        source_id: str = "",
        orientation: str = "",
        status: str = "",
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
        favorite: Optional[bool] = None,
        dedupe: bool = False,
        folder: str = "",
        folder_scope: str = "recursive",
        availability: str = "all",
        lifecycle_stage: str = "",
    ) -> int:
        clauses, params = self._asset_filter_parts(
            query, media_type, category, collection_id, source_id, orientation,
            status, date_from, date_to, favorite, folder, folder_scope, availability,
            lifecycle_stage,
        )
        if dedupe:
            sql = """
                SELECT COUNT(*) AS count FROM (
                    SELECT ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(a.content_hash, a.id)
                        ORDER BY a.is_missing, a.modified_at DESC, a.relative_path
                    ) AS duplicate_rank
                    FROM assets a WHERE {}
                ) WHERE duplicate_rank=1
            """.format(" AND ".join(clauses))
        else:
            sql = "SELECT COUNT(*) AS count FROM assets a WHERE {}".format(
                " AND ".join(clauses)
            )
        row = self.connection.execute(sql, params).fetchone()
        return int(row["count"])

    @synchronized
    def list_asset_folders(
        self, source_id: str = "", parent: str = "", media_type: str = ""
    ) -> List[Dict[str, Any]]:
        normalized_parent = _normalize_folder(parent)
        parent_parts = PurePosixPath(normalized_parent).parts if normalized_parent else ()
        params: List[Any] = []
        clauses = ["a.is_missing=0"]
        if source_id:
            clauses.append("a.source_id=%s")
            params.append(source_id)
        if media_type:
            clauses.append("a.media_type=%s")
            params.append(str(media_type))
        rows = self.connection.execute(
            """
            SELECT a.source_id, s.name AS source_name, a.relative_path
            FROM assets a JOIN sources s ON s.id=a.source_id
            WHERE {}
            ORDER BY s.name, a.relative_path
            """.format(" AND ".join(clauses)),
            params,
        ).fetchall()
        folders: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            parts = PurePosixPath(str(row["relative_path"])).parts
            if len(parts) <= len(parent_parts) + 1:
                continue
            if parent_parts and tuple(parts[: len(parent_parts)]) != tuple(parent_parts):
                continue
            child_name = parts[len(parent_parts)]
            folder_parts = (*parent_parts, child_name)
            folder_path = "/".join(folder_parts)
            key = (str(row["source_id"]), folder_path)
            item = folders.setdefault(
                key,
                {
                    "source_id": str(row["source_id"]),
                    "source_name": str(row["source_name"]),
                    "name": child_name,
                    "path": folder_path,
                    "asset_count": 0,
                    "direct_asset_count": 0,
                    "has_children": False,
                },
            )
            item["asset_count"] += 1
            if len(parts) == len(folder_parts) + 1:
                item["direct_asset_count"] += 1
            elif len(parts) > len(folder_parts) + 1:
                item["has_children"] = True
        return sorted(
            folders.values(),
            key=_folder_display_sort_key,
        )

    def set_favorite(self, asset_id: str, favorite: bool) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "UPDATE assets SET favorite=%s, updated_at=%s WHERE id=%s",
                (int(favorite), _now(), asset_id),
            )

    def update_note(self, asset_id: str, note: str) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "UPDATE assets SET note=%s, updated_at=%s WHERE id=%s", (note, _now(), asset_id)
            )

    def update_display_name(
        self,
        asset_id: str,
        display_name: str,
        source_type: str = "manual",
        status: str = "confirmed",
    ) -> None:
        value = str(display_name).strip()[:160]
        with self.lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT relative_path, media_type FROM assets WHERE id=%s", (asset_id,)
            ).fetchone()
            if row is None:
                raise KeyError(asset_id)
            if not value:
                value = readable_display_name(row["relative_path"], row["media_type"])
                source_type, status = "filename_rule", "derived"
            self.connection.execute(
                "UPDATE assets SET display_name=%s, display_name_source=%s, "
                "display_name_status=%s, updated_at=%s WHERE id=%s",
                (value, source_type, status, _now(), asset_id),
            )

    def add_tag(self, asset_id: str, tag: str) -> None:
        cleaned = tag.strip()
        if not cleaned:
            return
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "INSERT INTO asset_tags(asset_id, tag) VALUES(%s, %s) ON CONFLICT DO NOTHING",
                (asset_id, cleaned[:80]),
            )

    def remove_tag(self, asset_id: str, tag: str) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "DELETE FROM asset_tags WHERE asset_id=%s AND tag=%s", (asset_id, tag)
            )

    def add_tag_candidate(self, asset_id: str, tag: str, evidence: str, source_ref: str) -> None:
        cleaned = tag.strip()
        if not cleaned:
            return
        with self.lock, self.connection.transaction():
            self.connection.execute(
                """
                INSERT INTO asset_tag_candidates(asset_id, tag, evidence, source_ref, created_at)
                VALUES(%s, %s, %s, %s, %s)
                ON CONFLICT(asset_id, tag) DO UPDATE SET
                    evidence=excluded.evidence, source_ref=excluded.source_ref
                """,
                (asset_id, cleaned[:80], evidence[:500], source_ref[:500], _now()),
            )

    def confirm_tag_candidate(self, asset_id: str, tag: str) -> None:
        with self.lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT tag FROM asset_tag_candidates WHERE asset_id=%s AND tag=%s",
                (asset_id, tag),
            ).fetchone()
            if row is None:
                raise KeyError(tag)
            self.connection.execute(
                "INSERT INTO asset_tags(asset_id, tag) VALUES(%s, %s) ON CONFLICT DO NOTHING",
                (asset_id, tag),
            )
            self.connection.execute(
                "DELETE FROM asset_tag_candidates WHERE asset_id=%s AND tag=%s",
                (asset_id, tag),
            )

    @synchronized
    def list_asset_names(self) -> List[Dict[str, str]]:
        rows = self.connection.execute("SELECT id, relative_path FROM assets").fetchall()
        return [dict(row) for row in rows]

    def set_category(
        self,
        asset_id: str,
        category: str,
        source_type: str,
        status: str,
        evidence: str = "",
        prompt_version: Optional[str] = None,
    ) -> None:
        if category not in DEFAULT_CATEGORIES:
            raise ValueError("未知用途分类")
        if source_type not in ("rule", "local_ai", "manual"):
            raise ValueError("未知分类来源")
        if status not in ("candidate", "confirmed", "needs_agent_review"):
            raise ValueError("未知分类状态")
        now = _now()
        with self.lock, self.connection.transaction():
            self.connection.execute(
                """
                INSERT INTO asset_categories(
                    asset_id, category_name, source_type, status, evidence,
                    prompt_version, created_at, updated_at
                ) VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(asset_id, category_name, source_type) DO UPDATE SET
                    status=excluded.status,
                    evidence=excluded.evidence,
                    prompt_version=excluded.prompt_version,
                    updated_at=excluded.updated_at
                """,
                (asset_id, category, source_type, status, evidence, prompt_version, now, now),
            )
            if category != "待分类" and status == "confirmed":
                self.connection.execute(
                    "DELETE FROM asset_categories WHERE asset_id=%s AND category_name='待分类'",
                    (asset_id,),
                )

    def remove_category(self, asset_id: str, category: str) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "DELETE FROM asset_categories WHERE asset_id=%s AND category_name=%s",
                (asset_id, category),
            )

    def remove_category_source(self, asset_id: str, category: str, source_type: str) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "DELETE FROM asset_categories WHERE asset_id=%s AND category_name=%s AND source_type=%s",
                (asset_id, category, source_type),
            )

    def confirm_candidate(self, asset_id: str, category: str) -> None:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                """
                UPDATE asset_categories SET status='confirmed', source_type='manual', updated_at=%s
                WHERE asset_id=%s AND category_name=%s AND status='candidate'
                """,
                (_now(), asset_id, category),
            )
            if cursor.rowcount == 0:
                self.set_category(asset_id, category, "manual", "confirmed", "木易人工确认")
            if category != "待分类":
                self.connection.execute(
                    "DELETE FROM asset_categories WHERE asset_id=%s AND category_name='待分类'",
                    (asset_id,),
                )

    def create_collection(
        self, name: str, asset_ids: Optional[Iterable[str]] = None
    ) -> Dict[str, Any]:
        collection_id = uuid.uuid4().hex[:20]
        clean_name = name.strip()[:100]
        if not clean_name:
            raise ValueError("素材包名称不能为空")
        ids = list(dict.fromkeys(str(item) for item in (asset_ids or [])))
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "INSERT INTO collections(id, name, created_at) VALUES(%s, %s, %s)",
                (collection_id, clean_name, _now()),
            )
            for index, asset_id in enumerate(ids):
                exists = self.connection.execute(
                    "SELECT 1 FROM assets WHERE id=%s", (asset_id,)
                ).fetchone()
                if exists is None:
                    raise KeyError(asset_id)
                self.connection.execute(
                    "INSERT INTO collection_assets(collection_id, asset_id, sort_order) "
                    "VALUES(%s, %s, %s)",
                    (collection_id, asset_id, index),
                )
        return {"id": collection_id, "name": clean_name, "asset_count": len(ids)}

    def enqueue_unclassified_classification_jobs(
        self, limit: Optional[int] = None
    ) -> List[Dict[str, str]]:
        sql = """
            SELECT a.id
            FROM assets a
            WHERE a.is_missing=0
              AND a.media_type IN ('video', 'image')
              AND EXISTS (
                  SELECT 1 FROM asset_categories ac
                  WHERE ac.asset_id=a.id AND ac.category_name='待分类'
                    AND ac.status='confirmed'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM asset_categories ac
                  WHERE ac.asset_id=a.id AND ac.status='candidate'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM classification_jobs j
                  WHERE j.asset_id=a.id AND j.status IN ('queued', 'running')
              )
            ORDER BY a.modified_at DESC, a.id
        """
        params: List[Any] = []
        if limit is not None:
            sql += " LIMIT %s"
            params.append(max(1, int(limit)))
        now = _now()
        jobs = []
        with self.lock, self.connection.transaction():
            rows = self.connection.execute(sql, params).fetchall()
            for row in rows:
                job_id = uuid.uuid4().hex
                self.connection.execute(
                    """
                    INSERT INTO classification_jobs(
                        id, asset_id, status, created_at, updated_at
                    ) VALUES(%s, %s, 'queued', %s, %s)
                    """,
                    (job_id, row["id"], now, now),
                )
                jobs.append({"id": job_id, "asset_id": str(row["id"])})
        return jobs

    def recover_interrupted_classification_jobs(self) -> int:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE classification_jobs SET status='queued', error=NULL, updated_at=%s "
                "WHERE status='running'",
                (_now(),),
            )
        return int(cursor.rowcount)

    def claim_next_classification_job(self) -> Optional[Dict[str, str]]:
        with self.lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT id, asset_id FROM classification_jobs "
                "WHERE status='queued' ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            cursor = self.connection.execute(
                "UPDATE classification_jobs SET status='running', updated_at=%s "
                "WHERE id=%s AND status='queued'",
                (_now(), row["id"]),
            )
            if cursor.rowcount == 0:
                return None
            return {"id": str(row["id"]), "asset_id": str(row["asset_id"])}

    @synchronized
    def classification_status_counts(self) -> Dict[str, int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM classification_jobs GROUP BY status"
        ).fetchall()
        values = {str(row["status"]): int(row["count"]) for row in rows}
        values["queued"] = values.get("queued", 0)
        values["running"] = values.get("running", 0)
        return values

    @synchronized
    def list_collections(self) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT c.id, c.name, COUNT(ca.asset_id) AS asset_count
            FROM collections c LEFT JOIN collection_assets ca ON ca.collection_id=c.id
            GROUP BY c.id, c.name ORDER BY c.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def set_asset_collections(self, asset_id: str, collection_ids: Iterable[str]) -> None:
        ids = list(dict.fromkeys(collection_ids))
        with self.lock, self.connection.transaction():
            self.connection.execute("DELETE FROM collection_assets WHERE asset_id=%s", (asset_id,))
            for index, collection_id in enumerate(ids):
                self.connection.execute(
                    "INSERT INTO collection_assets(collection_id, asset_id, sort_order) VALUES(%s, %s, %s)",
                    (collection_id, asset_id, index),
                )

    def create_scan(self, source_id: str, batch_id: Optional[str] = None) -> str:
        scan_id = uuid.uuid4().hex
        stable_batch_id = batch_id or scan_id
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "INSERT INTO scans(id, batch_id, source_id, status, started_at) VALUES(%s, %s, %s, 'running', %s)",
                (scan_id, stable_batch_id, source_id, _now()),
            )
        return scan_id

    def recover_interrupted_scans(self) -> int:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE scans SET status='failed', error=%s, finished_at=%s WHERE status='running'",
                ("服务重启，上一次扫描任务已中断，本次将重新增量刷新", _now()),
            )
        return int(cursor.rowcount)

    def recover_interrupted_capture_downloads(self) -> int:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE captures SET status='download_failed', target_path=NULL, "
                "failure_reason=%s, updated_at=%s WHERE status='downloading'",
                ("服务重启，上一次本地保存已中断，可以重新保存", _now()),
            )
        return int(cursor.rowcount)

    def recover_interrupted_capture_previews(self) -> int:
        with self.lock, self.connection.transaction():
            cursor = self.connection.execute(
                "UPDATE captures SET media_refresh_status='needs_activation', updated_at=%s "
                "WHERE media_refresh_status='resolving'",
                (_now(),),
            )
        return int(cursor.rowcount)

    def update_scan(self, scan_id: str, **values: Any) -> None:
        allowed = {
            "status", "found", "processed", "failed", "missing", "proposed_missing",
            "commit_status", "error", "finished_at", "enumeration_errors",
        }
        clean = {key: value for key, value in values.items() if key in allowed}
        if not clean:
            return
        if "enumeration_errors" in clean:
            clean["enumeration_errors_json"] = _json(clean.pop("enumeration_errors"))
        with self.lock, self.connection.transaction():
            fields = ", ".join("{}=%s".format(key) for key in clean)
            self.connection.execute(
                "UPDATE scans SET {} WHERE id=%s".format(fields), (*clean.values(), scan_id)
            )

    @synchronized
    def count_running_scans(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM scans WHERE status='running'"
        ).fetchone()
        return int(row["count"])

    @synchronized
    def list_scans(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT sc.*, COALESCE(s.name, '') AS source_name
            FROM scans sc LEFT JOIN sources s ON s.id=sc.source_id
            ORDER BY sc.started_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
        scan_ids = [str(row["id"]) for row in rows]
        candidates_by_scan = {scan_id: [] for scan_id in scan_ids}
        if scan_ids:
            placeholders = ",".join("%s" for _scan_id in scan_ids)
            candidate_rows = self.connection.execute(
                """
                SELECT c.scan_id, a.id AS asset_id, a.relative_path
                FROM scan_missing_candidates c JOIN assets a ON a.id=c.asset_id
                WHERE c.scan_id IN ({})
                ORDER BY c.scan_id, a.relative_path, a.id
                """.format(placeholders),
                scan_ids,
            ).fetchall()
            for candidate in candidate_rows:
                candidates_by_scan[str(candidate["scan_id"])].append({
                    "asset_id": candidate["asset_id"],
                    "relative_path": candidate["relative_path"],
                })
        result = []
        for row in rows:
            item = dict(row)
            item["enumeration_errors"] = json.loads(item.pop("enumeration_errors_json") or "[]")
            item["batch_id"] = item.get("batch_id") or item["id"]
            item.pop("missing_candidate_token", None)
            item["missing_candidates"] = candidates_by_scan[str(item["id"])]
            result.append(item)
        return result

    def create_classification_job(self, asset_id: str, job_id: Optional[str] = None) -> str:
        identifier = job_id or uuid.uuid4().hex
        now = _now()
        with self.lock, self.connection.transaction():
            self.connection.execute(
                """
                INSERT INTO classification_jobs(id, asset_id, status, created_at, updated_at)
                VALUES(%s, %s, 'queued', %s, %s)
                """,
                (identifier, asset_id, now, now),
            )
        return identifier

    def update_classification_job(
        self,
        job_id: str,
        status: str,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                """
                UPDATE classification_jobs
                SET status=%s, error=%s, result_json=%s, updated_at=%s
                WHERE id=%s
                """,
                (status, error, _json(result) if result is not None else None, _now(), job_id),
            )

    @synchronized
    def list_classification_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT j.id, j.asset_id, j.status, j.error, j.created_at, j.updated_at,
                   a.relative_path
            FROM classification_jobs j JOIN assets a ON a.id=j.asset_id
            ORDER BY j.created_at DESC LIMIT %s
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [dict(row) for row in rows]


    @synchronized
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.connection.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        with self.lock, self.connection.transaction():
            self.connection.execute(
                "INSERT INTO settings(key, value) VALUES(%s, %s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
