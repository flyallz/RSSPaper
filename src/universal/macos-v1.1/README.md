# 期刊雷达 · 通用版 v1.3.2（Mac）

这是跨学科通用版的 Mac v1.2。它修复了 Mac 安装包缺少可信 CA 证书、HTTPS RSS 无法刷新的问题，并统一了学科选择和来源编辑界面。除 RSS/Atom、Crossref ISSN、OPML 与按需翻译外，现在还支持 arXiv 主题检索及标题/摘要的第二层关键词过滤。

## 使用

解压 `JournalRadar-Universal-v1.3.2-Mac-arm64.zip`，将 `JournalRadar.app` 放入“应用程序”并打开。适用于 Apple 芯片的 macOS 13 或更新版本。首次打开未公证的应用时，macOS 可能要求你在“系统设置 → 隐私与安全性”中决定是否允许打开。

点击“＋ 新建学科”建立工作区，在“管理期刊来源”中添加 RSS 地址或 ISSN，也可导入 OPML。仓库的 `data/edtech-radar.opml` 可作为教育技术工作区的起点。添加或修改来源后会立即刷新；开启自动刷新时，默认每 30 分钟检查一次，程序关闭后不在后台运行。

英文标题仅在点击“译为中文”时发送到你设置的接口。DeepSeek 可填写完整地址 `https://api.deepseek.com/chat/completions`，模型 `deepseek-flash`；点击“测试翻译”检查配置。密钥存入当前用户的 macOS 钥匙串，不写入应用数据文件。

数据位于 `~/Library/Application Support/JournalRadar/state.json`。旧版教育技术 Mac 卡片不会被覆盖，也不会自动迁移；可通过 OPML 导入来源。若从 Windows 通用版迁移，关闭两端程序后可以复制 `%APPDATA%\JournalRadar\state.json` 到上述目录，工作区、来源和论文缓存格式兼容。Windows DPAPI 加密的密钥不能复制到 Mac，请在 Mac 上重新输入。复制数据后检查代理地址是否仍适用。

没有稳定 RSS 的期刊可用 Crossref ISSN 来源；该来源和译题缓存存在应用配置中，OPML 只导出 RSS 来源。近 7/30 天只列出有精确日期的论文，仅有月份或年份的条目可在“全部时间”查看。

## 主题雷达与关键词过滤

添加来源时可选择“arXiv 主题检索”。只填 `cs.HC` 会自动转换为 `cat:cs.HC`；也可填写 arXiv 检索式，例如 `cat:cs.HC AND all:"augmented reality"`。程序按提交时间读取最新论文，并显示摘要片段。

RSS、Crossref 和 arXiv 来源都可以设置“二层包含关键词”和“排除关键词”。关键词用逗号分隔，默认命中任意一个即保留；勾选“必须同时包含全部关键词”后改为全部命中。匹配范围包括英文或中文标题及摘要。因此可以先订阅一个较宽的来源，再用研究方向收窄为持续更新的主题论文流。

## 从源码构建

在 Mac 上创建 Python 3.12 或 3.13 虚拟环境，安装本目录 `requirements.txt`，然后从仓库根目录运行 `PYTHON=/path/to/venv/bin/python bash scripts/build-universal-macos.sh`。脚本运行核心测试、生成图标、打包并检查应用，最后生成 ZIP。`JOURNAL_RADAR_HOME` 可指向临时目录供测试使用。

这个 ZIP 未经 Apple Developer ID 签名或公证；分发时如需无提示安装，应由开发者用自己的证书签名并公证。
