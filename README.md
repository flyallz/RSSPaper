# 教育技术期刊雷达

围绕《教育技术学》培养方案的期刊阅读小卡片。预置 **20 个 RSS**，覆盖可订阅的中文与英文期刊；第 21 本 *IEEE Transactions on Learning Technologies* 建议使用 IEEE Xplore Content Alerts。支持必读／选读、中文／英文筛选，自行增删改 RSS，以及调用用户配置的 Chat Completions 接口，把英文论文标题译成中文显示在原题下方。

| 平台 | 最新版本 | 打开方式 | 使用说明 |
|---|---|---|---|
| macOS 15+（Apple 芯片） | [v1.3](releases/macos/教育技术期刊雷达-Mac-v1.3.zip) | 解压并打开 `.app` | [Mac 说明](docs/桌面小卡片使用说明.md) |
| Windows 10/11 | [v1.3](releases/windows/教育技术期刊雷达-Windows-v1.3.zip) | 解压并双击 `Start-Radar.cmd` | [Windows 说明](docs/Windows使用说明.md) |
| Inoreader / Zotero | [OPML](data/edtech-radar.opml) | 导入订阅文件 | [订阅说明](docs/订阅说明.md) |

[所有已保留版本](releases/) 包括 Mac v1.0、v1.2、v1.3 和 Windows v1.2、v1.3；旧版仅供追溯，建议使用 v1.3。部分更早的中间构建没有完整安装包，因此没有补造版本。仓库还保留 [21 本期刊核对表](docs/21本期刊核对表.html)、[期刊目录](data/journal-catalog.json) 和 [验证记录](data/验证记录.json)。

## 源码与构建

- [Mac SwiftUI 源码](src/macos/main.swift)，通过 `scripts/build-macos.sh` 构建；`scripts/test-macos.sh` 用本地模拟接口检查翻译请求和错误处理。
- [Windows PowerShell/WPF 源码](src/windows/Radar.ps1)，与启动文件、预置订阅 JSON 放在同一目录即可运行。Windows 包尚未在本仓库维护者的 Windows 实机完成验证。
- 预置源及其核对依据位于 `data/`。生成的程序和源码不会包含用户 API 密钥。Mac 密钥保存在本机钥匙串；Windows 密钥使用当前用户的 Windows 加密存储。译题缓存及自定义订阅留在本机。

Mac 版在配有 Xcode Command Line Tools 的 macOS 上运行 `./scripts/build-macos.sh` 即可生成应用和 ZIP。构建采用临时签名；首次运行时请按 macOS 的提示自行决定是否打开。Windows 版使用系统自带的 Windows PowerShell 和 WPF，不需要另装 Python。

## 版本要点

- **v1.3：** DeepSeek `deepseek-flash` 使用非思考模式；Mac 测试接口显示具体 HTTP／网络错误，Windows 版显示 HTTP 状态。
- **v1.2：** Mac 增加标准“编辑 → 粘贴”菜单，API 地址及密钥可用 Command-V 输入；Windows 增加逐刊来源状态及外文 RSS 代理设置。
- **v1.0：** 最初的 Mac 置顶卡片，只读预置 RSS。

此仓库未包含任何用户个人 API 密钥、账户配置或翻译缓存。
