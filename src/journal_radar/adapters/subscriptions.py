"""Import and export subscription files without coupling to the UI."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from ..config import APP_NAME
from ..domain.models import Source
from ..domain.sources import create_source
from ..domain.validation import valid_http_url


def import_opml(path: Path) -> list[Source]:
    root = ET.fromstring(path.read_bytes())
    sources: list[Source] = []
    seen: set[str] = set()
    for node in root.iter():
        url = node.attrib.get("xmlUrl", "").strip()
        if not valid_http_url(url) or url.lower() in seen:
            continue
        seen.add(url.lower())
        name = node.attrib.get("title") or node.attrib.get("text") or urlparse(url).netloc
        sources.append(create_source(name, "rss", url))
    return sources


def import_legacy_feeds(path: Path) -> list[Source]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("旧版订阅文件格式不正确")
    sources: list[Source] = []
    seen: set[str] = set()
    for item in data:
        url = str(item.get("Url", "")).strip()
        if not valid_http_url(url) or url.lower() in seen:
            continue
        seen.add(url.lower())
        sources.append(create_source(str(item.get("Name") or urlparse(url).netloc), "rss", url))
    return sources


def export_opml(path: Path, sources: list[Source]) -> None:
    root = ET.Element("opml", version="2.0")
    ET.SubElement(root, "head").append(ET.Element("title"))
    root.find("head/title").text = APP_NAME
    body = ET.SubElement(root, "body")
    for source in sources:
        if source["kind"] == "rss":
            ET.SubElement(
                body,
                "outline",
                {
                    "text": source["name"],
                    "title": source["name"],
                    "type": "rss",
                    "xmlUrl": source["value"],
                },
            )
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
