"""Resource handlers for assets; existing application services own side effects."""
import os
import re
import subprocess
import urllib.parse
from pathlib import Path
from .scanner import EXTENSION_TYPES, probe_media, quick_fingerprint
from .security import resolve_registered_asset, resolve_registered_folder


def list_folders(self, app, parsed, query, match):
    return self._json(
        {
            "items": app.database.list_asset_folders(
                source_id=query.get("source", [""])[0],
                parent=query.get("parent", [""])[0],
                media_type=query.get("type", [""])[0],
            )
        }
    )


def list_assets(self, app, parsed, query, match):
    favorite_value = query.get("favorite", [""])[0]
    folder_scope = query.get("folder_scope", ["recursive"])[0]
    availability_values = urllib.parse.parse_qs(
        parsed.query, keep_blank_values=True
    ).get("availability")
    availability = "all" if availability_values is None else availability_values[0]
    lifecycle_stage_values = urllib.parse.parse_qs(
        parsed.query, keep_blank_values=True
    ).get("lifecycle_stage")
    lifecycle_stage = "" if lifecycle_stage_values is None else lifecycle_stage_values[0]
    if folder_scope not in ("direct", "recursive"):
        raise ValueError("文件夹范围必须是 direct 或 recursive")
    if availability not in ("available", "missing", "all"):
        raise ValueError("可用性必须是 available、missing 或 all")
    if lifecycle_stage_values is not None and not lifecycle_stage:
        raise ValueError("素材状态不能为空")
    asset_filters = dict(
        query=query.get("q", [""])[0], media_type=query.get("type", [""])[0],
        category=query.get("category", [""])[0],
        collection_id=query.get("collection", [""])[0],
        source_id=query.get("source", [""])[0],
        orientation=query.get("orientation", [""])[0],
        status=query.get("status", [""])[0],
        date_from=float(query["date_from"][0]) if query.get("date_from") else None,
        date_to=float(query["date_to"][0]) if query.get("date_to") else None,
        favorite=None if favorite_value == "" else favorite_value == "true",
        dedupe=query.get("dedupe", [""])[0] == "true",
        folder=query.get("folder", [""])[0],
        folder_scope=folder_scope,
        availability=availability,
        lifecycle_stage=lifecycle_stage,
    )
    items = app.database.list_assets(
        **asset_filters,
        limit=int(query.get("limit", [100])[0]),
        offset=int(query.get("offset", [0])[0]),
    )
    total = app.database.count_assets(**asset_filters)
    unfolded_filters = dict(asset_filters)
    unfolded_filters["dedupe"] = False
    unfolded_total = app.database.count_assets(**unfolded_filters)
    return self._json({
        "items": items,
        "count": len(items),
        "total": total,
        "unfolded_total": unfolded_total,
        "hidden_count": max(0, unfolded_total - total),
    })


def recover_missing(self, app, parsed, query, match):
    data = self._body()
    dry_run = data.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run 必须是布尔值")
    return self._json(
        app.database.recover_missing_assets(
            source_id=str(data.get("source_id") or ""), dry_run=dry_run
        )
    )


def set_batch_stage(self, app, parsed, query, match):
    data = self._body()
    asset_ids = data.get("asset_ids")
    if not isinstance(asset_ids, list):
        raise ValueError("asset_ids 必须是数组")
    stage = data.get("stage")
    if not isinstance(stage, str):
        raise ValueError("stage 必须是字符串")
    updated = app.database.set_assets_lifecycle_stage(asset_ids, stage)
    return self._json({"updated": updated, "stage": stage})


def reveal_folder(self, app, parsed, query, match):
    data = self._body()
    folder_path = resolve_registered_folder(
        app.database,
        str(data.get("source_id") or ""),
        str(data.get("folder") or ""),
    )
    if os.name == "nt":
        os.startfile(folder_path)
    else:
        subprocess.run(["open", str(folder_path)], check=True, timeout=15)
    return self._json({"ok": True})


def get_asset(self, app, parsed, query, match):
    return self._json(app.database.get_asset(match.group(1)))


