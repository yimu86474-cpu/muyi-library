"""Resource handlers for collections; existing application services own side effects."""
import re
from http import HTTPStatus


def list_collections(self, app, parsed, query, match):
    return self._json({"items": app.database.list_collections()})


def create_collection(self, app, parsed, query, match):
    data = self._body()
    return self._json(
        app.database.create_collection(
            data.get("name", ""), asset_ids=data.get("asset_ids", [])
        ),
        status=HTTPStatus.CREATED,
    )


def create_from_filter(self, app, parsed, query, match):
    data = self._body()
    values = data.get("filters") or {}
    favorite = values.get("favorite")
    availability = values.get("availability", "all")
    if availability not in ("available", "missing", "all"):
        raise ValueError("可用性必须是 available、missing 或 all")
    asset_filters = dict(
        query=str(values.get("q") or ""),
        media_type=str(values.get("type") or ""),
        category=str(values.get("category") or ""),
        collection_id=str(values.get("collection") or ""),
        source_id=str(values.get("source") or ""),
        orientation=str(values.get("orientation") or ""),
        status=str(values.get("status") or ""),
        date_from=float(values["date_from"]) if values.get("date_from") else None,
        date_to=float(values["date_to"]) if values.get("date_to") else None,
        favorite=None if favorite in (None, "", False) else bool(favorite),
        dedupe=bool(values.get("dedupe")),
        folder=str(values.get("folder") or ""),
        folder_scope=str(values.get("folder_scope") or "recursive"),
        availability=availability,
        lifecycle_stage=str(values.get("lifecycle_stage") or ""),
    )
    asset_ids = []
    total = app.database.count_assets(**asset_filters)
    for offset in range(0, total, 500):
        asset_ids.extend(
            item["id"]
            for item in app.database.list_assets(
                **asset_filters, limit=500, offset=offset
            )
        )
    return self._json(
        app.database.create_collection(
            data.get("name", ""), asset_ids=asset_ids
        ),
        status=HTTPStatus.CREATED,
    )


def set_asset_collections(self, app, parsed, query, match):
    app.database.set_asset_collections(
        match.group(1), self._body().get("collection_ids", [])
    )
    return self._json({"ok": True})


ROUTES = (
    ('GET', re.compile('/api/collections'), list_collections),
    ('POST', re.compile('/api/collections'), create_collection),
    ('POST', re.compile('/api/collections/from\\-filter'), create_from_filter),
    ('PATCH', re.compile('/api/assets/([0-9a-f]+)/collections'), set_asset_collections),
)
