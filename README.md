# 木易素材库 · Muyi Material Library

木易素材库是给创作者用的本地图片和视频管理工具，同一项目支持 Windows x64 和 Apple 芯片 Mac。把放参考图、生成图和剪辑片段的文件夹加入库，就能在一个页面预览、整理和搜索。素材原件保留在原目录，标签、备注和收藏保存在本机。

## 功能

- 添加一个或多个本地文件夹，浏览图片和视频。
- 给素材打标签、写备注、收藏或归入素材包，再用名称、标签和备注查找。
- 在 Chrome 按住 Windows 的 **Alt** 或 Mac 的 **Option** 点选网页上的图片或视频，保存作品链接到收集箱。抖音、小红书和 X 的作品可以按链接收藏并回到原出处。
- 网页提供可读取的原图时可一键保存。可读取的直连视频也可以手动保存，结果出现在「网页采集」来源中。

## 安装

在 [GitHub Releases](https://github.com/yimu86474-cpu/muyi-material-library/releases) 下载当前试用包、Chrome 收集器和中文说明。安装前以 Release 标明的版本和平台为准。

| 系统 | 软件包 | 启动 |
| --- | --- | --- |
| Windows x64 | `MuyiMaterialLibrary-windows-x64.zip` | 解压完整目录，双击 `MuyiMaterialLibrary.exe`。 |
| Apple 芯片 Mac | `MuyiMaterialLibrary-macOS-arm64.dmg` | 打开 DMG，把应用拖到「应用程序」，再双击打开。 |

应用自带 PostgreSQL，首次打开是一个空库。仅收藏网页链接时可以直接使用。要导入文件夹、生成预览或保存网页原件，请按说明自行安装 FFmpeg 和 FFprobe，随后重启素材库。备份、卸载、运行要求和收集器配对见 [安装与使用](docs/INSTALL.zh-CN.md)。

## 开发与反馈

前端使用 Vue 和 Vite，Python 服务在本机运行，PostgreSQL 保存索引。[独立版开发说明](docs/STANDALONE.md) 包含源码启动、打包和隔离验收命令。

遇到问题可在 [Issues](https://github.com/yimu86474-cpu/muyi-material-library/issues) 提交操作系统、版本、复现步骤和已去除个人信息的日志片段。

项目代码与收集器采用 [MIT 许可证](LICENSE)。安装包内的依赖适用各自的 [第三方许可](THIRD_PARTY_NOTICES.md)。
