"""Crossref abstract lookup. No publisher-page scraping or institutional login.

Absent DOI: accept only one exact normalized title match, never the first
search result. Public metadata availability is independent of campus access.
"""

from __future__ import annotations

import html
import json
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import quote, urlencode

from ..domain.papers import abstract_kind, normalize_doi
from .http import read_bytes


class _AbstractText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.rsplit(":", 1)[-1] in ("p", "title", "sec", "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        self.handle_starttag(tag, [])


def abstract_text(value: str) -> str:
    parser = _AbstractText()
    parser.feed(value)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    lines = [line for line in lines if line]
    if lines and lines[0].casefold() in ("abstract", "摘要"):
        lines.pop(0)
    return "\n\n".join(lines)


def _title_key(value: str) -> str:
    text = abstract_text(html.unescape(value))
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


@dataclass(frozen=True)
class AbstractResult:
    text: str
    doi: str
    source: str = "Crossref"


def _message(url: str, proxy: str) -> dict:
    try:
        payload = json.loads(read_bytes(url, proxy).decode("utf-8-sig"))
    except HTTPError as error:
        if error.code == 404:
            raise ValueError("Crossref 未收录该 DOI；校园网不会改变此接口的结果。") from error
        raise
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict):
        raise ValueError("Crossref 返回的数据格式无效，请稍后重试。")
    return message


def fetch_abstract(doi: str, title: str, proxy: str = "") -> AbstractResult:
    doi = normalize_doi(doi)
    if not doi:
        key = _title_key(title)
        if not key:
            raise ValueError("论文没有 DOI 或有效标题，无法查询摘要。")
        query = urlencode({"query.bibliographic": title, "rows": 5, "select": "DOI,title"})
        items = _message("https://api.crossref.org/works?" + query, proxy).get("items", [])
        matches = set()
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            titles = item.get("title") or []
            candidate = normalize_doi(str(item.get("DOI") or ""))
            if (
                candidate
                and isinstance(titles, list)
                and any(isinstance(value, str) and _title_key(value) == key for value in titles)
            ):
                matches.add(candidate)
        if len(matches) != 1:
            raise ValueError("没有唯一且标题一致的 DOI 匹配，已保留现有内容；可打开原文查看摘要。")
        doi = matches.pop()
    message = _message("https://api.crossref.org/works/" + quote(doi, safe=""), proxy)
    if normalize_doi(str(message.get("DOI") or "")) != doi:
        raise ValueError("返回的 DOI 与论文不一致，已停止补全。")
    value = message.get("abstract")
    text = abstract_text(value) if isinstance(value, str) else ""
    kind = abstract_kind(text)
    if kind == "missing":
        raise ValueError("出版社未向 Crossref 提供摘要；可打开原文查看，后续需接入出版社授权接口。")
    if kind != "available":
        raise ValueError("Crossref 仅提供片段或出版信息，无法确认完整摘要，已保留现有内容。")
    return AbstractResult(text, doi)
