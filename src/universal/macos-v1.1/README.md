# 期刊雷达 · 通用版 v1.4.0（Mac）

当前实现统一在 [src/journal_radar](../../journal_radar)，本目录保留兼容启动器与 Mac 打包规格。
Windows 和 Mac 的来源、筛选、卡片、摘要、翻译和配置逻辑共用同一套代码。

适用于 Apple 芯片 macOS 13+。从 Releases 获取已发布 ZIP，解压后将 JournalRadar.app 放入应用程序。
未签名/未公证的安装包可能需要在系统设置中允许打开。

数据保存在 ~/Library/Application Support/JournalRadar。已有 state.json 与译文缓存保持兼容；
密钥使用原 service/account 的系统钥匙串，改为原生 SecItem 调用。

从完整仓库根目录运行：

```sh
python -m pip install -r requirements-build.txt
python scripts/build-universal.py
```

测试、源码结构与发布说明见 [架构与维护文档](../../../docs/代码架构与维护说明.md)。
