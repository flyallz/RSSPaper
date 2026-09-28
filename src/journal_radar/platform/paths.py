"""The small set of platform-dependent paths and presentation defaults."""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("JOURNAL_RADAR_HOME")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "JournalRadar"
    base = os.environ.get("APPDATA")
    return Path(base) / "JournalRadar" if base else Path.home() / ".journal-radar"


def legacy_feed_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "EdTechRadar" / "feeds.json"
    return data_dir() / "feeds.json"


def platform_name() -> str:
    return "macOS" if sys.platform == "darwin" else "Windows"


def default_font() -> str:
    return "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"


def secret_storage_description() -> str:
    storage = "此 Mac 的钥匙串" if sys.platform == "darwin" else "本机（Windows 当前用户加密）"
    return f"密钥保存在{storage}；本地翻译接口可留空。"
