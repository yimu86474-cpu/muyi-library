"""同一连接存储对象共用的时间、序列化和可重入锁包装。"""
import json
import time
from functools import wraps
from typing import Any


def _now() -> float:
    return time.time()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def synchronized(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)

    return locked
