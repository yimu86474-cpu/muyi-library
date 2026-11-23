# 木易素材库独立版开发

普通用户请从项目 Release 下载平台软件包，查看 [安装与使用](INSTALL.zh-CN.md)。本页供维护者从源码启动、打包和验证。

## 源码启动

准备 Python 3.11、Node.js 24 和 PostgreSQL 二进制。需要测试图片、视频处理时，另在本机安装 FFmpeg 和 FFprobe。首次运行请把 `--data-dir` 指向单独的测试目录。

### Apple 芯片 Mac

```bash
python3.11 -m venv .venv-standalone
.venv-standalone/bin/python -m pip install 'psycopg[binary]==3.3.6'
npm --prefix frontend ci
npm --prefix frontend run build
.venv-standalone/bin/python -m material_library.standalone \
  --postgres-bin "$(pg_config --bindir)" --data-dir "$PWD/.standalone-test"
```

### Windows x64

```powershell
py -3.11 -m venv .venv-standalone
$python = ".\.venv-standalone\Scripts\python.exe"
& $python -m pip install 'psycopg[binary]==3.3.6'
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
& $python -m material_library.standalone --postgres-bin 'C:\path\to\PostgreSQL\bin' --data-dir "$PWD\.standalone-test"
```

`--postgres-bin` 指向包含 `initdb`、`pg_ctl` 和 `postgres` 的目录。程序会初始化和启停自己的数据库。调试时可通过 `--port 0` 获取随机端口，收集器配对使用默认端口 18778。

## 打包和验收

[GitHub Actions 工作流](../.github/workflows/windows-preview.yml) 构建同一提交的 Windows x64 和 Apple 芯片 Mac 包，包含独立 PostgreSQL。工作流中列明构建工具版本、脚本顺序和测试产物。Windows 使用 MSVC 和 Meson，Mac 使用 Xcode 命令行工具和 Make。Windows 包由微软官方运行库提供所需 DLL，验收工作流会独立下载并验证微软签名。两边的构建脚本从 PostgreSQL 官方归档下载对应源码并校验 SHA-256。

`scripts/smoke_standalone.py` 在新测试目录中运行。它验证无媒体工具时的链接收藏、安装工具后的图片和视频导入、缩略图、视频分段读取、原件字节、重启读回及数据库退出。例：

```powershell
& $python scripts/smoke_standalone.py --launcher 'C:\test-builds\MuyiMaterialLibrary\MuyiMaterialLibrary.exe' --work 'C:\test-runs\standalone-01' --media-bin 'C:\test-tools\ffmpeg\bin' --check-no-tools
```

Chrome 收集器的解析测试通过 `node --test chrome-extension/tests/*.test.mjs` 运行。发布验收还需在实际桌面双击启动、添加文件夹、预览图片和播放视频。

打包使用纯 Python 的 `psycopg`，它与源码开发环境的可选 `psycopg[binary]` 安装方式相互独立。PyInstaller 将 Psycopg 源文件放在 `_internal/psycopg`，驱动加载随 PostgreSQL 服务端一起编译的 libpq。安装包验收在首次启动后，用单独目录里的替换驱动重启并核对数据。替换步骤见 [安装说明](INSTALL.zh-CN.md#5-高级用法更换-psycopg)。

## 本机排错

退出正在运行的同一数据目录实例后再启动。查看测试数据目录的 `runtime/logs/server.log`、`postgres.log` 和 `postgres-launch.log`。试用包支持 `--media-bin` 显式指定 FFmpeg 与 FFprobe 所在目录，也支持 `MUYI_MEDIA_BIN`。
