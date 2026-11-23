# 木易素材库安装与使用

## 1. 打开素材库

| 平台 | 文件 | 操作 |
| --- | --- | --- |
| Windows x64 | `MuyiMaterialLibrary-windows-x64.zip` | 先安装下方的微软官方运行库，再解压整个 ZIP，在解压后的目录双击 `MuyiMaterialLibrary.exe`。同目录的 `_internal` 与 `tools` 随程序保留。 |
| Apple 芯片 Mac | `MuyiMaterialLibrary-macOS-arm64.dmg` | 打开 DMG，把应用拖入「应用程序」，再双击打开。 |

Windows 首次使用前，请安装 **Microsoft Visual C++ v14 Redistributable x64**。如果已安装受支持的版本，直接打开素材库即可。出现 `VCRUNTIME140.dll` 或 `MSVCP140.dll` 缺失提示时，使用微软官方安装程序。 [微软说明](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) · [微软 x64 安装程序](https://aka.ms/vc14/vc_redist.x64.exe)

应用打开后进入本机网页。若浏览器没有自动打开，访问 `http://127.0.0.1:18778`。首次启动会创建空库，内置的 PostgreSQL 会随程序启动和退出，无需额外安装数据库或开发工具。试用包已在 Windows Server 2025 x64 与 macOS 15 Apple Silicon 的自动化环境验收。Windows 11 桌面双击、原生文件夹选择器和交互播放待真机验收。

建议从项目 Release 下载并核对随附的 SHA-256。Windows 试用包暂未签名，Mac 应用使用临时签名且未通过 Apple 公证。可信来源的 Mac 下载若被系统拦截，可在「系统设置 → 隐私与安全性」查看针对单个应用的「仍要打开」选项。

## 2. 需要导入本地文件或保存网页原件时，安装媒体工具

只收藏作品链接可以直接跳过这一步。扫描本地素材、生成预览和保存网页原件需要 FFmpeg 和 FFprobe。两者均由创作者从公开渠道自行安装。

- Windows 在 PowerShell 运行 `winget install --id Gyan.FFmpeg -e`。
- Apple 芯片 Mac 已有 Homebrew 时，在终端运行 `brew install ffmpeg-full`。该版本含视频预览所需的 H.264 编码器。
- 也可以从 [FFmpeg 官方下载页](https://ffmpeg.org/download.html) 选择平台构建。把 `ffmpeg` 和 `ffprobe` 放在同一个目录并加入 PATH，或通过环境变量 `MUYI_MEDIA_BIN` 指定那个目录。Mac 使用 Homebrew 的默认安装路径，Windows 可识别 WinGet 的链接目录。

装好后先退出再打开木易素材库。点击「添加来源」选择测试文件夹，等待扫描，原件会保留在原目录。

## 3. 安装和配对 Chrome 收集器

1. 解压 Release 的收集器 ZIP，或从 Mac DMG 复制 `Chrome Collector` 到本地。打开 Chrome 的 `chrome://extensions/`，打开「开发者模式」，点击「加载已解压的扩展程序」，选择包含 `manifest.json` 的目录。
2. 素材库用默认端口打开后，在「来源与设置 → 浏览器点选收集」复制配对令牌。进入扩展的选项页粘贴令牌并点击「保存并检查连接」。
3. 在网页按住 Windows 的 **Alt** 或 Mac 的 **Option** 左键点选图片或视频。也可点击扩展图标进入点选模式。回到素材库的「链接收集箱」查看原出处并添加标签、备注。
4. 抖音、小红书、X 的作品可以当作链接卡保存。若网页提供可读取的原始图片，点「保存原图」。可读取的直连视频可手动保存。短期媒体地址过期时，打开原作品并重新点选。链接卡可直接回到原作品页。

扩展需要读取网页上你点选的元素，因此 Chrome 会提示它可访问网页内容。采集时它把来源链接、标题以及能识别到的媒体地址发给本机素材库。配对令牌保存在 Chrome 本地扩展存储。扩展不提交浏览器 Cookie 或浏览历史。网页自己提供的分享链接可能包含访问参数，转发前先检查链接。

## 4. 数据、备份和卸载

在「来源与设置」中点击「退出素材库」。Windows 也可在启动窗口按 Ctrl+C。升级或备份前先退出。

- Windows 数据目录为 `%LOCALAPPDATA%\MuyiMaterialLibraryPreview`。
- macOS 数据目录为 `~/Library/Application Support/MuyiMaterialLibraryPreview`。

退出后备份整个数据目录。本地来源的原件留在你添加的文件夹里，也需要单独备份。恢复时使用同平台、同 PostgreSQL 主版本的软件，保持本地来源路径可用。排错日志为数据目录中的 `runtime/logs/server.log`、`postgres.log` 和 `postgres-launch.log`。

卸载时删除应用或 Windows 解压目录，在 Chrome 的扩展管理页移除收集器。需要继续保留素材库和整理记录时，请保留数据目录、备份及原文件。

## 5. 高级用法：更换 Psycopg

应用加载普通 Python 源文件。随附版本在 Windows 解压目录内的 `_internal/psycopg`，Mac 中在 `MuyiMaterialLibrary.app/Contents/Resources/MuyiMaterialLibrary/_internal/psycopg`。可以用另一个目录内接口兼容、支持 Python 3.14 的纯 Python Psycopg 启动。这个目录应包含 `psycopg/__init__.py`。应用仍使用随包的 PostgreSQL 客户端库。

如需比较或调试其他版本，可在终端用 `python -m pip install --no-deps --target <独立目录> psycopg==<版本>` 准备替换目录，退出素材库，然后从同一个终端启动：

```powershell
$env:MUYI_PSYCOPG_PATH = 'C:\path\to\replacement-driver'
.\MuyiMaterialLibrary.exe
```

```bash
MUYI_PSYCOPG_PATH="$HOME/muyi-replacement-driver" \
  /Applications/MuyiMaterialLibrary.app/Contents/MacOS/launcher
```

正常双击时使用应用自带版本。替换目录及其代码由本机使用者自行选择。
