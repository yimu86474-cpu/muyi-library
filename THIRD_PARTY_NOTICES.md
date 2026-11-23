# 第三方组件许可

木易素材库和 Chrome 收集器的项目代码采用 MIT。安装包内的第三方组件使用各自的许可证。许可原文与署名位于 `licenses/`，来源索引见该目录的 `SOURCES.md`。

| 组件 | 许可与对应源码 |
| --- | --- |
| PostgreSQL 服务端及 libpq 客户端 | PostgreSQL License。准确版本、官方源码归档及许可文本见 `tools/postgres/SOURCE.txt`、`tools/postgres/LICENSE`。应用和数据库使用同一次构建提供的 libpq。 |
| CPython 和标准库 | Python Software Foundation License 及各组件自己的条款。Python 许可位于 `licenses/CPython.txt`，包内另附 Expat、XZ 和 zlib 的许可原文。 |
| PyInstaller 6.22.3 | GPL v2 或更高版本，带有引导程序例外。随应用分发的运行时钩子使用 Apache 2.0。 [对应源码](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3) |
| Psycopg 3.3.6 | LGPL v3 或更高版本，随包提供 LGPL v3 和所引用的 GPL v3 两份原文。纯 Python 驱动位于 `_internal/psycopg/`。安装说明给出替换兼容版本的操作。 [对应源码](https://github.com/psycopg/psycopg/tree/3.3.6) |
| typing-extensions 4.16.0 | PSF-2.0。 [对应发行版](https://pypi.org/project/typing-extensions/4.16.0/#files) |
| tzdata 2026.6（Windows） | Python 时区数据包的许可证随包，IANA 时区数据为公有领域。 [对应发行版](https://pypi.org/project/tzdata/2026.6/#files) |
| OpenSSL 3（Python 的 TLS 依赖） | Apache 2.0。实际版本的许可和源码链接在 `licenses/` 中。 |
| certifi 2026.11.20 | MPL-2.0。 [本版本源码包](https://pypi.org/project/certifi/2026.11.20/#files) |
| Vue 3.5.41 | MIT，含同版 Vue 运行时模块。 [对应源码](https://github.com/vuejs/core/tree/v3.5.41) |
| hls.js 1.7.1 | Apache 2.0。hls.js 厂商和 Brightcove 的版权声明在 `licenses/hls.js.txt`，许可证全文在 `licenses/Apache-2.0.txt`。 [对应源码](https://github.com/video-dev/hls.js/tree/v1.7.1) |

Windows 的 Visual C++ v14 x64 运行库由用户从 Microsoft 官方获取。处理本地媒体时，用户自行从上游安装 FFmpeg 和 FFprobe。 [Microsoft 下载页](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) · [FFmpeg 下载页](https://ffmpeg.org/download.html)
