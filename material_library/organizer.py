import hashlib
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from .database import LibraryDatabase
from .security import resolve_registered_asset


# Explanation contract: docs/EXPLAIN.md
def full_content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class DuplicateVerifier:
    def __init__(
        self,
        database: LibraryDatabase,
        hash_file: Optional[Callable[[Path], str]] = None,
    ):
        self.database = database
        self.hash_file = hash_file or full_content_hash

    def run(
        self,
        pause_event: Optional[threading.Event] = None,
        progress: Optional[Callable[[Dict[str, int]], None]] = None,
    ) -> Dict[str, int]:
        verified = failed = 0
        candidates = self.database.list_duplicate_verification_candidates()
        total = len(candidates)
        for index, asset_id in enumerate(candidates, start=1):
            if pause_event is not None:
                pause_event.wait()
            try:
                path = resolve_registered_asset(self.database, asset_id)
                before = path.stat()
                content_hash = self.hash_file(path)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise OSError("校验期间原文件发生变化，未写入重复结论")
                self.database.set_content_hash(asset_id, content_hash)
                verified += 1
            except Exception as error:
                self.database.set_content_hash(asset_id, None, str(error))
                failed += 1
            if progress:
                progress(
                    {
                        "total": total,
                        "processed": index,
                        "verified": verified,
                        "failed": failed,
                    }
                )
        summary = self.database.duplicate_summary()
        return {
            "total": total,
            "processed": total,
            "verified": verified,
            "failed": failed,
            "exact_groups": summary["exact_groups"],
            "hidden_copies": summary["hidden_copies"],
        }
