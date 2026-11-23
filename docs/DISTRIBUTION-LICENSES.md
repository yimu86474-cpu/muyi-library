# 桌面安装包第三方许可证核对

核对日期为 2026-11-23。核对对象是私有试用版 `v0.2.1-preview.1` 的实际下载文件。项目代码和 Chrome 收集器继续使用 MIT。下列条款适用于各自组件。

## 核对依据

| 下载文件 | SHA-256 |
| --- | --- |
| Windows x64 ZIP | `e42b4b6b24b2cbd3c942a90e94ea05d84c1ab685c9feaabb26fc2b99ec3210cd` |
| Apple 芯片 Mac DMG | `df6399f1a0ea0fe82693f6b7322e4641609b67358fb386d998d9cfa2a0f7935f` |
| Chrome 收集器 ZIP | `ae645875d595726a7fe30a0880c99fac464a2e34cb8fc86e96fd9a8d1f2c1e3e` |

用 Release 的校验表核对文件后解包。版本来自包内构建记录、运行库自身标识、PyInstaller 冻结模块清单和构建日志。两个桌面包均未发现 FFmpeg 或 FFprobe。更早的 `v0.2.0-preview.1` Mac 包含启用了 `--enable-nonfree` 的 FFmpeg 和 FFprobe，属于历史私测版本。FFmpeg 上游说明该构建不可再分发。 [FFmpeg 许可证说明](https://ffmpeg.org/doxygen/trunk/md_LICENSE.html)

## 两个桌面包共有的组件

| 实际组件 | 已随包提供 | 核对结论与对应来源 |
| --- | --- | --- |
| 项目及 Chrome 收集器 | 各自的 MIT 原文 | 收集器 ZIP 也带有 MIT。 |
| PostgreSQL 服务端 | `tools/postgres/LICENSE` 和 `SOURCE.txt` | Windows 为 17.12，Mac 为 18.6，均列明准确源码归档和 SHA-256。另有一份 PostgreSQL 客户端库来自 Psycopg wheel，版本见下表。 [PostgreSQL License](https://www.postgresql.org/about/licence/) |
| CPython 3.11.9 | `licenses/CPython.txt` | Python 及标准库许可已随包。静态并入标准扩展的组件和 Windows Microsoft 运行库需看各自条款。 [Python 3.11.9 官方发行](https://www.python.org/downloads/release/python-3119/) |
| PyInstaller 6.22.3 | `licenses/pyinstaller-6.22.3.txt` | 包含 GPL v2、引导程序例外和 Apache 2.0 全文。引导程序例外适用于打包到应用内的引导程序与相关文件，运行时钩子另用 Apache 2.0。 [官方许可说明](https://pyinstaller.org/en/stable/license.html) |
| Vue 3.5.41 及同版 Vue 运行时模块 | `licenses/vue.txt` | MIT，已附版权和许可。 [Vue 源码与许可](https://github.com/vuejs/core/tree/v3.5.41) |
| hls.js 1.7.1 | `licenses/hls.js.txt` | Dailymotion 和其引用的 Brightcove 版权均在文件中。Apache 2.0 全文在同包的 PyInstaller 许可文件中，后续可在本组件条目明确指向。 [hls.js 发行包](https://www.npmjs.com/package/hls.js/v/1.7.1) |
| certifi 2026.11.20 | `licenses/certifi-2026.11.20.txt` | MPL-2.0。已有许可原文，发布说明可直接给出本版本源码地址。 [certifi 本版本源码](https://pypi.org/project/certifi/2026.11.20/#files) |
| typing-extensions 4.16.0 | 冻结模块内有代码，许可目录中没有该组件许可 | 应从对应发行包附 PSF-2.0 许可及版权。 [typing-extensions 4.16.0](https://pypi.org/project/typing-extensions/4.16.0/) |
| psycopg 和 psycopg-binary 3.3.6 | 两份 LGPL v3 文本、部分生成的 C 文件 | 包里没有 LGPL v3 要求同时附带的 GPL v3 全文。Psycopg 主模块位于冻结归档中，尚未验证用户可替换兼容实现的路径，也未核对可重建该组合的对应源码和构建材料是否完整。 [Psycopg 3.3.6](https://github.com/psycopg/psycopg/tree/3.3.6) · [二进制 wheel](https://pypi.org/project/psycopg-binary/3.3.6/) · [LGPL v3 第 4 节](https://opensource.org/license/lgpl-3-0) |

## 平台随包组件

| 平台与实际组件 | 许可核对 |
| --- | --- |
| Mac 的 Psycopg wheel 带入 libpq 18.6、OpenSSL 3.5.8、OpenLDAP 2.6.14 和 MIT Kerberos 1.22.2 | libpq 版本用 `PQlibVersion()` 读回，OpenLDAP 版本由其 API 读回，OpenSSL 版本来自二进制，Kerberos 版本由该 wheel 的上游构建脚本确定。OpenSSL 3 使用 Apache 2.0。OpenLDAP 及 Kerberos 的版权、声明和许可原文应随再分发材料提供，实际包内未找到专属许可文件。 [Psycopg 构建脚本](https://github.com/psycopg/psycopg/blob/3.3.6/tools/ci/build_libpq.sh) · [OpenSSL 许可](https://openssl-library.org/source/license/index.html) · [OpenLDAP 许可](https://www.openldap.org/software/release/license.html) · [MIT Kerberos 许可](https://web.mit.edu/kerberos/krb5-latest/doc/mitK5license.html) |
| Windows 的 Psycopg wheel 带入 libpq 18.4、OpenSSL 3.6.4，Python 包另带 OpenSSL 3.0.13 | 三个版本由实际 DLL 的版本资源或版本字符串确认。应在第三方声明分别标明来源和适用通知。服务端 17.12 和 wheel 内的客户端 18.4 是不同构建。 [Psycopg Windows 构建脚本](https://github.com/psycopg/psycopg/blob/3.3.6/tools/ci/wheel_win32_before_build.bat) · [OpenSSL 许可](https://openssl-library.org/source/license/index.html) |
| Windows 的 tzdata 2026.6 | 冻结模块、时区数据目录和构建日志都确认其存在，数据标记为 IANA 2026f。发布时应附 Python 分发包的许可及版权，IANA 原始时区数据库为公有领域。 [tzdata 发行包](https://pypi.org/project/tzdata/2026.6/) · [IANA 时区数据库](https://data.iana.org/time-zones/tz-link.html) |
| 两个平台的 CPython 标准扩展 | 实际 `pyexpat` 含 Expat 2.6.0，Mac 的 `_lzma` 含 liblzma 5.2.3，Windows 包另有 `libffi-8.dll`、`_bz2.pyd` 和 `_lzma.pyd`。Windows 的 `CPython.txt` 已列 libffi 与 bzip2 的版权和许可。发布材料需检查其余组件的独立声明，尤其是 Expat 的 MIT 原文，并记录 Windows `_lzma` 的构建来源。 [CPython 对应源码](https://github.com/python/cpython/tree/v3.11.9) · [Expat 2.6.0](https://github.com/libexpat/libexpat/tree/R_2_6_0/expat) · [XZ Utils](https://tukaani.org/xz/) |
| Windows 的 Microsoft 运行库 | 实际包含 `VCRUNTIME140.dll` 14.38.33126.1、`ucrtbase.dll` 10.0.26100.1742 和 `api-ms-win-*.dll`。Windows 的 CPython 许可文件已有 Microsoft 代码附加条款。现有构建记录无法确认单独收集的 DLL 是否全部来自获准再分发的来源，也未核实面向接收者的条款是否覆盖 Microsoft 要求。可以确认来源及适用条款，或让用户按需要从 Microsoft 安装官方运行库并验证新包的首次启动。 [Microsoft 分发规定](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files) · [官方运行库下载](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) |

## 面向公开下载的剩余事项

1. 补齐 LGPL 对应的 GPL v3 全文，以及上表所列组件的版权和许可。为 Psycopg 验证允许用户替换兼容版本的打包方式，或提供构建该组合所需的对应源码和可重建材料。用新安装包验证数据库启动与重启读回。
2. 查明 Windows 单独 DLL 的再分发依据，或把 Microsoft 运行库改为用户从官方安装。选定方式后，在干净 Windows 环境实测。
3. 重新生成实际发给用户的安装包和校验表，再按包内文件核对一次。当前私有试用包的结果不能作为后续包的许可清单。

本次核对基于已发布的私有试用文件。该文件中的许可内容以实际安装包为准。
