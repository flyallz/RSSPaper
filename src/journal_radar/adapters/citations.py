"""Retrieve registered DOI metadata and publisher-supplied CSL formatted references."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from ..domain.papers import normalize_doi
from .abstracts import _title_key, abstract_text, resolve_doi
from .http import read_bytes

FORMATS = {"apa": "APA（作者—年份）", "bibtex": "BibTeX", "ris": "RIS（Zotero / EndNote）"}
ACCEPT = {
    "apa": "text/x-bibliography; style=apa; locale=en-US",
    "bibtex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
}


@dataclass(frozen=True)
class CitationResult:
    doi: str
    format: str
    text: str
    warnings: str = ""


def arxiv_doi(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in ("arxiv.org", "export.arxiv.org", "www.arxiv.org"):
        return ""
    match = re.fullmatch(
        r"/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?(?:\.pdf)?",
        parsed.path,
    )
    return "10.48550/arxiv." + match[1].lower() if match else ""


def fetch_citation(
    doi: str,
    title: str,
    url: str,
    format: str = "apa",
    proxy: str = "",
    cancelled: Callable[[], bool] | None = None,
) -> CitationResult:
    if format not in FORMATS:
        raise ValueError("引用格式不受支持")

    def check():
        if cancelled and cancelled():
            raise ValueError("引用查询已取消")

    check()
    doi = normalize_doi(doi) or normalize_doi(url) or arxiv_doi(url)
    if not doi:
        doi = resolve_doi("", title, proxy)
    check()
    endpoint = "https://doi.org/" + quote(doi, safe="/")
    metadata = json.loads(
        read_bytes(endpoint, proxy, accept="application/vnd.citationstyles.csl+json").decode(
            "utf-8-sig"
        )
    )
    if not isinstance(metadata, dict) or normalize_doi(str(metadata.get("DOI") or "")) != doi:
        raise ValueError("登记信息的 DOI 不一致，已停止生成引用")
    record_title = metadata.get("title") or ""
    if isinstance(record_title, list):
        record_title = record_title[0] if record_title else ""
    if not isinstance(record_title, str) or _title_key(record_title) != _title_key(title):
        raise ValueError("DOI 登记题名与当前论文不一致，请核对 DOI；未生成其他论文的引用")
    warnings = []
    if not metadata.get("author"):
        warnings.append("登记信息缺少作者，请核对是否为无署名文献")
    if not (metadata.get("issued") or {}).get("date-parts"):
        warnings.append("登记信息缺少发表年份，请核对")
    if metadata.get("type") == "article-journal" and not metadata.get("container-title"):
        warnings.append("登记信息缺少期刊名称，请核对")
    check()
    raw = read_bytes(endpoint, proxy, accept=ACCEPT[format]).decode("utf-8-sig").strip()
    check()
    if not raw or re.search(r"<(?:!doctype|html|head|body)\b", raw, re.I):
        raise ValueError("服务未返回有效引用，请重试或打开原文核对")
    if format == "bibtex" and not re.match(r"@\w+\s*\{", raw):
        raise ValueError("服务未返回有效 BibTeX")
    if format == "ris" and not (re.match(r"TY\s+-", raw) and re.search(r"^ER\s+-", raw, re.M)):
        raise ValueError("服务未返回有效 RIS")
    text = abstract_text(raw) if format == "apa" else raw
    if not text:
        raise ValueError("引用内容为空")
    return CitationResult(doi, format, text, "；".join(warnings))
