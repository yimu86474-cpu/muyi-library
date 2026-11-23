# 木易素材库

**给 AI 视频、剪辑和视觉创作者用的本地素材库。**

做分镜时，想找回上周的一张参考图、一个运镜片段，或者一条看过的作品链接？把常用素材文件夹加进来，给值得留下的参考写个标签或备注，下次按关键词就能找回来。

[下载 Windows x64][windows] · [下载 Apple 芯片 Mac][mac] · [下载 Chrome 收集器][collector] · [中文安装说明](docs/INSTALL.zh-CN.md)

## 用它整理什么

- **本地参考。** 在一个页面预览图片和视频。可以打标签、写备注、收藏，或归入某个项目的素材包。原件留在原文件夹，索引和整理记录保存在本机。
- **网页上的灵感。** 安装 Chrome 收集器后，按住 Windows 的 **Alt** 或 Mac 的 **Option** 点选素材。抖音、小红书和 X 的作品可以先收藏为链接，之后从「链接收集箱」回到原出处。
- **需要留底的原件。** 网页提供可读取的原图时可一键保存，可读取的直连视频可手动保存。媒体是否可保存取决于网页提供的地址。

## 第一次打开

| 你的电脑 | 怎么开始 |
| --- | --- |
| Windows x64 | 安装 [微软 Visual C++ x64 运行库][vc-runtime]，解压 [Windows ZIP][windows]，双击 `MuyiMaterialLibrary.exe`。 |
| Apple 芯片 Mac | 打开 [Mac DMG][mac]，把应用拖到「应用程序」后打开。 |

打开后会出现一个本地空库，数据库随应用一起提供。你可以选一个常用工作流开始：

1. **先收链接。** 按 [收集器配对步骤](docs/INSTALL.zh-CN.md#3-安装和配对-chrome-收集器) 配对 Chrome 扩展。挑一条想留作参考的作品，点选后到「链接收集箱」查看。
2. **先整理本地文件。** 按 [媒体工具安装说明](docs/INSTALL.zh-CN.md#2-需要导入本地文件或保存网页原件时安装媒体工具) 装好 FFmpeg 和 FFprobe，重启素材库，然后点「添加来源」，选一个装着参考图或视频的文件夹。

当前是**公开测试版**。空库启动、图片和视频导入、退出重启后的读回已在 Windows Server 2025 x64 和 Apple 芯片 macOS 15 的托管环境验证。Windows 包暂未签名，Mac 包使用临时签名且未公证。挂载、首次打开和备份见 [完整安装说明](docs/INSTALL.zh-CN.md)。安装包校验值在 [Release][release]。

## 开发、反馈与许可

- [从源码运行或构建 Windows 与 Mac 版本](docs/STANDALONE.md)
- [报告问题或建议功能][issues]
- 项目代码和 Chrome 收集器采用 [MIT](LICENSE)，安装包中的依赖适用各自的 [第三方许可证](THIRD_PARTY_NOTICES.md)。

[release]: https://github.com/yimu86474-cpu/muyi-library/releases/tag/v0.2.3-preview.1
[windows]: https://github.com/yimu86474-cpu/muyi-library/releases/download/v0.2.3-preview.1/MuyiMaterialLibrary-windows-x64.zip
[mac]: https://github.com/yimu86474-cpu/muyi-library/releases/download/v0.2.3-preview.1/MuyiMaterialLibrary-macOS-arm64.dmg
[collector]: https://github.com/yimu86474-cpu/muyi-library/releases/download/v0.2.3-preview.1/MuyiMaterialLibrary-chrome-collector-v0.5.1.zip
[issues]: https://github.com/yimu86474-cpu/muyi-library/issues
[vc-runtime]: https://aka.ms/vc14/vc_redist.x64.exe
