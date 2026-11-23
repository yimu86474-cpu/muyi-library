"""Entry point for the self-contained local image and video library preview."""

import argparse
import json
import os
import platform
import ssl
import sys
import webbrowser
from pathlib import Path

from psycopg import Error as PostgresError

from material_library.database import LibraryDatabase
from material_library.media_tools import configure_media_tools
from material_library.server import create_server
from material_library.standalone_postgres import StandalonePostgres, lock_data_directory


def default_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "MuyiMaterialLibraryPreview"
    return Path.home() / "Library" / "Application Support" / "MuyiMaterialLibraryPreview"


def bundled_paths() -> tuple[Path, Path]:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "frontend", Path(sys.executable).resolve().parent / "tools"
    repo = Path(__file__).resolve().parents[1]
    return repo / "frontend" / "dist", repo / "tools"


def run(args) -> None:
    root = args.data_dir.resolve()
    frontend = args.frontend.resolve()
    if not (frontend / "index.html").is_file():
        raise FileNotFoundError(f"找不到素材库页面 {frontend / 'index.html'}")
    if getattr(sys, "frozen", False):
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    media_tools_ready = configure_media_tools(args.media_bin)
    # libpq settings inherited from a developer shell never select this database.
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]

    runtime = root / "runtime"
    with lock_data_directory(root), StandalonePostgres(root, args.postgres_bin.resolve()).running() as dsn:
        database = LibraryDatabase(runtime / "standalone-index", dsn=dsn)
        try:
            database.initialize()
            database.recover_interrupted_scans()
            server = create_server(
                "127.0.0.1", args.port, database, runtime, frontend, media_tools_ready=media_tools_ready,
            )
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                print(json.dumps({"url": url, "pid": os.getpid()}), flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        finally:
            database.close()


def main() -> int:
    frontend, tools = bundled_paths()
    parser = argparse.ArgumentParser(description="独立启动木易素材库试用版")
    parser.add_argument("--version", action="version", version=f"Python {platform.python_version()}, {ssl.OPENSSL_VERSION}")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir(), help="此试用版专用的数据目录")
    parser.add_argument("--frontend", type=Path, default=frontend, help="独立构建的网页目录")
    parser.add_argument("--postgres-bin", type=Path, default=tools / "postgres" / "bin")
    parser.add_argument("--media-bin", type=Path, default=Path(value) if (value := os.environ.get("MUYI_MEDIA_BIN")) else None,
                        help="本机 FFmpeg 和 FFprobe 所在目录")
    parser.add_argument("--port", type=int, default=18778, help="本机端口，收集器使用默认端口 18778")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, RuntimeError, PostgresError, ValueError) as error:
        print(f"素材库启动失败。{error}\n日志目录 {args.data_dir}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
