"""Construct sources and apply second-layer keyword filters."""

from __future__ import annotations

import re
import uuid

from .models import Paper, Source
from .validation import normalize_issn, valid_http_url


def _keyword_list(value: str | list[str]) -> list[str]:
    values = value if isinstance(value, list) else re.split(r"[,，;；\n]+", value)
    return list(dict.fromkeys(part.strip() for part in values if part.strip()))


def create_source(
    name: str,
    kind: str,
    value: str,
    include_keywords: str | list[str] = "",
    exclude_keywords: str | list[str] = "",
    match_all: bool = False,
) -> Source:
    name, value = name.strip(), value.strip()
    if not name:
        raise ValueError("请填写期刊名称")
    if kind == "rss":
        if not valid_http_url(value):
            raise ValueError("RSS 地址必须以 http:// 或 https:// 开头")
    elif kind == "crossref":
        value = normalize_issn(value)
    elif kind == "arxiv":
        if not value:
            raise ValueError("请填写 arXiv 分类或检索式")
        if re.fullmatch(r"[A-Za-z-]+(?:\.[A-Za-z-]+)?", value):
            value = "cat:" + value
    else:
        raise ValueError("不支持的来源类型")
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "kind": kind,
        "value": value,
        "enabled": True,
        "include_keywords": _keyword_list(include_keywords),
        "exclude_keywords": _keyword_list(exclude_keywords),
        "match_all": bool(match_all),
    }


def paper_matches_source(paper: Paper, source: Source) -> bool:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).casefold()
    includes = [
        str(value).casefold() for value in source.get("include_keywords", []) if str(value).strip()
    ]
    excludes = [
        str(value).casefold() for value in source.get("exclude_keywords", []) if str(value).strip()
    ]
    if any(value in text for value in excludes):
        return False
    if not includes:
        return True
    matches = [value in text for value in includes]
    return all(matches) if source.get("match_all") else any(matches)
