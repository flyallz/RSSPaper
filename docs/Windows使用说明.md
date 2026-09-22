# 教育技术期刊雷达 · Windows 桌面小卡片

适用于 Windows 10/11。解压整个文件夹后，双击 **`Start-Radar.cmd`**。它会打开一个置顶小窗口；窗口开着时每 30 分钟更新一次，也可以点“刷新”。双击论文条目打开原文。请把文件夹中的 `Radar.ps1` 和 `feeds.default.json` 留在一起。

点“设置”→“RSS 订阅”，可以选中现有期刊修改名称或地址，也能新增、删除及恢复预置的 20 本。更改会保存在当前 Windows 用户的 `%APPDATA%\EdTechRadar` 中，重新打开仍在。恢复预置会替换整个自定义列表。

如果英文期刊没有显示，先在主窗口右上角把语言切到“英文”，再点“来源”查看每本期刊的读取结果。新版状态栏还会显示成功读取的英文期刊数。若外文站点连接失败，可在“设置”→“RSS 订阅”底部填写你已有的本地 HTTP 代理地址（例如 `http://127.0.0.1:7890`）并点“保存代理”；该代理只用于外文 RSS，中文 RSS 仍走系统网络。留空则使用系统网络设置。


点“设置”→“大模型翻译”，填写兼容 OpenAI Chat Completions 的**完整接口地址**、模型名称和 API 密钥，先点“测试接口”，再勾选启用并保存。支持 HTTPS 地址；本机模型也可使用 `http://localhost` 或 `http://127.0.0.1`，且可不填密钥。DeepSeek 可使用 `https://api.deepseek.com/chat/completions` 和 `deepseek-flash`；新版会关闭该接口的思考模式，并在测试失败时显示 HTTP 状态。开启后，小卡片只把屏幕中出现的英文标题发送到该接口；英文原题保留，中文译题显示在下面。译题会缓存，接口可能按调用量收费。密钥采用 Windows 当前用户的加密存储方式保存在本机。关闭翻译开关后不会继续发送标题。

预置 RSS 覆盖培养方案中有可用 RSS 的 20 本期刊；IEEE Transactions on Learning Technologies 建议使用 IEEE Xplore 的 Content Alerts。CNKI 文章页面可能需要机构权限。小卡片显示的是各 RSS 当前可见的条目，不保证覆盖过去七天的全部论文。

这个 Windows 包使用系统自带的 Windows PowerShell 和 WPF，不需要另外安装 Python 或大模型软件。若单位电脑禁止运行 PowerShell 脚本，请联系设备管理员处理；不要更改单位安全策略。当前交付环境是 Mac，已检查脚本结构、窗口布局文件、20 个预置地址和压缩包，但尚未在 Windows 实机运行。
