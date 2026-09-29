"""OpenAI-compatible translation transport; no cache or widgets here."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request

from ..config import MAX_DOWNLOAD, USER_AGENT
from ..domain.validation import valid_api_endpoint
from .http import build_http_opener


def contains_cjk(text: str) -> bool:
    chinese = sum("\u3400" <= char <= "\u9fff" for char in text)
    latin = sum(char.isascii() and char.isalpha() for char in text)
    # An isolated Chinese author name must not reverse an English abstract.
    return chinese > 0 and chinese / max(1, chinese + latin) >= 0.35


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
    cancelled: Callable[[], bool] | None = None,
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
    chunks = split_translation_text(title) if content_type == "abstract" else [title]
    translated = []
    for chunk in chunks:
        if cancelled and cancelled():
            raise TranslationCancelled()
        budget = max(2048, min(8192, len(chunk) * 3)) if content_type == "abstract" else 512
        translated.append(
            request_translation(
                chunk, instruction, endpoint, model, api_key, proxy, budget, cancelled
            )
        )
    if cancelled and cancelled():
        raise TranslationCancelled()
    return "\n\n".join(translated)


class TranslationCancelled(Exception):
    """A user cancelled a job; incomplete results must never enter the cache."""


def split_translation_text(text: str, limit: int = 1500) -> list[str]:
    """Prefer paragraph/sentence boundaries while retaining every input character."""
    parts = []
    remaining = text
    while len(remaining) > limit:
        boundaries = list(re.finditer(r"\n\n|(?<=[。！？.!?])\s+", remaining[:limit]))
        cut = boundaries[-1].end() if boundaries and boundaries[-1].end() > limit // 2 else limit
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        parts.append(remaining)
    return parts


def request_translation(
    text: str,
    instruction: str,
    endpoint: str,
    model: str,
    api_key: str,
    proxy: str,
    budget: int,
    cancelled: Callable[[], bool] | None,
) -> str:
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    for attempt in range(2):
        if cancelled and cancelled():
            raise TranslationCancelled()
        params = {
            "model": model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": text},
            ],
            "max_tokens": budget,
        }
        if urlparse(endpoint).hostname == "api.deepseek.com":
            params["thinking"] = {"type": "disabled"}
        request = Request(
            endpoint,
            data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with build_http_opener(proxy).open(request, timeout=30) as response:
                payload = response.read(MAX_DOWNLOAD + 1)
                if len(payload) > MAX_DOWNLOAD:
                    raise ValueError("翻译响应过大，已停止读取")
                result = json.loads(payload.decode("utf-8-sig"))
        except HTTPError as error:
            raise ValueError(f"接口返回 HTTP {error.code}，请检查密钥、余额或模型") from error
        if cancelled and cancelled():
            raise TranslationCancelled()
        choices = result.get("choices") or []
        choice = choices[0] if choices else {}
        reason = choice.get("finish_reason")
        if reason == "length":
            budget = min(16384, budget * 2)
            if attempt == 0:
                continue
            raise ValueError("译文达到输出上限，未保存不完整结果；请换用支持更长输出的模型后重试")
        if reason not in (None, "stop"):
            raise ValueError("模型未正常完成翻译，未保存结果（" + str(reason) + "）")
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("接口返回空译文；请检查模型输出设置")
        return content.strip()
    raise ValueError("翻译未完成")
