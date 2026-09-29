"""Verified HTTP transport with response limits and bounded retry."""

from __future__ import annotations

import ssl
import time
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

import certifi

from ..config import MAX_DOWNLOAD, USER_AGENT
from ..domain.validation import valid_http_url


def build_http_opener(proxy: str):
    if proxy:
        if not valid_http_url(proxy):
            raise ValueError("代理地址必须以 http:// 或 https:// 开头")
        proxy_handler = ProxyHandler({"http": proxy, "https": proxy})
    else:
        proxy_handler = ProxyHandler()
    context = ssl.create_default_context(cafile=certifi.where())
    return build_opener(proxy_handler, HTTPSHandler(context=context))


def read_bytes(url: str, proxy: str, timeout: int = 22, accept: str = "") -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept
            or "application/rss+xml, application/atom+xml, application/json, application/xml, text/xml, */*",
        },
    )
    last_error = None
    for attempt in range(3):
        try:
            with build_http_opener(proxy).open(request, timeout=timeout) as response:
                payload = response.read(MAX_DOWNLOAD + 1)
            break
        except HTTPError as error:
            last_error = error
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            delay = min(5, int(error.headers.get("Retry-After", "0") or 0) or (attempt + 1))
            time.sleep(delay)
    else:
        raise last_error or ValueError("来源读取失败")
    if len(payload) > MAX_DOWNLOAD:
        raise ValueError("来源文件过大，已停止读取")
    if b"Making sure you&#39;re not a bot" in payload or b"Making sure you're not a bot" in payload:
        raise ValueError("来源站点要求浏览器验证，暂时无法自动读取；请稍后重试")
    return payload
