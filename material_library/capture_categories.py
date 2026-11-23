"""链接用途目录与卡片用途迁移；宿主必须提供同一 connection 和 RLock。"""
import json
import uuid
from typing import Any, Dict, Iterable, List, Optional

from .storage_support import _json, _now, synchronized


class CaptureCategoryStore:
    """只使用宿主连接与锁，不建立连接，不持有独立事务状态。"""
    connection: Any
    lock: Any

    @staticmethod
    def _normalize_capture_category_name(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("链接用途名称必须是文字")
        name = " ".join(value.split())
        if not name:
            raise ValueError("链接用途名称不能为空")
        if len(name) > 40:
            raise ValueError("链接用途名称不能超过 40 个字")
        return name


    @synchronized
    def list_capture_categories(self) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, name, sort_order, created_at, updated_at "
            "FROM capture_categories ORDER BY sort_order, created_at"
        ).fetchall()
        counts = {str(row["name"]): 0 for row in rows}
        for capture in self.connection.execute("SELECT categories_json FROM captures").fetchall():
            try:
                values = json.loads(capture["categories_json"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                values = []
            for name in set(str(value) for value in values if str(value) in counts):
                counts[name] += 1
        return [
            {**dict(row), "count": counts[str(row["name"])], "protected": row["name"] == "待分类"}
            for row in rows
        ]


    def create_capture_category(self, name: str) -> Dict[str, Any]:
        clean_name = self._normalize_capture_category_name(name)
        now = _now()
        category_id = uuid.uuid4().hex[:20]
        with self.lock, self.connection.transaction():
            exists = self.connection.execute(
                "SELECT 1 FROM capture_categories WHERE lower(name)=lower(%s)", (clean_name,)
            ).fetchone()
            if exists is not None:
                raise ValueError("这个链接用途已经存在")
            next_order = int(self.connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS value FROM capture_categories"
            ).fetchone()["value"])
            self.connection.execute(
                "INSERT INTO capture_categories(id, name, sort_order, created_at, updated_at) "
                "VALUES(%s, %s, %s, %s, %s)",
                (category_id, clean_name, next_order, now, now),
            )
        return next(item for item in self.list_capture_categories() if item["id"] == category_id)


    @staticmethod
    def _replace_capture_category_values(values: Any, old_name: str, new_name: str) -> List[str]:
        result = []
        for value in values if isinstance(values, list) else []:
            name = new_name if str(value) == old_name else str(value)
            if name and name not in result:
                result.append(name)
        if any(name != "待分类" for name in result):
            result = [name for name in result if name != "待分类"]
        return result


    def rename_capture_category(self, category_id: str, name: str) -> Dict[str, Any]:
        clean_name = self._normalize_capture_category_name(name)
        with self.lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT * FROM capture_categories WHERE id=%s", (category_id,)
            ).fetchone()
            if row is None:
                raise KeyError(category_id)
            old_name = str(row["name"])
            if old_name == "待分类":
                raise ValueError("待分类是系统用途，不能改名")
            duplicate = self.connection.execute(
                "SELECT 1 FROM capture_categories WHERE lower(name)=lower(%s) AND id<>%s",
                (clean_name, category_id),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("这个链接用途已经存在")
            for capture in self.connection.execute(
                "SELECT id, categories_json FROM captures"
            ).fetchall():
                try:
                    values = json.loads(capture["categories_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    values = []
                updated = self._replace_capture_category_values(values, old_name, clean_name)
                if updated != values:
                    self.connection.execute(
                        "UPDATE captures SET categories_json=%s, updated_at=%s WHERE id=%s",
                        (_json(updated), _now(), capture["id"]),
                    )
            self.connection.execute(
                "UPDATE capture_categories SET name=%s, updated_at=%s WHERE id=%s",
                (clean_name, _now(), category_id),
            )
        return next(item for item in self.list_capture_categories() if item["id"] == category_id)


    def delete_capture_category(
        self, category_id: str, replacement_id: Optional[str] = None
    ) -> Dict[str, Any]:
        with self.lock, self.connection.transaction():
            row = self.connection.execute(
                "SELECT * FROM capture_categories WHERE id=%s", (category_id,)
            ).fetchone()
            if row is None:
                raise KeyError(category_id)
            old_name = str(row["name"])
            if old_name == "待分类":
                raise ValueError("待分类是系统用途，不能删除")
            replacement_name = ""
            if replacement_id:
                replacement = self.connection.execute(
                    "SELECT * FROM capture_categories WHERE id=%s", (replacement_id,)
                ).fetchone()
                if replacement is None:
                    raise KeyError(replacement_id)
                if replacement_id == category_id:
                    raise ValueError("迁移用途不能与删除用途相同")
                replacement_name = str(replacement["name"])
            affected = []
            for capture in self.connection.execute(
                "SELECT id, categories_json FROM captures"
            ).fetchall():
                try:
                    values = json.loads(capture["categories_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    values = []
                if old_name in values:
                    affected.append((capture, values))
            if affected and not replacement_name:
                raise ValueError("这个用途仍有链接素材，请先选择迁移到哪个用途")
            for capture, values in affected:
                updated = self._replace_capture_category_values(values, old_name, replacement_name)
                updated = [name for name in updated if name]
                if not updated:
                    updated = ["待分类"]
                self.connection.execute(
                    "UPDATE captures SET categories_json=%s, updated_at=%s WHERE id=%s",
                    (_json(updated), _now(), capture["id"]),
                )
            self.connection.execute("DELETE FROM capture_categories WHERE id=%s", (category_id,))
        return {"deleted": True, "id": category_id, "name": old_name, "migrated_count": len(affected)}
