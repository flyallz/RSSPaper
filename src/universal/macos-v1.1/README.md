# 期刊雷达 · 通用版 v1.1（Mac）

这是 Windows 通用版 v1.1 的 Mac 对应版本，界面和工作区、RSS/Atom、Crossref ISSN、OPML、刷新、日期精度与按需翻译功能保持一致。它不会预设某一学科的期刊。

## 使用

解压 `JournalRadar-Universal-v1.1-Mac-arm64.zip`，将 `JournalRadar.app` 放入“应用程序”并打开。适用于 Apple 芯片的 macOS 13 或更新版本。首次打开未公证的应用时，macOS 可能要求你在“系统设置 → 隐私与安全性”中决定是否允许打开。

点击“＋ 新建学科”建立工作区，在“管理期刊来源”中添加 RSS 地址或 ISSN，也可导入 OPML。仓库的 `data/edtech-radar.opml` 可作为教育技术工作区的起点。添加或修改来源后会立即刷新；开启自动刷新时，默认每 30 分钟检查一次，程序关闭后不在后台运行。

英文标题仅在点击“译为中文”时发送到你设置的接口。DeepSeek 可填写完整地址 `https://api.deepseek.com/chat/completions`，模型 `deepseek-flash`；点击“测试翻译”检查配置。密钥存入当前用户的 macOS 钥匙串，不写入应用数据文件。

数据位于 `~/Library/Application Support/JournalRadar/state.json`。旧版教育技术 Mac 卡片不会被覆盖，也不会自动迁移；可通过 OPML 导入来源。若从 Windows 通用版迁移，关闭两端程序后可以复制 `%APPDATA%\JournalRadar\state.json` 到上述目录，工作区、来源和论文缓存格式兼容。Windows DPAPI 加密的密钥不能复制到 Mac，请在 Mac 上重新输入。复制数据后检查代理地址是否仍适用。

没有稳定 RSS 的期刊可用 Crossref ISSN 来源；该来源和译题缓存存在应用配置中，OPML 只导出 RSS 来源。近 7/30 天只列出有精确日期的论文，仅有月份或年份的条目可在“全部时间”查看。

## 从源码构建

在 Mac 上创建 Python 3.12 或 3.13 虚拟环境，安装本目录 `requirements.txt`，然后从仓库根目录运行 `PYTHON=/path/to/venv/bin/python bash scripts/build-universal-macos.sh`。脚本运行核心测试、生成图标、打包并检查应用，最后生成 ZIP。`JOURNAL_RADAR_HOME` 可指向临时目录供测试使用。

这个 ZIP 未经 Apple Developer ID 签名或公证；分发时如需无提示安装，应由开发者用自己的证书签名并公证。
