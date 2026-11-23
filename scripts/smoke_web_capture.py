"""Verify video capture with synthetic CDN responses and an isolated PostgreSQL."""

import argparse
import io
import json
import re
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from material_library.database import LibraryDatabase
from material_library.server import create_server
from material_library.standalone_postgres import StandalonePostgres
from scripts.smoke_standalone import CAPTURE_FIXTURES, request, require, samples, wait_scan


def verify(root, postgres_bin, ffmpeg):
    source = root / "fixtures"
    samples(source, ffmpeg)
    video = (source / "测试 视频.mp4").read_bytes()
    png = (source / "测试 图片.png").read_bytes()
    media_urls = {
        "douyin": "https://v1.douyinvod.com/fixture.mp4",
        "xiaohongshu": "https://sns-video-bd.xhscdn.com/stream/fixture.mp4",
        "x": "https://video.twimg.com/ext_tw_video/190000000000000001/pu/fixture.mp4",
    }

    def open_fixture(upstream, timeout):
        require(upstream.full_url in media_urls.values(), "测试访问了未声明的媒体 URL")
        byte_range = upstream.get_header("Range")
        response = io.BytesIO(video)
        response.status = 200
        response.headers = {"Content-Type": "video/mp4", "Content-Length": str(len(video))}
        if byte_range:
            match = re.fullmatch(r"bytes=0-([0-9]+)", byte_range)
            require(match is not None, "测试只接受起始位置固定的分段请求")
            end = int(match[1])
            response = io.BytesIO(video[:end + 1])
            response.status = 206
            response.headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(end + 1),
                "Content-Range": f"bytes 0-{end}/{len(video)}",
            }
        return response

    runtime = root / "runtime"
    with StandalonePostgres(root, postgres_bin).running() as dsn:
        database = LibraryDatabase(runtime / "standalone-index", dsn=dsn)
        try:
            database.initialize()
            with patch("material_library.captures.open_capture_remote_media", open_fixture):
                with create_server("127.0.0.1", 0, database, runtime) as server:
                    thread = threading.Thread(target=server.serve_forever)
                    thread.start()
                    try:
                        base = f"http://127.0.0.1:{server.server_port}"
                        result = check(base, runtime, media_urls, video)
                        result["image_original"] = check_image(base, png)
                    finally:
                        server.shutdown()
                        thread.join()
        finally:
            database.close()
    require(not (root / "postgres" / "postmaster.pid").exists(), "PostgreSQL 未退出")
    return result


def check(base, runtime, media_urls, video):
    _, bootstrap = request(base, "/api/bootstrap")
    headers = {"Origin": "chrome-extension://" + "a" * 32, "X-Muyi-Capture-Token": bootstrap["capture_token"]}
    cards = {}
    for platform, (work_id, page_url) in CAPTURE_FIXTURES.items():
        _, card = request(base, "/api/captures", method="POST", headers=headers, data={
            "platform": platform, "external_id": work_id, "page_url": page_url, "page_title": platform,
            "content_kind": "video", "source_identity_verified": True, "media_url": media_urls[platform],
        })
        cards[platform] = f"/api/captures/{card['id']}"

    inbox = runtime / "capture-inbox"
    require(not inbox.exists(), "仅采集时不应写入视频原件")
    result = {}
    for platform, path in cards.items():
        if platform in {"douyin", "xiaohongshu"}:
            deadline = time.monotonic() + 8
            while True:
                _, preview = request(base, path + "/preview/status")
                if preview["state"] != "resolving":
                    break
                require(time.monotonic() < deadline, f"{platform} 的预览未按时完成")
                time.sleep(0.1)
            require(preview["state"] == "ready", f"{platform} 未取得可播放预览 {preview}")
        status, segment = request(base, path + "/media", headers={"Range": "bytes=0-31"})
        require(status == 206 and segment == video[:32], f"{platform} 视频预览未读回")
        _, saved = request(base, path + "/save-local", method="POST")
        require(saved["status"] == "downloaded" and saved.get("library_scan_id"), f"{platform} 保存入库失败")
        target = Path(saved["target_path"])
        require(target.parent == inbox and target.read_bytes() == video, f"{platform} 本地文件校验失败")
        wait_scan(base, saved["library_scan_id"])
        _, local_media = request(base, path + "/media")
        require(local_media == video, f"{platform} 已保存的视频没有从本地读回")
        result[platform] = {"preview_range": status, "local_save_and_index": True}
    _, library = request(base, "/api/assets?availability=available")
    require(library["total"] == len(cards), "保存的网页视频没有全部进入素材库")
    return result


def check_image(base, original):
    class ImageResponse(io.BytesIO):
        status = 200

        def getheader(self, name):
            return {"Content-Type": "image/png", "Content-Length": str(len(original))}.get(name)

    class ImageEndpoint:
        def request(self, method, path, headers):
            require(method == "GET" and path == "/original.png", "没有请求指定的原图")
            require("Cookie" not in headers and "Authorization" not in headers, "原图下载不得发送凭据")

        def getresponse(self):
            return ImageResponse(original)

        def close(self):
            pass

    _, bootstrap = request(base, "/api/bootstrap")
    headers = {"Origin": "chrome-extension://" + "a" * 32, "X-Muyi-Capture-Token": bootstrap["capture_token"]}
    for url, expected in (("http://127.0.0.1/original.png", "download_failed"),
                          ("https://image.example.test/original.png", "downloaded")):
        _, card = request(base, "/api/captures", method="POST", headers=headers, data={
            "page_title": "合成网页图片", "page_url": "https://example.test/work", "content_kind": "image",
            "media_url": url,
        })
        path = "/api/captures/" + card["id"]
        if expected == "download_failed":
            _, saved = request(base, path + "/save-local", method="POST")
            require(not saved.get("target_path") and "公开地址" in saved["failure_reason"],
                    "保存原图时未拒绝本机地址")
            continue
        with patch("material_library.capture_images._connect", return_value=ImageEndpoint()):
            _, saved = request(base, path + "/save-local", method="POST")
        require(saved["status"] == expected and saved.get("library_scan_id"), "保存网页原图失败")
        require(Path(saved["target_path"]).suffix == ".png", "原图格式没有保留")
        wait_scan(base, saved["library_scan_id"])
        _, copied = request(base, path + "/media")
        require(copied == original, "网页原图的字节发生变化")
    return {"preserved_bytes": len(original), "local_address_blocked": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="muyi-capture-") as directory:
        results = verify(Path(directory).resolve(), args.postgres_bin.resolve(), args.ffmpeg)
    print(json.dumps({"status": "pass", "synthetic_cdn": results}, ensure_ascii=True))


if __name__ == "__main__":
    main()
