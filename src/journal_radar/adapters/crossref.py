"""Parse Crossref metadata independently of HTTP transport."""

from __future__ import annotations

import html
import json
import re
from datetime import date as calendar_date

from ..domain.models import Paper, Source
from ..domain.papers import abstract_kind, make_paper
from ..domain.validation import valid_http_url


def parse_crossref(payload: bytes, source: Source) -> list[Paper]:
    data = json.loads(payload.decode("utf-8-sig"))
    items = data.get("message", {}).get("items", [])
    papers: list[Paper] = []
    for item in items:
        titles = item.get("title") or []
        title = html.unescape(str(titles[0])).strip() if titles else ""
        doi = item.get("DOI", "")
        link = item.get("URL") or ("https://doi.org/" + doi if doi else "")
        date = precision = ""
        for field in ("published-online", "published", "published-print", "issued"):
            parts = (item.get(field) or {}).get("date-parts") or []
            if parts and parts[0]:
                values = parts[0]
                try:
                    if len(values) >= 3:
                        date = calendar_date(
                            int(values[0]), int(values[1]), int(values[2])
                        ).isoformat()
                        precision = "day"
                    elif len(values) == 2 and 1 <= int(values[1]) <= 12:
                        date, precision = f"{int(values[0]):04d}-{int(values[1]):02d}", "month"
                    elif len(values) == 1:
                        date, precision = f"{int(values[0]):04d}", "year"
                except (ValueError, TypeError):
                    pass
                if date:
                    break
        abstract = re.sub(
            r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(item.get("abstract") or "")))
        ).strip()
        if title and valid_http_url(link):
            paper = make_paper(
                source,
                title,
                link,
                date,
                precision,
                abstract=abstract,
                doi=doi,
                abstract_source="Crossref",
            )
            if abstract_kind(abstract) == "available":
                paper["abstract_kind"] = "full"
            papers.append(paper)
    return papers
