"""OpenAI-compatible translation transport; no cache or widgets here."""

from __future__ import annotations

import hashlib
import json
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request

from ..config import MAX_DOWNLOAD, USER_AGENT
from ..domain.validation import valid_api_endpoint
from .http import build_http_opener


def contains_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def translation_key(endpoint: str, model: str, title: str, target_language: str = "zh") -> str:
    return hashlib.sha256(
        (endpoint + "|" + model + "|" + target_language + "|" + title).encode("utf-8")
    ).hexdigest()


def translate_title(
    title: str,
    endpoint: str,
    model: str,
    api_key: str,
    proxy: str = "",
    target_language: str = "zh",
    content_type: str = "title",
) -> str:
    if not valid_api_endpoint(endpoint) or not model:
        raise ValueError("请在设置中填写翻译接口和模型")
    if not api_key and urlparse(endpoint).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("远程翻译接口需要 API 密钥")
    subject = "摘要" if content_type == "abstract" else "标题"
    instruction = (
        f"将学术论文{subject}准确翻译为英文。只返回英文译文，不加解释。"
        if target_language == "en"
        else f"将学术论文{subject}准确翻译为简体中文。只返回译文，不加解释。"
    )
    params: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": title},
        ],
        "max_tokens": 180,
    }
    if urlparse(endpoint).hostname == "api.deepseek.com":
        params["thinking"] = {"type": "disabled"}
        params["max_tokens"] = 256
    payload = json.dumps(params, ensure_ascii=False).encode("utf-8")
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with build_http_opener(proxy).open(request, timeout=30) as response:
            result = json.loads(response.read(MAX_DOWNLOAD).decode("utf-8-sig"))
    except HTTPError as error:
        raise ValueError(f"接口返回 HTTP {error.code}，请检查密钥、余额或模型") from error
    choices = result.get("choices") or []
    content = str((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not content:
        raise ValueError("接口返回空译文；请检查模型输出设置")
    return content
