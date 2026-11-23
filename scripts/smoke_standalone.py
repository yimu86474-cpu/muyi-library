"""Exercise first launch, media scan, shutdown and persisted readback with synthetic files."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER_MARKER = "Psycopg replacement loaded from the separate test directory"
CAPTURE_FIXTURES = {
    "douyin": ("7400000000000000001", "https://www.douyin.com/video/7400000000000000001"),
    "xiaohongshu": ("0123456789abcdef01234567", "https://www.xiaohongshu.com/explore/0123456789abcdef01234567"),
    "x": ("190000000000000001", "https://x.com/fixture/status/190000000000000001"),
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def request(base, path, *, method="GET", data=None, headers=None):
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        base + path, data=payload, method=method,
        headers={"Content-Type": "application/json", "Origin": base, **(headers or {})},
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as response:
        body = response.read()
        if response.headers.get_content_type() == "application/json":
            return response.status, json.loads(body)
        return response.status, body


def ready(process, log):
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith('{"url":'):
                info = json.loads(line)
                require(info["pid"] == process.pid, "启动回执 PID 不匹配")
                require(re.fullmatch(r"http://127\.0\.0\.1:\d+", info["url"]), "非隔离本机地址")
                return info["url"]
        if process.poll() is not None:
            break
        time.sleep(0.15)
    raise RuntimeError(f"没有收到启动回执，查看 {log}")


def launcher_settings(work):
    if os.name == "nt":
        local_appdata = work / "Local AppData"
        return local_appdata / "MuyiMaterialLibraryPreview", {"LOCALAPPDATA": str(local_appdata)}, []
    library = work / "library"
    return library, {}, ["--data-dir", str(library)]


@contextmanager
def launch(work, command, attempt, unpacked, *, driver=None):
    log = work / f"launch-{attempt}.log"
    library, profile_env, flags = launcher_settings(work)
    env = dict(os.environ, MUYI_POSTGRES_PROFILES=str(work / "intentionally-absent.json"),
               MATERIAL_DATABASE_DSN="host=127.0.0.1 port=1", PGPORT="1")
    env.update(profile_env)
    env.pop("MUYI_PSYCOPG_PATH", None)
    if driver is not None:
        env["MUYI_PSYCOPG_PATH"] = str(driver)
    with log.open("wb") as output:
        process = subprocess.Popen(
            [*command, *flags, "--no-browser", "--port", "0"],
            stdout=output, stderr=subprocess.STDOUT, cwd=work if unpacked else ROOT, env=env,
        )
    try:
        base = ready(process, log)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        raise
    try:
        if driver is not None:
            require(DRIVER_MARKER in log.read_text(encoding="utf-8"), "未加载可替换 Psycopg")
        yield base, process.pid
    finally:
        try:
            if process.poll() is None:
                request(base, "/api/service/stop", method="POST")
            require(process.wait(timeout=45) == 0, f"素材库异常退出，查看 {log}")
            require(not (library / "postgres" / "postmaster.pid").exists(), "PostgreSQL 没有退出")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def samples(root, ffmpeg):
    root.mkdir()
    png = root / "测试 图片.png"
    mp4 = root / "测试 视频.mp4"
    for source, settings, target in (
        ("color=c=orange:s=96x64", ["-frames:v", "1", "-threads", "1"], png),
        ("testsrc2=size=128x96:rate=12", ["-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p"], mp4),
    ):
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", source, *settings, str(target)],
                       check=True, timeout=30)
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (png, mp4)}


def read_assets(base, expected):
    _, result = request(base, "/api/assets?availability=available")
    assets = {asset["relative_path"]: asset for asset in result["items"]}
    require(set(assets) == set(expected) and result["total"] == 2, "素材应恰好为两条合成样本")
    require({item["media_type"] for item in assets.values()} == {"image", "video"}, "图片或视频未识别")
    for filename, asset in assets.items():
        url = f"/api/assets/{asset['id']}"
        _, original = request(base, url + "/media")
        require(hashlib.sha256(original).hexdigest() == expected[filename], "原件读回字节不一致")
        _, preview = request(base, url + "/thumbnail")
        require(len(preview) > 30 and preview.startswith(b"\xff\xd8"), "缺少 JPEG 缩略图")
        if asset["media_type"] == "video":
            status, segment = request(base, url + "/preview", headers={"Range": "bytes=0-31"})
            require(status == 206 and len(segment) == 32 and b"ftyp" in segment, "视频预览不能分段读取")
    return assets


def wait_scan(base, scan_id):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        _, scans = request(base, "/api/scans")
        scan = next(row for row in scans["items"] if row["id"] == scan_id)
        require(scan["status"] != "failed", f"扫描失败 {scan}")
        if scan["status"] == "completed":
            require(scan["commit_status"] == "committed", f"扫描未提交 {scan}")
            return
        time.sleep(0.15)
    raise TimeoutError("合成素材扫描未按时完成")


def check_isolation(base):
    for path, headers, status in (
        ("/api/bootstrap", {"Host": "outside.invalid"}, 403),
        ("/api/bootstrap", {"Origin": "https://outside.invalid"}, 403),
        ("/api/content/index/status", {}, 404),
    ):
        try:
            request(base, path, headers=headers)
        except urllib.error.HTTPError as error:
            require(error.code == status, "独立版隔离门禁响应不符")
        else:
            raise RuntimeError("独立版隔离门禁未拒绝请求")


def capture_fixture_cards(base, token):
    origin = "chrome-extension://" + "a" * 32
    headers = {"Origin": origin, "X-Muyi-Capture-Token": token}
    status, paired = request(base, "/api/captures/pair", method="POST", headers=headers)
    require(status == 200 and paired == {"ok": True}, "扩展配对失败")
    try:
        request(base, "/api/captures/pair", method="POST", headers={**headers, "X-Muyi-Capture-Token": "wrong"})
    except urllib.error.HTTPError as error:
        require(error.code == 403, "错误令牌应拒绝")
    else:
        raise RuntimeError("错误令牌被接受")
    ids = {}
    for platform_name, (work_id, url) in CAPTURE_FIXTURES.items():
        payload = {"platform": platform_name, "external_id": work_id, "page_url": url,
                   "page_title": "合成样本", "content_kind": "video", "source_identity_verified": True}
        _, card = request(base, "/api/captures", method="POST", headers=headers, data=payload)
        _, duplicate = request(base, "/api/captures", method="POST", headers=headers, data=payload)
        require(card["id"] == duplicate["id"] and duplicate["duplicate"], "同一作品没有去重")
        ids[platform_name] = card["id"]
    request(base, f"/api/captures/{ids['douyin']}/metadata", method="PATCH",
            data={"note": "网页采集复验备注", "tags": ["采集测试"]})
    return ids


def check_capture_readback(base, capture_ids, library):
    _, capture_list = request(base, "/api/captures")
    captures = {item["platform"]: item for item in capture_list["items"]}
    require({name: item["id"] for name, item in captures.items()} == capture_ids, "网页卡重启后未读回")
    douyin = captures["douyin"]
    require(douyin["note"] == "网页采集复验备注" and "采集测试" in douyin["tags"], "采集备注或标签丢失")
    require(not (library / "runtime" / "capture-inbox").exists(), "仅收集链接时不应保存媒体")


def check_without_media(work, command, unpacked):
    work.mkdir()
    absent_tools = work / "empty-tools"
    absent_tools.mkdir()
    command = [*command, "--media-bin", str(absent_tools)]
    with launch(work, command, 1, unpacked) as (base, _):
        _, bootstrap = request(base, "/api/bootstrap")
        require(not bootstrap["media_tools_ready"], "未安装媒体工具时不应显示就绪")
        capture_ids = capture_fixture_cards(base, bootstrap["capture_token"])
        try:
            request(base, "/api/scans", method="POST", data={"source_ids": []})
        except urllib.error.HTTPError as error:
            require(error.code == 503 and "FFmpeg" in error.read().decode(), "缺少工具时应说明安装方式")
        else:
            raise RuntimeError("缺少媒体工具时不应启动扫描")
    with launch(work, command, 2, unpacked) as (base, _):
        library, _, _ = launcher_settings(work)
        check_capture_readback(base, capture_ids, library)


def packaged_runtime(command, bundle):
    description = subprocess.check_output([*command, "--version"], text=True, encoding="utf-8", timeout=30).strip()
    matched = re.fullmatch(r"Python (\d+\.\d+\.\d+), OpenSSL (3\.5\.(\d+))(?:[ \t]+.*)?", description)
    require(matched is not None and int(matched[3]) >= 9, f"安装包使用了不受支持的 OpenSSL 版本。{description}")
    declared = (bundle / "licenses" / "OpenSSL-SOURCE.txt").read_text(encoding="utf-8").splitlines()[0]
    require(declared == f"OpenSSL {matched[2]}", "OpenSSL 运行版本与随包许可证记录不一致")
    return {"python": matched[1], "openssl": matched[2]}


def prepare_replacement_driver(work, bundle):
    source = bundle / "_internal" / "psycopg"
    require((source / "__init__.py").is_file(), "Psycopg 未以可替换源文件分发")
    replacement = work / "replacement-driver"
    shutil.copytree(source, replacement / "psycopg")
    with (replacement / "psycopg" / "__init__.py").open("a", encoding="utf-8") as module:
        module.write(f"\nprint({DRIVER_MARKER!r}, flush=True)\n")
    return replacement


def check(work, command, ffmpeg, unpacked, driver):
    source = work / "样本 文件夹"
    expected = samples(source, ffmpeg)
    with launch(work, command, 1, unpacked) as (base, first_pid):
        library, _, _ = launcher_settings(work)
        require((library / "postgres" / "PG_VERSION").is_file(), "没有在试用版用户目录建立 PostgreSQL")
        check_isolation(base)
        _, page = request(base, "/")
        require(b"/assets/" in page and b"index-" in page, "独立版未提供构建好的网页")
        _, bootstrap = request(base, "/api/bootstrap")
        require(bootstrap["standalone"] and not bootstrap["sources"], "首次启动应为空库")
        require(bootstrap["media_tools_ready"], "外部 FFmpeg 和 FFprobe 未被识别")
        capture_ids = capture_fixture_cards(base, bootstrap["capture_token"])
        _, new_source = request(base, "/api/sources", method="POST", data={"path": str(source)})
        _, scan = request(base, "/api/scans", method="POST", data={"source_ids": [new_source["id"]]})
        wait_scan(base, scan["scan_ids"][0])
        first = read_assets(base, expected)
        asset = first["测试 图片.png"]
        request(base, f"/api/assets/{asset['id']}/metadata", method="PATCH",
                data={"note": "重启读回备注", "add_tags": ["合成测试"]})
    with launch(work, command, 2, unpacked, driver=driver) as (base, second_pid):
        require(first_pid != second_pid, "未观察到独立进程重启")
        _, bootstrap = request(base, "/api/bootstrap")
        require([row["id"] for row in bootstrap["sources"]] == [new_source["id"]], "来源未持久化")
        require(len(bootstrap["scans"]) == 1, "重启时不应再次扫描")
        second = read_assets(base, expected)
        ids = {name: row["id"] for name, row in second.items()}
        require(ids == {name: row["id"] for name, row in first.items()}, "重启后的素材 ID 改变")
        asset = second["测试 图片.png"]
        require(asset["note"] == "重启读回备注" and "合成测试" in asset["tags"], "备注或标签未读回")
        check_capture_readback(base, capture_ids, library)
    for name, checksum in expected.items():
        require(hashlib.sha256((source / name).read_bytes()).hexdigest() == checksum, "原件被修改")
    result = {
        "status": "pass", "platform": platform.platform(), "unpacked_bundle": unpacked,
        "launch_pids": [first_pid, second_pid], "assets": ids,
        "first_launch_empty": True, "metadata_survived_restart": True,
        "replacement_driver_loaded_on_restart": driver is not None,
        "local_only_and_integrations_disabled": True,
        "synthetic_capture_cards_survived_restart": capture_ids,
        "exercised_windows_default_data_directory": os.name == "nt",
        "video_preview_range": 206, "originals_unchanged": True, "postgres_stopped_after_each_run": True,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True, help="只在尚不存在的验收目录运行")
    parser.add_argument("--launcher", type=Path, help="解包目录中的独立可执行文件")
    parser.add_argument("--tools-root", type=Path, help="独立包内的工具和扩展目录")
    parser.add_argument("--postgres-bin", type=Path, help="只用于开发环境测试")
    parser.add_argument("--ffmpeg", help="生成合成样本的 FFmpeg 路径")
    parser.add_argument("--media-bin", type=Path, help="本次验收另装的 FFmpeg 和 FFprobe 目录")
    parser.add_argument("--check-no-tools", action="store_true", help="也验收未安装媒体工具时的链接采集")
    args = parser.parse_args()
    work = args.work.resolve()
    command = [str(args.launcher.resolve())] if args.launcher else [sys.executable, "-m", "material_library.standalone"]
    tools_root = args.tools_root or (args.launcher.resolve().parent if args.launcher else None)
    if tools_root:
        manifest = tools_root / "chrome-extension" / "manifest.json"
        require("http://127.0.0.1:18778/*" in json.loads(manifest.read_text(encoding="utf-8"))["host_permissions"],
                "试用包未带上配对端口正确的扩展")
        require((tools_root / "chrome-extension" / "LICENSE").is_file(), "收集器缺少许可证")
        require((tools_root / "tools" / "postgres" / "LICENSE").is_file(), "PostgreSQL 缺少许可证")
        require(not (tools_root / "tools" / "media").exists(), "包中不应包含媒体工具")
        require((tools_root / "licenses" / "GPL-3.0.txt").is_file(), "Psycopg 缺少配套 GPL v3 文本")
    runtime = packaged_runtime(command, tools_root) if tools_root else None
    if args.postgres_bin:
        command.extend(("--postgres-bin", str(args.postgres_bin.resolve())))
    ffmpeg = "ffmpeg"
    work.mkdir(parents=True, exist_ok=False)
    if args.check_no_tools:
        check_without_media(work / "link-only", command, bool(args.launcher))
    if args.media_bin:
        media_bin = args.media_bin.resolve()
        command.extend(("--media-bin", str(media_bin)))
        ffmpeg = str(media_bin / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    driver = prepare_replacement_driver(work, tools_root) if tools_root else None
    result = check(work, command, args.ffmpeg or ffmpeg, bool(args.launcher), driver)
    result["link_only_without_media_tools"] = args.check_no_tools
    if runtime:
        result["packaged_runtime"] = runtime
    (work / "readback.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
