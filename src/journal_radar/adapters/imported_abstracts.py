"""Import an explicitly selected CSL/Zotero JSON record without online lookups."""

import json

from ..config import MAX_DOWNLOAD
from ..domain.papers import abstract_kind, normalize_doi
from .abstracts import AbstractResult, _title_key, abstract_text


def parse_imported_abstract(payload: bytes, title: str, url: str, doi: str = "") -> AbstractResult:
    if len(payload) > MAX_DOWNLOAD:
        raise ValueError("导入文件过大，请只导出需要补全的条目")
    data = json.loads(payload.decode("utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("items", [data])
    if not isinstance(data, list):
        raise ValueError("导入文件应为 CSL JSON 或 Zotero 条目 JSON")
    expected = normalize_doi(doi)
    matches = set()
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            item = item["data"]
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            continue
        if _title_key(item["title"]) != _title_key(title):
            continue
        record_doi = normalize_doi(str(item.get("DOI") or item.get("doi") or ""))
        record_url = item.get("URL") or item.get("url") or ""
        if expected and record_doi and expected != record_doi:
            continue
        if not (expected and record_doi == expected) and record_url != url:
            continue
        value = item.get("abstract") or item.get("abstractNote")
        text = abstract_text(value) if isinstance(value, str) else ""
        if abstract_kind(text) == "available":
            matches.add((text, record_doi or expected))
    if len(matches) != 1:
        raise ValueError(
            "没有唯一、题名和 DOI / 原文链接一致且包含完整摘要字段的条目；请确认导出格式包含摘要，未使用相似标题匹配"
        )
    text, resolved_doi = matches.pop()
    # A reference manager may itself have saved an RSS teaser: do not certify completeness.
    return AbstractResult(text, resolved_doi, "用户导入文献数据（完整性未确认）", "available")
