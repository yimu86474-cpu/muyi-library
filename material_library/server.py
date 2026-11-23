"""Compose the material service and keep HTTP lifecycle separate from resource handlers."""
import json
import secrets
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from .background_jobs import ScanManager
from .api_routes import dispatch, UNHANDLED
from .http_transport import MaterialHttpHandler
from .captures import CaptureService
from .capture_preview import CAPTURE_PREVIEW_CLOSE_TIMEOUT_SECONDS, CapturePreviewCoordinator
from .database import LibraryDatabase
from .media import MediaCache
from .security import AssetAccessError

DEFAULT_FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "dist"


class MaterialApplication:
    def __init__(
        self,
        database: LibraryDatabase,
        runtime_dir: Path,
        frontend_dir: Optional[Path],
        inbox_dir: Optional[Path] = None,
        *,
        media_tools_ready: bool = True,
    ):
        self.database = database
        self.standalone = True
        self.media_tools_ready = media_tools_ready
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.frontend_dir = Path(frontend_dir) if frontend_dir else None
        self.media_cache = MediaCache(self.runtime_dir)
        self.scans = ScanManager(database)
        self.server: Optional[ThreadingHTTPServer] = None
        self._connect_captures(inbox_dir)

    def _connect_captures(self, inbox_dir):
        database = self.database
        self.captures = CaptureService(
            database,
            inbox_dir or (self.runtime_dir / "capture-inbox"),
            media_cache=self.media_cache,
        )
        self.capture_previews = CapturePreviewCoordinator(database, self.captures)
        token = database.get_setting("capture_pairing_token")
        if not token:
            token = secrets.token_urlsafe(24)
            database.set_setting("capture_pairing_token", token)
        self.capture_token = token

    def public_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        return dict(source)

    def stop(self) -> None:
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    def bootstrap(self) -> Dict[str, Any]:
        return {
            "standalone": True,
            "media_tools_ready": self.media_tools_ready,
            "categories": self.database.list_categories(),
            "lifecycle_stages": self.database.list_lifecycle_stages(media_type="video"),
            "capture_categories": self.database.list_capture_categories(),
            "sources": [self.public_source(item) for item in self.database.list_sources()],
            "collections": self.database.list_collections(),
            "scans": self.database.list_scans(),
            "scan_queue": self.scans.status(),
            "capture_token": self.capture_token,
            "capture_count": self.database.capture_count(),
            "projects": self.database.list_asset_folders(),
        }


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_close(self) -> None:
        app = getattr(self, "app", None)
        if app is not None:
            app.capture_previews.close(timeout=CAPTURE_PREVIEW_CLOSE_TIMEOUT_SECONDS)
            app.scans.resume()
            app.scans.executor.shutdown(wait=True, cancel_futures=True)
        super().server_close()


def create_handler(app: MaterialApplication):
    class Handler(MaterialHttpHandler):
        application = app

        def _route(self, method: str) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            try:
                self._guard_request(method, path)
                if method == "GET" and path == "/api/health":
                    return self._json({"status": "ok", "version": "0.1.0"})
                if method == "GET" and path == "/api/bootstrap":
                    return self._json(app.bootstrap())
                if method == "GET" and path == "/api/categories":
                    return self._json({"items": app.database.list_categories()})
                if method == "POST" and path == "/api/service/stop":
                    self._json({"status": "stopping"})
                    app.stop()
                    return
                result = dispatch(self, app, method, parsed, query)
                if result is not UNHANDLED:
                    return result
                return self._static(path)
            except PermissionError as error:
                return self._error(HTTPStatus.FORBIDDEN, str(error))
            except (AssetAccessError, KeyError, FileNotFoundError) as error:
                return self._error(HTTPStatus.NOT_FOUND, str(error))
            except (ValueError, json.JSONDecodeError) as error:
                return self._error(HTTPStatus.BAD_REQUEST, str(error))
            except subprocess.SubprocessError as error:
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            except Exception as error:
                return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))

    return Handler


def create_server(
    host: str,
    port: int,
    database: LibraryDatabase,
    runtime_dir: Path,
    frontend_dir: Optional[Path] = DEFAULT_FRONTEND,
    inbox_dir: Optional[Path] = None,
    *,
    media_tools_ready: bool = True,
) -> AppServer:
    app = MaterialApplication(
        database,
        runtime_dir,
        frontend_dir,
        inbox_dir=inbox_dir,
        media_tools_ready=media_tools_ready,
    )
    server = AppServer((host, port), create_handler(app))
    app.server = server
    server.app = app  # type: ignore[attr-defined]
    return server
