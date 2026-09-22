# RSSPaper · 期刊雷达

原项目是围绕《教育技术学》培养方案的期刊阅读小卡片，保留原有 Mac、Windows 和 OPML 版本。本次新增跨学科 Windows 通用版：可为不同学科建立工作区，订阅 RSS/Atom 或 Crossref ISSN 来源，自定义刷新间隔，并在点击论文按钮后才翻译英文标题。

| 平台 | 推荐版本 | 下载与说明 |
| --- | --- | --- |
| Windows 10/11 · 跨学科 | 通用版 v1.1 | [Windows 版本合集](https://github.com/flyallz/RSSPaper/releases/tag/v1.1)；解压 ZIP，运行 `JournalRadar/JournalRadar.exe` |
| Windows 10/11 · 教育技术 | PowerShell 版 v1.5 | [Windows 版本合集](https://github.com/flyallz/RSSPaper/releases/tag/v1.1)；解压 ZIP，运行 `Start-Radar.cmd` |
| macOS 15+（Apple 芯片） | [v1.3](releases/macos/教育技术期刊雷达-Mac-v1.3.zip) | [Mac 说明](docs/桌面小卡片使用说明.md) |
| Inoreader / Zotero | [OPML](data/edtech-radar.opml) | [订阅说明](docs/订阅说明.md) |

Windows 历史版本的代码分别位于 `src/legacy/v1.2`～`v1.5`；跨学科通用版位于 `src/universal/v1.0`、`v1.1`。原 Mac v1.0、v1.2、v1.3 安装包仍保存在 `releases/macos/`，源码在 `src/macos/`；Windows v1.2、v1.3 原安装包仍保存在 `releases/windows/`。原有 [21 本期刊核对表](docs/21本期刊核对表.html)、[期刊目录](data/journal-catalog.json) 与 [验证记录](data/验证记录.json) 未改动。

## 日期修复（Windows 通用版 v1.1）

ScienceDirect 的部分 RSS 条目不提供独立日期标签，而是在简介中写 `Publication date: January 2027` 或 `Publication date: Available online 28 August 2026`。v1.1 会识别这两种格式：前者只显示月份，不虚构具体某一天；后者显示精确在线发表日期。Crossref 仅提供月份或年份时也保留原始精度。近 7/30 天筛选只针对有精确日期的论文；仅有月份的论文可在“全部时间”查看。升级后点击“刷新来源”即可更新现有缓存和日期，不影响已保存的标题翻译。

## 各版源码与构建

- Mac SwiftUI 源码：`src/macos/main.swift`；`scripts/build-macos.sh` 构建，`scripts/test-macos.sh` 测试。
- 原 Windows PowerShell/WPF 源码：`src/windows/`；各历史快照在 `src/legacy/`。
- 通用 Windows Python/PySide6 源码：`src/universal/`；v1.1 的构建说明在 `src/universal/v1.1/BUILD.txt`。GitHub Actions 的 Windows 工作流用于生成所有 Windows 版本的下载 ZIP。

本仓库只包含程序源码、默认订阅清单和构建配置，不包含用户 API 密钥、个人配置、缓存论文或日志。通用版默认数据位于 `%APPDATA%\JournalRadar`，原版位于 `%APPDATA%\EdTechRadar`，互不覆盖。翻译请求只在用户点击按钮时发送，第三方接口可能收费。
