"""Non-blocking coordination for expiring capture preview URLs."""

# Explanation contract: docs/EXPLAIN.md

import math
import logging
import queue
import re
import threading
import time
import urllib.error
from typing import Callable, Dict, Optional, Set
from urllib.parse import urlparse


CAPTURE_MEDIA_VERIFY_TTL_SECONDS = 1800
CAPTURE_MEDIA_RETRY_BACKOFF_SECONDS = 60
# Probing remote media and refreshing a thumbnail can finish during shutdown.
CAPTURE_PREVIEW_CLOSE_TIMEOUT_SECONDS = 180
_CLOSE_CANCELLED_REASON = "预览服务正在停止，未开始的刷新已取消"


_PUBLIC_MESSAGES = {
    "ready": "预览已就绪",
    "needs_activation": "预览地址需要重新激活，请稍后重试",
    "resolving": "正在后台刷新预览，请稍候",
    "needs_login": "请先在抖音完成登录或验证，再重试预览",
    "unavailable": "该作品当前不可预览",
}


_LOGGER = logging.getLogger(__name__)


class CapturePreviewCoordinator:
    """Coalesce preview refreshes and execute them on one background worker."""

    def __init__(
        self,
        database,
        capture_service,
        *,
        clock: Callable[[], float] = time.time,
        worker_starter: Optional[Callable[[Callable[[], None]], None]] = None,
    ):
        self.database = database
        self.capture_service = capture_service
        self.clock = clock
        self._jobs = queue.Queue()
        self._lock = threading.RLock()
        self._queued_keys = set()
        self._waiting_capture_ids: Dict[str, Set[str]] = {}
        self._closing = False
        self._closed = False
        self._stop_signal = object()
        self._stop_enqueued = False
        self._worker_thread: Optional[threading.Thread] = None
        self.database.recover_interrupted_capture_previews()
        if worker_starter is not None:
            worker_starter(self._run_one_job)
        else:
            self._start_daemon_worker()

    def _start_daemon_worker(self) -> None:
        def worker_loop() -> None:
            while True:
                try:
                    if not self._run_one_job():
                        return
                except BaseException:
                    _LOGGER.exception("capture preview worker cycle failed")

        self._worker_thread = threading.Thread(
            target=worker_loop,
            name="capture-preview-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def close(self, *, timeout: float = CAPTURE_PREVIEW_CLOSE_TIMEOUT_SECONDS) -> None:
        if timeout < 0:
            raise ValueError("关闭等待时间不能为负数")
        with self._lock:
            if self._closed:
                return
            if not self._closing:
                self._closing = True
                self._cancel_queued_jobs_locked()
            worker = self._worker_thread
            if worker is not None and not self._stop_enqueued:
                self._jobs.put(self._stop_signal)
                self._stop_enqueued = True
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=timeout)
            if worker.is_alive():
                raise TimeoutError("预览后台任务未在关闭期限内结束")
        with self._lock:
            if worker is None or not worker.is_alive():
                self._closed = True

    def _cancel_queued_jobs_locked(self) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            try:
                if job is self._stop_signal:
                    continue
                key, capture_id = job
                waiting_capture_ids = self._waiting_capture_ids.pop(key, {capture_id})
                self._queued_keys.discard(key)
                for waiting_capture_id in waiting_capture_ids:
                    self.database.update_capture_preview_state(
                        waiting_capture_id,
                        "needs_activation",
                        obtained_at=self.clock(),
                        error=_CLOSE_CANCELLED_REASON,
                    )
            finally:
                self._jobs.task_done()

    def prepare(self, capture_id: str, *, force: bool = False) -> Dict[str, object]:
        if not isinstance(force, bool):
            raise ValueError("force 必须是布尔值")
        with self._lock:
            if self._closing or self._closed:
                raise RuntimeError("预览服务正在停止")
        record = self.database.get_capture(capture_id)
        identity_response = self._missing_identity_response(record, capture_id)
        if identity_response is not None:
            return identity_response
        fast_response = self._prepare_fast_response(record, capture_id, force=force)
        if fast_response is not None:
            return fast_response

        with self._lock:
            if self._closing or self._closed:
                raise RuntimeError("预览服务正在停止")
            record = self.database.get_capture(capture_id)
            identity_response = self._missing_identity_response(record, capture_id)
            if identity_response is not None:
                return identity_response
            fast_response = self._prepare_fast_response(record, capture_id, force=force)
            if fast_response is not None:
                return fast_response
            key = self._work_key(record, capture_id)
            if key in self._queued_keys:
                record = self.database.update_capture_preview_state(
                    capture_id,
                    "resolving",
                    obtained_at=self.clock(),
                    error=None,
                )
                self._waiting_capture_ids.setdefault(key, set()).add(capture_id)
                return self._public_response(record, state="resolving")
            self._queued_keys.add(key)
            self._waiting_capture_ids[key] = {capture_id}
            try:
                record = self.database.update_capture_preview_state(
                    capture_id,
                    "resolving",
                    obtained_at=self.clock(),
                    error=None,
                )
                self._jobs.put((key, capture_id))
            except Exception:
                self._queued_keys.discard(key)
                self._waiting_capture_ids.pop(key, None)
                raise
        return self._public_response(record, state="resolving")

    def status(self, capture_id: str) -> Dict[str, object]:
        record = self.database.get_capture(capture_id)
        if self.capture_service.local_file_path(capture_id) is not None:
            return self._public_response(record, state="ready")
        if self._is_capture_queued(capture_id):
            return self._public_response(record, state="resolving")
        return self._public_response(record)

    def _is_capture_queued(self, capture_id: str) -> bool:
        with self._lock:
            return any(capture_id in ids for ids in self._waiting_capture_ids.values())

    def mark_stale(self, capture_id: str, reason: str) -> Dict[str, object]:
        record = self.database.update_capture_preview_state(
            capture_id,
            "needs_activation",
            obtained_at=self.clock(),
            error=str(reason or "预览地址已失效"),
        )
        return self._public_response(record, state="needs_activation")

    def _run_one_job(self) -> bool:
        job = self._jobs.get()
        try:
            if job is self._stop_signal:
                return False
            key, capture_id = job
            try:
                outcome = self._process_job(capture_id)
            except BaseException:
                outcome = {
                    "state": "needs_activation",
                    "error": "后台预览任务异常中断",
                    "obtained_at": self.clock(),
                }
            with self._lock:
                try:
                    if outcome["state"] == "ready":
                        self._refresh_thumbnail_best_effort(capture_id)
                        self._propagate_success(key, capture_id, outcome)
                    else:
                        self._propagate_failure(key, outcome)
                finally:
                    self._queued_keys.discard(key)
                    self._waiting_capture_ids.pop(key, None)
        finally:
            self._jobs.task_done()
        return True

    def _refresh_thumbnail_best_effort(self, capture_id: str) -> None:
        """Replace expiring remote covers with a local frame after media is ready."""
        try:
            record = self.database.get_capture(capture_id)
            # XHS already caches the original cover separately; refreshing video
            # must not replace or invalidate it using an expired image URL.
            if record.get("platform") == "xiaohongshu":
                return
            if str(record.get("thumbnail_status") or "") == "generated":
                return
            self.capture_service.refresh_thumbnail(capture_id)
        except Exception:
            # Preview readiness is more important than cover maintenance. A later
            # successful preview refresh will retry this best-effort operation.
            _LOGGER.info("capture thumbnail refresh deferred", exc_info=True)

    def _process_job(self, capture_id: str) -> Dict[str, object]:
        record = self.database.get_capture(capture_id)
        media_url = str(record.get("media_url") or "").strip()
        if media_url:
            try:
                self.capture_service.probe_remote_media(capture_id, track="video")
            except Exception as error:
                if not self._requires_resolution(error):
                    return self._error_outcome(error)
            else:
                return {
                    "state": "ready",
                    "obtained_at": record.get("media_obtained_at") or self.clock(),
                    "verified_at": self.clock(),
                }

        return {
            "state": "needs_activation",
            "error": "请打开原作品并播放，再用扩展重新点选，更新这张卡的媒体地址。",
            "obtained_at": self.clock(),
        }

    def _error_outcome(
        self,
        error: BaseException,
        *,
        attempted_at: Optional[float] = None,
    ) -> Dict[str, object]:
        return {
            "state": self._error_state(error),
            "obtained_at": self.clock() if attempted_at is None else attempted_at,
            "error": str(error or "预览地址刷新失败"),
        }

    def _propagate_success(
        self,
        key: str,
        source_capture_id: str,
        outcome: Dict[str, object],
    ) -> None:
        source = self.database.get_capture(source_capture_id)
        media_url = str(source.get("media_url") or "").strip()
        if not media_url:
            self._propagate_failure(
                key,
                {
                    "state": "needs_activation",
                    "obtained_at": outcome.get("obtained_at") or self.clock(),
                    "error": "预览刷新未返回可用媒体地址",
                },
            )
            return
        expected_external_id = str(source.get("external_id") or "")
        platform = str(source.get("platform") or "")
        for waiting_capture_id in self._waiting_capture_ids.get(key, {source_capture_id}):
            waiting = self.database.get_capture(waiting_capture_id)
            if key.startswith("douyin:") and (
                str(waiting.get("platform") or "") != "douyin"
                or str(waiting.get("external_id") or "") != expected_external_id
            ):
                self.database.update_capture_preview_state(
                    waiting_capture_id,
                    "unavailable",
                    obtained_at=outcome.get("obtained_at"),
                    error="等待刷新时作品 ID 已变化",
                )
                continue
            self.database.update_capture_media(
                waiting_capture_id,
                media_url,
                audio_url=str(source.get("audio_url") or ""),
                platform=platform,
                external_id=expected_external_id,
                page_url=str(source.get("page_url") or ""),
                page_title=str(source.get("page_title") or ""),
                published_at_text=str(source.get("published_at_text") or ""),
                obtained_at=float(outcome.get("obtained_at") or self.clock()),
                verified_at=float(outcome.get("verified_at") or self.clock()),
            )

    def _propagate_failure(self, key: str, outcome: Dict[str, object]) -> None:
        for waiting_capture_id in self._waiting_capture_ids.get(key, set()):
            self.database.update_capture_preview_state(
                waiting_capture_id,
                str(outcome["state"]),
                obtained_at=float(outcome.get("obtained_at") or self.clock()),
                error=str(outcome.get("error") or "预览地址刷新失败"),
            )

    def _prepare_fast_response(
        self,
        record: Dict[str, object],
        capture_id: str,
        *,
        force: bool = False,
    ) -> Optional[Dict[str, object]]:
        if self.capture_service.local_file_path(capture_id) is not None:
            return self._public_response(record, state="ready")
        if self._is_capture_queued(capture_id):
            return self._public_response(record, state="resolving")
        if self._is_recently_verified(record) and not force:
            return self._public_response(record, state="ready")
        state = str(record.get("media_refresh_status") or "needs_activation")
        if state == "unavailable" and not force:
            return self._public_response(record, state=state)
        if state == "needs_login" and not force:
            return self._public_response(record, state=state)
        if state == "needs_activation" and self._retry_after_ms(record) > 0 and not force:
            return self._public_response(record, state=state)
        return None

    def _missing_identity_response(
        self,
        record: Dict[str, object],
        capture_id: str,
    ) -> Optional[Dict[str, object]]:
        if (
            str(record.get("platform") or "") != "douyin"
            or str(record.get("content_kind") or "") != "video"
            or self._capture_work_id(record)
        ):
            return None
        record = self.database.update_capture_preview_state(
            capture_id,
            "unavailable",
            obtained_at=self.clock(),
            error="这张抖音卡没有可核对的作品 ID，请在原作品页重新采集",
        )
        return self._public_response(record, state="unavailable")

    @staticmethod
    def _capture_work_id(record: Dict[str, object]) -> str:
        external_id = str(record.get("external_id") or "").strip()
        if re.fullmatch(r"\d{8,}", external_id):
            return external_id
        parsed = urlparse(str(record.get("page_url") or "").strip())
        if (
            parsed.scheme not in {"http", "https"}
            or (parsed.hostname or "").lower() not in {"douyin.com", "www.douyin.com"}
        ):
            return ""
        match = re.fullmatch(r"/(?:video|note)/(\d{8,})/?", parsed.path)
        return match.group(1) if match else ""

    def _public_response(
        self,
        record: Dict[str, object],
        *,
        state: Optional[str] = None,
    ) -> Dict[str, object]:
        public_state = state or str(record.get("media_refresh_status") or "needs_activation")
        if public_state not in _PUBLIC_MESSAGES:
            public_state = "needs_activation"
        return {
            "capture_id": str(record.get("id") or ""),
            "state": public_state,
            "message": (
                str(record.get("media_refresh_error") or "")
                if record.get("platform") == "xiaohongshu" and public_state not in {"ready", "resolving"}
                else ""
            ) or _PUBLIC_MESSAGES[public_state],
            "has_audio": bool(str(record.get("audio_url") or "").strip()),
            "retry_after_ms": (
                self._retry_after_ms(record) if public_state == "needs_activation" else 0
            ),
        }

    def _is_recently_verified(self, record: Dict[str, object]) -> bool:
        if str(record.get("media_refresh_status") or "") != "ready":
            return False
        if not str(record.get("media_url") or "").strip():
            return False
        try:
            verified_at = float(record.get("media_last_verified_at"))
        except (TypeError, ValueError):
            return False
        age = max(0.0, self.clock() - verified_at)
        return age <= CAPTURE_MEDIA_VERIFY_TTL_SECONDS

    def _retry_after_ms(self, record: Dict[str, object]) -> int:
        if not record.get("media_refresh_error"):
            return 0
        try:
            attempted_at = float(record.get("media_obtained_at"))
        except (TypeError, ValueError):
            return 0
        remaining = attempted_at + CAPTURE_MEDIA_RETRY_BACKOFF_SECONDS - self.clock()
        return max(0, int(math.ceil(remaining * 1000)))

    @staticmethod
    def _work_key(record: Dict[str, object], capture_id: str) -> str:
        work_id = CapturePreviewCoordinator._capture_work_id(record)
        if str(record.get("platform") or "") == "douyin" and work_id:
            return "douyin:{}".format(work_id)
        return "capture:{}".format(capture_id)

    @staticmethod
    def _requires_resolution(error: BaseException) -> bool:
        if isinstance(error, urllib.error.HTTPError) and error.code in (403, 404, 410):
            return True
        message = str(error or "").lower()
        if re.search(r"http\s*(?:error\s*)?(403|404|410)", message):
            return True
        return any(
            marker in message
            for marker in (
                "没有可安全预检",
                "没有可信",
                "受信任媒体地址",
                "missing media",
                "stale",
            )
        )

    @staticmethod
    def _error_state(error: BaseException) -> str:
        explicit_state = str(getattr(error, "preview_state", ""))
        if explicit_state in {"needs_activation", "needs_login", "unavailable"}:
            return explicit_state
        message = str(error or "").lower()
        if isinstance(error, (TimeoutError, ConnectionError)):
            return "needs_activation"
        if re.search(r"http\s*401\b", message):
            return "needs_login"
        if any(
            marker in message
            for marker in ("登录", "验证码", "captcha", "challenge", "login", "sign in")
        ):
            return "needs_login"
        if any(
            marker in message
            for marker in (
                "id 不匹配",
                "作品 id 不匹配",
                "source identity mismatch",
                "该作品为私密作品",
                "作品已设为私密",
                "作品仅作者可见",
                "precise work unavailable",
                "作品不存在",
                "作品已删除",
                "没有可核对的作品 id",
            )
        ):
            return "unavailable"
        return "needs_activation"
