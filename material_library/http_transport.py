"""HTTP origin checks, serialization and bounded local/remote file transport."""
import ipaddress
import os
import json
import subprocess
import urllib.error
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional
from .media import RangeNotSatisfiable, media_mime, parse_range_header
from .desktop_actions import pick_windows_folder


class MaterialHttpHandler(BaseHTTPRequestHandler):
    server_version = "MuyiMaterialLibrary/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        app = self.application
        log_dir = app.runtime_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "server.log").open("a", encoding="utf-8") as handle:
            handle.write("{} {}\n".format(self.log_date_time_string(), format % args))

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        allowed_origin = self._capture_cors_origin()
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Muyi-Capture-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_PATCH(self) -> None:
        self._route("PATCH")

    def do_DELETE(self) -> None:
        self._route("DELETE")

    def _require_local_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        parsed = urllib.parse.urlparse(origin)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise PermissionError("拒绝其他网页修改本机素材库")

    def _require_same_loopback_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        if not self._is_same_loopback_origin(origin):
            raise PermissionError("拒绝其他网页修改本机素材库")

    def _guard_request(self, method: str, path: str) -> None:
        if getattr(self.application, "standalone", False):
            self._require_standalone_route(method, path)
        elif method in ("POST", "PATCH", "DELETE") and (method, path) != ("POST", "/api/captures"):
            self._require_local_origin()

    def _require_standalone_route(self, method: str, path: str) -> None:
        if self._loopback_authority(self.headers.get("Host", ""), is_origin=False) != self.server.server_address:
            raise PermissionError("请从启动器显示的本机地址打开素材库")
        if not (method == "POST" and path in {"/api/captures", "/api/captures/pair"} and self._capture_cors_origin()):
            self._require_same_loopback_origin()
        if (
            path.startswith(("/api/obsidian", "/api/content", "/api/classification",
                             "/api/duplicates", "/api/system/"))
            or path.endswith(("/trash-duplicates", "/relocate", "/transcript"))
        ):
            raise FileNotFoundError("独立试用版暂未开放此功能")

    @staticmethod
    def _loopback_authority(value: str, *, is_origin: bool) -> Optional[tuple]:
        try:
            parsed = urllib.parse.urlsplit(value if is_origin else "//" + value)
            if (
                (is_origin and parsed.scheme != "http")
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                return None
            hostname = parsed.hostname
            port = parsed.port
        except ValueError:
            return None
        if not hostname:
            return None
        normalized_host = hostname.lower()
        if normalized_host != "localhost":
            try:
                address = ipaddress.ip_address(normalized_host)
            except ValueError:
                return None
            if not address.is_loopback:
                return None
            normalized_host = address.compressed
        return normalized_host, 80 if port is None else port

    def _is_same_loopback_origin(self, origin: str) -> bool:
        origin_authority = self._loopback_authority(origin, is_origin=True)
        host_authority = self._loopback_authority(
            self.headers.get("Host", ""), is_origin=False
        )
        return origin_authority is not None and origin_authority == host_authority

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("请求内容过大")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("请求内容必须是对象")
        return value

    def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if self.path.startswith("/api/captures"):
            allowed_origin = self._capture_cors_origin()
            if allowed_origin:
                self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message or HTTPStatus(status).phrase}, status=status)

    def _capture_cors_origin(self) -> Optional[str]:
        origin = self.headers.get("Origin", "")
        parsed = urllib.parse.urlparse(origin)
        if parsed.scheme == "chrome-extension" and parsed.hostname:
            return origin
        return None

    def _file(self, path: Path) -> None:
        size = path.stat().st_size
        range_header = self.headers.get("Range")
        if range_header:
            try:
                start, end = parse_range_header(range_header, size)
            except RangeNotSatisfiable:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", "bytes */{}".format(size))
                self.end_headers()
                return
            status = HTTPStatus.PARTIAL_CONTENT
        else:
            start, end = 0, max(0, size - 1)
            status = HTTPStatus.OK
        length = max(0, end - start + 1)
        try:
            # Establish read access before advertising a successful response.
            with path.open("rb") as handle:
                self.send_response(status)
                self.send_header("Content-Type", media_mime(path))
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header(
                    "Cache-Control",
                    "no-store" if path.name == "index.html" else "private, max-age=3600",
                )
                if status == HTTPStatus.PARTIAL_CONTENT:
                    self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, size))
                self.end_headers()
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            # Cancelling a preview/seek closes the client socket; no error
            # response can be sent there. The file context still releases it.
            self.close_connection = True

    def _remote_capture_media(self, capture_id: str, *, track: str = "video") -> None:
        app = self.application
        if track == "video":
            local_path = app.captures.local_file_path(capture_id)
            if local_path is not None:
                return self._file(local_path)
        try:
            response = app.captures.open_remote_media(
                capture_id, self.headers.get("Range", ""), track=track
            )
        except urllib.error.HTTPError as error:
            close_attempted = False
            try:
                capture = app.database.get_capture(capture_id)
                if (
                    str(capture.get("platform") or "") in {"douyin", "xiaohongshu"}
                    and error.code in (403, 404, 410)
                ):
                    try:
                        close_attempted = True
                        error.close()
                    finally:
                        app.capture_previews.mark_stale(
                            capture_id, "预览地址已失效"
                        )
                    return self._error(
                        HTTPStatus.CONFLICT, "预览地址已失效，请重新激活预览"
                    )
                raise
            finally:
                if not close_attempted:
                    try:
                        error.close()
                    except Exception:
                        # Cleanup must not replace the upstream or metadata error.
                        pass
        try:
            self._stream_remote_media(response, track)
        finally:
            response.close()

    def _stream_remote_media(self, response, track):
        status = int(getattr(response, "status", 0) or response.getcode() or 200)
        if status not in (HTTPStatus.OK, HTTPStatus.PARTIAL_CONTENT):
            raise ValueError("远程媒体暂时无法读取")
        headers = response.headers
        self.send_response(status)
        fallback_type = "audio/mp4" if track == "audio" else "video/mp4"
        self.send_header("Content-Type", headers.get("Content-Type") or fallback_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, max-age=3600")
        for name in ("Content-Length", "Content-Range", "Last-Modified"):
            value = headers.get(name)
            if value:
                self.send_header(name, value)
        self.end_headers()
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                break

    def _pick_folder(self) -> str:
        if getattr(self.application, "standalone", False) and os.name == "nt":
            return pick_windows_folder()
        script = 'POSIX path of (choose folder with prompt "选择要加入木易素材库的文件夹")'
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300, check=True
        )
        return result.stdout.strip().rstrip("/")

    def _pick_file(self) -> str:
        script = 'POSIX path of (choose file with prompt "选择这条素材移动后的新文件")'
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300, check=True
        )
        return result.stdout.strip()

    def _validate_source_path(self, value: str) -> Path:
        standalone = getattr(self.application, "standalone", False)
        if standalone and (not value or not Path(value).is_absolute()):
            raise ValueError("请选择一个具体的素材文件夹")
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("选择的文件夹不存在")
        forbidden = {Path("/"), Path.home(), Path.home() / "Desktop"}
        if path in forbidden:
            raise ValueError("来源范围太大，请选择具体素材文件夹")
        if standalone and (path == Path(path.anchor) or path in {
            (Path.home() / name).resolve() for name in ("Downloads", "Documents", "Pictures", "Videos", "Movies")
        }):
            raise ValueError("来源范围太大，请选择具体素材文件夹")
        return path

    def _static(self, path: str) -> None:
        app = self.application
        if not app.frontend_dir or not app.frontend_dir.is_dir():
            return self._error(HTTPStatus.NOT_FOUND, "页面尚未构建")
        relative = path.lstrip("/") or "index.html"
        candidate = (app.frontend_dir / relative).resolve()
        try:
            candidate.relative_to(app.frontend_dir.resolve())
        except ValueError:
            return self._error(HTTPStatus.FORBIDDEN, "无效页面路径")
        if not candidate.is_file():
            candidate = app.frontend_dir / "index.html"
        return self._file(candidate)
