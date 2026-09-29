"""Parse RSS and Atom payloads; this module does not perform network requests."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import date as calendar_date
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

from ..domain.models import Paper, Source
from ..domain.papers import abstract_kind, make_paper, normalize_doi
from ..domain.validation import valid_http_url

_MONTHS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        1,
    )
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(node: ET.Element) -> str:
    value = "".join(node.itertext()).strip()
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _date_info(value: str) -> tuple[str, str]:
    value = value.strip()
    if not value:
        return "", ""
    try:
        return parsedate_to_datetime(value).date().isoformat(), "day"
    except (TypeError, ValueError):
        pass
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T\s])", value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat(), "day"
    except ValueError:
        pass
    month = re.fullmatch(r"(\d{4})-(\d{1,2})", value)
    if month and 1 <= int(month.group(2)) <= 12:
        return f"{month.group(1)}-{int(month.group(2)):02d}", "month"
    english_day = re.fullmatch(
        r"(?:Available online\s+)?(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value, re.I
    )
    if english_day and english_day.group(2).lower() in _MONTHS:
        try:
            return calendar_date(
                int(english_day.group(3)),
                _MONTHS[english_day.group(2).lower()],
                int(english_day.group(1)),
            ).isoformat(), "day"
        except ValueError:
            return "", ""
    english_month = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", value, re.I)
    if english_month and english_month.group(1).lower() in _MONTHS:
        return f"{english_month.group(2)}-{_MONTHS[english_month.group(1).lower()]:02d}", "month"
    if re.fullmatch(r"\d{4}", value):
        return value, "year"
    return "", ""


def _description_date(value: str) -> tuple[str, str, str]:
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value)))
    match = re.search(
        r"\bPublication date\s*:\s*((?:Available online\s+)?(?:\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{4}|\d{4}-\d{2}(?:-\d{2})?))",
        plain,
        re.I,
    )
    if not match:
        return "", "", ""
    raw = match.group(1)
    parsed, precision = _date_info(raw)
    return (
        parsed,
        precision,
        "online" if raw.lower().startswith("available online") else "publication",
    )


def parse_rss(payload: bytes, source: Source) -> list[Paper]:
    root = ET.fromstring(payload)
    papers: list[Paper] = []
    for item in root.iter():
        if _local(item.tag) not in ("item", "entry"):
            continue
        title = link = date = description = precision = date_kind = doi = ""
        contents = []
        for child in item:
            field = _local(child.tag)
            if field == "title" and not title:
                title = _text(child)
            elif field == "link":
                candidate = child.attrib.get("href", "") or _text(child)
                if candidate and (not link or child.attrib.get("rel") == "alternate"):
                    link = urljoin(source["value"], candidate)
            elif field in ("pubdate", "published", "updated", "date") and not date:
                date, precision = _date_info(_text(child))
            elif field in ("publicationdate", "coverdate") and not date:
                date, precision = _date_info(_text(child))
            elif field in ("description", "summary") and not description:
                description = "".join(child.itertext())
                contents.append(_text(child))
            elif field in ("encoded", "content", "abstract"):
                contents.append(_text(child))
            elif field in ("doi", "identifier", "guid") and not doi:
                doi = normalize_doi(_text(child))
        if not date and description:
            date, precision, date_kind = _description_date(description)
        if title and valid_http_url(link):
            # A content:encoded/Atom content field may contain more than the teaser.
            abstract = max(
                contents,
                key=lambda text: (abstract_kind(text) != "metadata", len(text)),
                default="",
            )
            papers.append(
                make_paper(
                    source, title, link, date, precision, date_kind, abstract, doi, "RSS / Atom"
                )
            )
        if len(papers) >= 60:
            break
    return papers
