"""Validate user input without network or UI dependencies."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def valid_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def valid_api_endpoint(value: str) -> bool:
    parsed = urlparse(value.strip())
    return valid_http_url(value) and (
        parsed.scheme == "https" or parsed.hostname in ("localhost", "127.0.0.1", "::1")
    )


def normalize_issn(value: str) -> str:
    compact = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"\d{7}[\dX]", compact):
        raise ValueError("ISSN 应为 8 位，例如 0360-1315")
    checksum = sum(int(digit) * (8 - index) for index, digit in enumerate(compact[:7]))
    checksum += 10 if compact[-1] == "X" else int(compact[-1])
    if checksum % 11:
        raise ValueError("ISSN 校验位不正确，请检查数字")
    return compact[:4] + "-" + compact[4:]
