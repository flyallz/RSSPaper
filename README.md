# RSSPaper · 期刊雷达

跨学科论文订阅工具，支持 Windows 和 Apple 芯片 Mac。可建立多个学科工作区，
订阅 RSS/Atom、Crossref ISSN 或 arXiv 检索来源，按标题和摘要设置包含/排除关键词，
展开摘要，并按需进行中文与英文的标题、摘要翻译。

已发布安装包见 [GitHub Releases](https://github.com/flyallz/RSSPaper/releases)。
当前源码进入 v1.4.0：Windows 和 Mac 共用一套实现，历史版本入口继续保留。
正式安装包以 Releases 页面为准，未发布的源码版本不代表已有对应正式安装包。

## 使用与数据

- Windows：解压完整 ZIP，运行 JournalRadar/JournalRadar.exe，保留 _internal 文件夹。
- Mac：解压 ZIP，将 JournalRadar.app 放入应用程序。当前构建面向 Apple 芯片 macOS 13+。
- 点击“新建学科”和“管理期刊来源”添加订阅，也可导入 OPML。
- 网络代理、翻译接口、模型与刷新间隔在“翻译与网络设置”配置。
- 翻译仅在用户点击时请求第三方接口，可能产生费用；用户自行填写有效模型名称。
- 中文标题/摘要可译为英文，其他标题/摘要可译为中文。来源没有完整摘要时，程序不会补造摘要。
- 来源只有月份/年份的日期会保留原始精度；近 7/30 天筛选仅包括精确日期。

Windows 数据位于 %APPDATA%/JournalRadar；Mac 位于 ~/Library/Application Support/JournalRadar。
两端配置文件保持 schema 1 兼容。密钥分别使用 Windows DPAPI、Mac 钥匙串保存，
不能通过复制 state.json 跨平台迁移密钥。损坏配置的会话禁止覆盖原文件。

## 当前代码与开发

公共实现位于 src/journal_radar，分为界面、业务、来源接入、领域模型、存储与平台模块。
src/universal/v1.1 和 macos-v1.1 是兼容启动入口与平台打包规格，不再各自维护业务代码。

- [架构与维护说明](docs/代码架构与维护说明.md)：模块职责、数据兼容、会议来源扩展步骤。
- [贡献约定](CONTRIBUTING.md)：代码组织与合并前检查。
- [v1.4.0 变更](docs/版本说明-v1.4.0.md)。

在 Python 3.12/3.13 虚拟环境中安装根目录 requirements-build.txt 后：

```sh
PYTHONPATH=src python -m journal_radar
python -m ruff check .
python -m ruff format --check .
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
python scripts/build-universal.py
```

Windows PowerShell 环境变量写法、平台测试与发布步骤见维护说明。
构建产物和 SHA-256 位于 dist/artifacts。GitHub Actions 在 Mac 和 Windows 上检查、测试、打包，
发布流程手动触发并默认生成草稿。正式代码签名和 Apple 公证仍需要开发者证书。

## 历史资料

原 Mac SwiftUI 源码在 src/macos；原 Windows PowerShell/WPF 源码在 src/windows 和 src/legacy。
原通用版 v1.0 快照在 src/universal/v1.0。历史安装包保留在 releases 中，新安装包由构建产出。

原教育技术培养方案资料仍可使用：

- [OPML 订阅清单](data/edtech-radar.opml)
- [订阅说明](docs/订阅说明.md)
- [21 本期刊核对表](docs/21本期刊核对表.html)
- [期刊目录](data/journal-catalog.json)

仓库不包含真实用户 API 密钥、个人配置或论文缓存。
