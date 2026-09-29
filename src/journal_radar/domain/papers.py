"""Normalize papers and preserve the date precision supplied by publishers."""

from __future__ import annotations

import hashlib
import re
from datetime import date as calendar_date
from datetime import timedelta
from urllib.parse import unquote, urlparse

from .models import Paper, Source


def abstract_kind(text: str) -> str:
    """Classify what the source actually supplied, not what the UI displays."""
    text = text.strip()
    if not text:
        return "missing"
    if re.match(r"^(?:publication date|source|authors?\(s\)|authors?)\s*:", text, re.I):
        return "metadata"
    return "fragment" if re.search(r"(?:\.\.\.|…)[\s\"'”）)]*$", text) else "available"


def normalize_doi(value: str) -> str:
    """Accept an explicit DOI or resolver URL, never arbitrary article prose."""
    value = unquote(value.strip())
    parsed = urlparse(value)
    if parsed.hostname in ("doi.org", "dx.doi.org"):
        value = parsed.path.lstrip("/")
    value = re.sub(r"^doi\s*:\s*", "", value, flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/\S+", value) else ""


def paper_abstract_kind(paper: Paper) -> str:
    detected = abstract_kind(paper.get("abstract", ""))
    if detected != "available":
        return detected
    # Old RSS caches used 'full' merely because no ellipsis was present.
    if paper.get("abstract_kind") == "full" and paper.get("abstract_source"):
        return "full"
    return "available"


def make_paper(
    source: Source,
    title: str,
    link: str,
    date: str,
    precision: str = "",
    date_kind: str = "",
    abstract: str = "",
    doi: str = "",
    abstract_source: str = "",
) -> Paper:
    abstract = abstract.strip()
    return {
        "id": hashlib.sha256((source["id"] + "|" + link).encode("utf-8")).hexdigest(),
        "source_id": source["id"],
        "source_name": source["name"],
        "publication_name": source.get("publication_name", ""),
        "title": title,
        "url": link,
        "date": date,
        "date_precision": precision,
        "date_kind": date_kind,
        "abstract": abstract,
        "abstract_kind": abstract_kind(abstract),
        "doi": normalize_doi(doi) or normalize_doi(link),
        "abstract_source": abstract_source,
    }


def sort_papers(papers: list[Paper]) -> list[Paper]:
    return sorted(
        papers, key=lambda paper: (paper.get("date") or "", paper.get("title") or ""), reverse=True
    )


def paper_date_label(paper: Paper) -> str:
    value = paper.get("date") or ""
    if not value:
        return "日期未提供"
    precision = paper.get("date_precision") or ("day" if len(value) == 10 else "")
    if precision == "month":
        return value + "（来源仅提供月份）"
    if precision == "year":
        return value + "（来源仅提供年份）"
    if paper.get("date_kind") == "online":
        return value + "（在线发表）"
    return value


def is_recent_publication(paper: Paper, days: int, today: calendar_date | None = None) -> bool:
    if days <= 0:
        return True
    value = paper.get("date") or ""
    precision = paper.get("date_precision") or ("day" if len(value) == 10 else "")
    if precision != "day":
        return False
    try:
        published = calendar_date.fromisoformat(value)
    except ValueError:
        return False
    today = today or calendar_date.today()
    return today - timedelta(days=days) <= published <= today
