"""Retrieve the selected public image without using browser credentials or proxies."""

import http.client
import ipaddress
import json
import socket
import ssl
import subprocess
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

MAX_IMAGE_BYTES = 32 * 1024 * 1024
IMAGE_FORMATS = {
    ".jpg": ("jpeg_pipe", "mjpeg"),
    ".png": ("png_pipe", "png"),
    ".webp": ("webp_pipe", "webp"),
    ".gif": ("gif", "gif"),
    ".apng": ("apng", "apng"),
    ".avif": ("mov", "av1"),
}
IMAGE_MIME_SUFFIXES = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/gif": ".gif", "image/apng": ".apng", "image/avif": ".avif",
}


def _public_endpoints(host, port):
    endpoints = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for family, kind, protocol, _, address in endpoints:
        ip = ipaddress.ip_address(address[0])
        # Only normal publicly routed unicast addresses may receive the request.
        if not ip.is_global or ip.is_multicast:
            raise ValueError("只允许从公开地址保存网页图片")
        if ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo):
            raise ValueError("只允许从公开地址保存网页图片")
        if ip.version == 6 and ip not in ipaddress.ip_network("2000::/3"):
            raise ValueError("只允许从公开地址保存网页图片")
    return endpoints


def _connect(host, port, tls):
    connection = http.client.HTTPConnection(host, port, timeout=12)
    last_error = None
    for family, kind, protocol, _, address in _public_endpoints(host, port):
        stream = socket.socket(family, kind, protocol)
        try:
            stream.settimeout(12)
            stream.connect(address)
            connection.sock = ssl.create_default_context().wrap_socket(stream, server_hostname=host) if tls else stream
            return connection
        except OSError as error:
            stream.close()
            last_error = error
    raise ValueError("无法连接图片来源") from last_error


def _write_original(response, target):
    mime = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
    extension = IMAGE_MIME_SUFFIXES.get(mime)
    if response.status != 200 or mime not in {*IMAGE_MIME_SUFFIXES, "", "application/octet-stream"}:
        raise ValueError("图片来源没有返回可保存的原图，请打开原网页重选图片")
    length = response.getheader("Content-Length")
    if length and (not length.isdecimal() or int(length) > MAX_IMAGE_BYTES):
        raise ValueError("图片超过 32 MB 或无法确定原始长度")
    written = 0
    deadline = time.monotonic() + 60
    with target.open("xb") as handle:
        while block := response.read1(64 * 1024):
            if time.monotonic() > deadline:
                raise ValueError("等待原图下载超时")
            written += len(block)
            if written > MAX_IMAGE_BYTES:
                raise ValueError("图片超过 32 MB")
            handle.write(block)
    if not written or (length and written != int(length)):
        raise ValueError("图片文件为空或未完整下载")
    return validate_image(target, extension)


def _image_request(url):
    parts = urlsplit(url)
    secure = parts.scheme == "https"
    port = 443 if secure else 80
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("图片没有可用的公开原图地址，请打开原网页重选")
    if parts.username or parts.password or parts.port not in (None, port):
        raise ValueError("图片地址包含不支持的访问方式")
    request_path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    if parts.query:
        request_path += "?" + quote(parts.query, safe="%/?@:!$&'()*+,;=-._~")
    return parts.hostname.encode("idna").decode("ascii"), port, secure, request_path


def download_image(url, page_url, target):
    page = urlsplit(str(page_url or ""))
    headers = {"Accept": "image/*", "Accept-Encoding": "identity", "User-Agent": "Mozilla/5.0"}
    if page.scheme in ("http", "https") and page.hostname and not page.username and not page.password:
        headers["Referer"] = f"{page.scheme}://{page.netloc}/"
    for _ in range(5):
        origin, port, secure, request_path = _image_request(url)
        connection = _connect(origin, port, secure)
        try:
            connection.request("GET", request_path, headers=headers)
            with connection.getresponse() as response:
                location = response.getheader("Location")
                if response.status not in (301, 302, 303, 307, 308) or not location:
                    return _write_original(response, target)
                url = urljoin(url, location)
                if secure and urlsplit(url).scheme != "https":
                    raise ValueError("图片来源重定向到非加密地址")
        finally:
            connection.close()
    raise ValueError("图片来源重定向次数过多")


def validate_image(path: Path, extension: str | None = None):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_entries",
         "format=format_name:format_tags=major_brand:stream=codec_name,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if result.returncode:
        raise ValueError("原图格式无法读取或文件不完整")
    info = json.loads(result.stdout)
    formats = info.get("format", {}).get("format_name", "").split(",")
    stream = next(iter(info.get("streams", [])), {})
    if not stream.get("width") or not stream.get("height"):
        raise ValueError("下载结果不是可识别的原始图片")
    for suffix, (file_format, codec) in IMAGE_FORMATS.items():
        if file_format not in formats or stream.get("codec_name") != codec:
            continue
        if suffix == ".avif" and info["format"].get("tags", {}).get("major_brand") not in ("avif", "avis"):
            continue
        if extension and extension != suffix and {extension, suffix} != {".png", ".apng"}:
            raise ValueError("图片文件格式和来源返回的类型不一致")
        return suffix
    raise ValueError("暂时只能保存 JPG、PNG、WebP、GIF、APNG 和 AVIF 原图")
