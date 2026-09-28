"""Short error messages suitable for display; never include credentials."""

from __future__ import annotations

from urllib.error import HTTPError, URLError


def compact_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        return f"HTTP {error.code}：来源拒绝了请求"
    if isinstance(error, URLError):
        return f"连接失败：{error.reason}"
    return str(error).splitlines()[0][:180]