def remove_asset(self, app, parsed, query, match):
    app.database.remove_asset(match.group(1))
    return self._json({"ok": True, "original_file_changed": False})


def get_media(self, app, parsed, query, match):
    asset_id, kind = match.groups()
    source = resolve_registered_asset(app.database, asset_id)
    asset = app.database.get_asset(asset_id)
    if kind == "thumbnail":
        target = app.media_cache.thumbnail_path(
            asset_id, source, asset["media_type"], asset.get("duration")
        )
    elif kind == "preview":
        target = app.media_cache.preview_path(asset_id, source, asset["media_type"])
    else:
        target = source
    return self._file(target)


def reveal_asset(self, app, parsed, query, match):
    source = resolve_registered_asset(app.database, match.group(1))
    if os.name == "nt":
        subprocess.Popen(["explorer.exe", f"/select,{source}"])
    else:
        subprocess.run(["open", "-R", str(source)], check=True, timeout=15)
    return self._json({"ok": True})


def set_favorite(self, app, parsed, query, match):
    app.database.set_favorite(match.group(1), bool(self._body().get("favorite")))
    return self._json(app.database.get_asset(match.group(1)))


def set_stage(self, app, parsed, query, match):
    data = self._body()
    stage = data.get("stage")
    if not isinstance(stage, str):
        raise ValueError("stage 必须是字符串")
    asset_id = match.group(1)
    app.database.set_asset_lifecycle_stage(asset_id, stage)
    return self._json(app.database.get_asset(asset_id))


def update_metadata(self, app, parsed, query, match):
    asset_id = match.group(1)
    data = self._body()
    if "display_name" in data:
        app.database.update_display_name(asset_id, str(data["display_name"]))
    if "note" in data:
        app.database.update_note(asset_id, str(data["note"])[:4000])
    for tag in data.get("add_tags", []):
        app.database.add_tag(asset_id, str(tag))
    for tag in data.get("remove_tags", []):
        app.database.remove_tag(asset_id, str(tag))
    for tag in data.get("confirm_tag_candidates", []):
        app.database.confirm_tag_candidate(asset_id, str(tag))
    for category in data.get("confirm_categories", []):
        app.database.confirm_candidate(asset_id, str(category))
    for category in data.get("remove_categories", []):
        app.database.remove_category(asset_id, str(category))
    for category in data.get("manual_categories", []):
        app.database.set_category(asset_id, str(category), "manual", "confirmed", "木易人工设置")
    return self._json(app.database.get_asset(asset_id))


def add_batch_tags(self, app, parsed, query, match):
    data = self._body()
    for asset_id in data.get("asset_ids", []):
        for tag in data.get("tags", []):
            app.database.add_tag(str(asset_id), str(tag))
    return self._json({"updated": len(data.get("asset_ids", []))})


ROUTES = (
    ('GET', re.compile('/api/folders'), list_folders),
    ('GET', re.compile('/api/assets'), list_assets),
    ('POST', re.compile('/api/assets/recover\\-missing'), recover_missing),
    ('PATCH', re.compile('/api/assets/batch/stage'), set_batch_stage),
    ('POST', re.compile('/api/folders/reveal'), reveal_folder),
    ('GET', re.compile('/api/assets/([0-9a-f]+)'), get_asset),
    ('DELETE', re.compile('/api/assets/([0-9a-f]+)'), remove_asset),
    ('GET', re.compile('/api/assets/([0-9a-f]+)/(media|preview|thumbnail)'), get_media),
    ('POST', re.compile('/api/assets/([0-9a-f]+)/reveal'), reveal_asset),
    ('PATCH', re.compile('/api/assets/([0-9a-f]+)/favorite'), set_favorite),
    ('PATCH', re.compile('/api/assets/([0-9a-f]+)/stage'), set_stage),
    ('PATCH', re.compile('/api/assets/([0-9a-f]+)/metadata'), update_metadata),
    ('POST', re.compile('/api/assets/batch/tags'), add_batch_tags),
)
