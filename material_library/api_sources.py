"""Resource handlers for sources; existing application services own side effects."""
import re
import secrets
from http import HTTPStatus


def list_sources(self, app, parsed, query, match):
    return self._json({"items": [app.public_source(item) for item in app.database.list_sources()]})


def pick_source(self, app, parsed, query, match):
    selected = self._pick_folder()
    return self._json({"path": selected})


def add_source(self, app, parsed, query, match):
    data = self._body()
    source_path = self._validate_source_path(data.get("path", ""))
    excluded_relative_prefixes = data.get("excluded_relative_prefixes") or []
    if not isinstance(excluded_relative_prefixes, list):
        raise ValueError("excluded_relative_prefixes 必须是数组")
    source = app.database.add_source(
        data.get("name") or source_path.name,
        source_path,
        data.get("default_category"),
        excluded_relative_prefixes,
    )
    return self._json(app.public_source(source), status=HTTPStatus.CREATED)


def remove_source(self, app, parsed, query, match):
    app.database.remove_source(match.group(1))
    return self._json({"ok": True})


def list_scans(self, app, parsed, query, match):
    return self._json({"items": app.database.list_scans()})


def start_scans(self, app, parsed, query, match):
    if not app.media_tools_ready:
        return self._error(HTTPStatus.SERVICE_UNAVAILABLE, "扫描媒体需要 FFmpeg 和 FFprobe，请安装后重新打开素材库。")
    data = self._body()
    source_ids = data.get("source_ids") or [item["id"] for item in app.database.list_sources()]
    batch_id = secrets.token_hex(16)
    scan_ids = [app.scans.start(source_id, batch_id=batch_id) for source_id in source_ids]
    return self._json(
        {"batch_id": batch_id, "scan_ids": scan_ids}, status=HTTPStatus.ACCEPTED
    )


def pause_scans(self, app, parsed, query, match):
    app.scans.pause()
    return self._json({"status": "paused"})


def resume_scans(self, app, parsed, query, match):
    app.scans.resume()
    return self._json({"status": "running"})


def confirm_missing(self, app, parsed, query, match):
    result = app.database.confirm_scan_missing(match.group(1))
    return self._json(result)


ROUTES = (
    ('GET', re.compile('/api/sources'), list_sources),
    ('POST', re.compile('/api/sources/pick'), pick_source),
    ('POST', re.compile('/api/sources'), add_source),
    ('DELETE', re.compile('/api/sources/([0-9a-f]+)'), remove_source),
    ('GET', re.compile('/api/scans'), list_scans),
    ('POST', re.compile('/api/scans'), start_scans),
    ('POST', re.compile('/api/scans/pause'), pause_scans),
    ('POST', re.compile('/api/scans/resume'), resume_scans),
    ('POST', re.compile('/api/scans/([0-9a-f]+)/confirm-missing'), confirm_missing),
)
