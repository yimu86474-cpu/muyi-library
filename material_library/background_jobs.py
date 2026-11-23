"""Queue the standalone library scans outside HTTP request threads."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional
from .database import LibraryDatabase
from .scanner import MediaScanner


class ScanManager:
    def __init__(self, database: LibraryDatabase):
        self.database = database
        self.scanner = MediaScanner()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="material-scan")
        self.paused = threading.Event()
        self.paused.set()

    def start(self, source_id: str, batch_id: Optional[str] = None) -> str:
        scan_id = self.database.create_scan(source_id, batch_id=batch_id)
        self.executor.submit(self._run, scan_id, source_id)
        return scan_id

    def _run(self, scan_id: str, source_id: str) -> None:
        try:
            def progress(values: Dict[str, int]) -> None:
                self.paused.wait()
                self.database.update_scan(scan_id, **values)

            result = self.scanner.sync_source(
                self.database, source_id, progress=progress, scan_id=scan_id
            )
            self.database.update_scan(
                scan_id, status="completed", finished_at=time.time(), **result
            )
        except Exception as error:  # 后台任务必须持久化失败，不能静默退出
            self.database.update_scan(
                scan_id, status="failed", error=str(error)[:1000], finished_at=time.time()
            )

    def pause(self) -> None:
        self.paused.clear()

    def resume(self) -> None:
        self.paused.set()

    def status(self) -> Dict[str, Any]:
        active = self.database.count_running_scans()
        return {
            "status": "paused" if active and not self.paused.is_set() else "running" if active else "idle",
            "active": active,
        }
