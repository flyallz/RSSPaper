"""Storage and scholarly-source adapters for the macOS Journal Radar app."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import ssl
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date as calendar_date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

import certifi


APP_NAME = "期刊雷达"
USER_AGENT = "JournalRadar/1.1 (macOS; personal research reader)"
MAX_DOWNLOAD = 4 * 1024 * 1024


def data_dir() -> Path:
    override = os.environ.get("JOURNAL_RADAR_HOME")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / "JournalRadar"


def new_profile(name: str = "我的学科") -> dict:
    return {"id": uuid.uuid4().hex, "name": name.strip() or "我的学科", "sources": []}


def default_state() -> dict:
    profile = new_profile()
    return {
        "schema": 1,
        "profiles": [profile],
        "active_profile_id": profile["id"],
        "settings": {
            "proxy": "",
            "api_endpoint": "",
            "api_model": "deepseek-flash",
            "refresh_minutes": 30,
        },
        "papers": {},
        "statuses": {},
        "translations": {},
        "last_refresh": {},
    }


def load_state(folder: Path | None = None) -> dict:
    folder = folder or data_dir()
    path = folder / "state.json"
    if not path.exists():
        return default_state()
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("配置文件不是有效的对象")
    state = default_state()
    state.update(raw)
    if not isinstance(state.get("profiles"), list) or not state["profiles"]:
        state["profiles"] = [new_profile()]
    for profile in state["profiles"]:
        profile.setdefault("sources", [])
        profile.setdefault("id", uuid.uuid4().hex)
        profile.setdefault("name", "未命名学科")
        for source in profile["sources"]:
            source.setdefault("include_keywords", [])
            source.setdefault("exclude_keywords", [])
            source.setdefault("match_all", False)
    ids = {p["id"] for p in state["profiles"]}
    if state.get("active_profile_id") not in ids:
        state["active_profile_id"] = state["profiles"][0]["id"]
    defaults = default_state()["settings"]
    defaults.update(state.get("settings") or {})
    state["settings"] = defaults
    for name in ("papers", "statuses", "translations", "last_refresh"):
        if not isinstance(state.get(name), dict):
            state[name] = {}
    return state


def save_state(state: dict, folder: Path | None = None) -> None:
    folder = folder or data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "state.json"
    fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def current_profile(state: dict) -> dict:
    return next(p for p in state["profiles"] if p["id"] == state["active_profile_id"])


def valid_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def valid_api_endpoint(value: str) -> bool:
    parsed = urlparse(value.strip())
    return valid_http_url(value) and (parsed.scheme == "https" or parsed.hostname in ("localhost", "127.0.0.1", "::1"))


def normalize_issn(value: str) -> str:
    compact = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"\d{7}[\dX]", compact):
        raise ValueError("ISSN 应为 8 位，例如 0360-1315")
    checksum = sum(int(digit) * (8 - index) for index, digit in enumerate(compact[:7]))
    checksum += 10 if compact[-1] == "X" else int(compact[-1])
    if checksum % 11:
        raise ValueError("ISSN 校验位不正确，请检查数字")
    return compact[:4] + "-" + compact[4:]


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
) -> dict:
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


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(node: ET.Element) -> str:
    value = "".join(node.itertext()).strip()
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


_MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1
)}


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
    english_day = re.fullmatch(r"(?:Available online\s+)?(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value, re.I)
    if english_day and english_day.group(2).lower() in _MONTHS:
        try:
            return calendar_date(int(english_day.group(3)), _MONTHS[english_day.group(2).lower()], int(english_day.group(1))).isoformat(), "day"
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
    return parsed, precision, "online" if raw.lower().startswith("available online") else "publication"


def _paper(source: dict, title: str, link: str, date: str, precision: str = "", date_kind: str = "", abstract: str = "") -> dict:
    abstract = abstract.strip()
    abstract_kind = "fragment" if re.search(r"(?:\.\.\.|…)$", abstract) else ("metadata" if abstract.lower().startswith("publication date:") else ("full" if abstract else "missing"))
    return {
        "id": hashlib.sha256((source["id"] + "|" + link).encode("utf-8")).hexdigest(),
        "source_id": source["id"],
        "source_name": source["name"],
        "title": title,
        "url": link,
        "date": date,
        "date_precision": precision,
        "date_kind": date_kind,
        "abstract": abstract,
        "abstract_kind": abstract_kind,
    }


def parse_rss(payload: bytes, source: dict) -> list[dict]:
    root = ET.fromstring(payload)
    papers: list[dict] = []
    for item in root.iter():
        if _local(item.tag) not in ("item", "entry"):
            continue
        title = link = date = description = precision = date_kind = ""
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
        if not date and description:
            date, precision, date_kind = _description_date(description)
        if title and valid_http_url(link):
            abstract = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", description))).strip()
            papers.append(_paper(source, title, link, date, precision, date_kind, abstract))
        if len(papers) >= 60:
            break
    return papers


def parse_crossref(payload: bytes, source: dict) -> list[dict]:
    data = json.loads(payload.decode("utf-8-sig"))
    items = data.get("message", {}).get("items", [])
    papers: list[dict] = []
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
                        date = calendar_date(int(values[0]), int(values[1]), int(values[2])).isoformat()
                        precision = "day"
                    elif len(values) == 2 and 1 <= int(values[1]) <= 12:
                        date, precision = f"{int(values[0]):04d}-{int(values[1]):02d}", "month"
                    elif len(values) == 1:
                        date, precision = f"{int(values[0]):04d}", "year"
                except (ValueError, TypeError):
                    pass
                if date:
                    break
        abstract = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(item.get("abstract") or "")))).strip()
        if title and valid_http_url(link):
            papers.append(_paper(source, title, link, date, precision, abstract=abstract))
    return papers


def _opener(proxy: str):
    if proxy:
        if not valid_http_url(proxy):
            raise ValueError("代理地址必须以 http:// 或 https:// 开头")
        proxy_handler = ProxyHandler({"http": proxy, "https": proxy})
    else:
        proxy_handler = ProxyHandler()
    context = ssl.create_default_context(cafile=certifi.where())
    return build_opener(proxy_handler, HTTPSHandler(context=context))


def paper_matches_source(paper: dict, source: dict) -> bool:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).casefold()
    includes = [str(value).casefold() for value in source.get("include_keywords", []) if str(value).strip()]
    excludes = [str(value).casefold() for value in source.get("exclude_keywords", []) if str(value).strip()]
    if any(value in text for value in excludes):
        return False
    if not includes:
        return True
    matches = [value in text for value in includes]
    return all(matches) if source.get("match_all") else any(matches)


def _read(url: str, proxy: str, timeout: int = 22) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/json, application/xml, text/xml, */*"})
    last_error = None
    for attempt in range(3):
        try:
            with _opener(proxy).open(request, timeout=timeout) as response:
                payload = response.read(MAX_DOWNLOAD + 1)
            break
        except HTTPError as error:
            last_error = error
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            delay = min(5, int(error.headers.get("Retry-After", "0") or 0) or (attempt + 1))
            time.sleep(delay)
    else:
        raise last_error or ValueError("来源读取失败")
    if len(payload) > MAX_DOWNLOAD:
        raise ValueError("来源文件过大，已停止读取")
    if b"Making sure you&#39;re not a bot" in payload or b"Making sure you're not a bot" in payload:
        raise ValueError("来源站点要求浏览器验证，暂时无法自动读取；请稍后重试")
    return payload


def fetch_source(source: dict, proxy: str = "") -> list[dict]:
    if source["kind"] == "rss":
        papers = parse_rss(_read(source["value"], proxy), source)
    elif source["kind"] == "crossref":
        issn = normalize_issn(source["value"])
        query = urlencode({"rows": 30, "sort": "published", "order": "desc", "select": "DOI,title,URL,abstract,published,published-online,published-print,issued"})
        url = "https://api.crossref.org/journals/" + quote(issn) + "/works?" + query
        papers = parse_crossref(_read(url, proxy), source)
    elif source["kind"] == "arxiv":
        query = urlencode({"search_query": source["value"], "start": 0, "max_results": 60, "sortBy": "submittedDate", "sortOrder": "descending"})
        papers = parse_rss(_read("https://export.arxiv.org/api/query?" + query, proxy), source)
    else:
        raise ValueError("未知来源类型")
    if not papers:
        raise ValueError("此来源没有可用的论文标题与链接")
    return [paper for paper in papers if paper_matches_source(paper, source)]


def compact_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        return f"HTTP {error.code}：来源拒绝了请求"
    if isinstance(error, URLError):
        return f"连接失败：{error.reason}"
    return str(error).splitlines()[0][:180]


def import_opml(path: Path) -> list[dict]:
    root = ET.fromstring(path.read_bytes())
    sources: list[dict] = []
    seen: set[str] = set()
    for node in root.iter():
        url = node.attrib.get("xmlUrl", "").strip()
        if not valid_http_url(url) or url.lower() in seen:
            continue
        seen.add(url.lower())
        name = node.attrib.get("title") or node.attrib.get("text") or urlparse(url).netloc
        sources.append(create_source(name, "rss", url))
    return sources


def import_legacy_feeds(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("旧版订阅文件格式不正确")
    sources: list[dict] = []
    seen: set[str] = set()
    for item in data:
        url = str(item.get("Url", "")).strip()
        if not valid_http_url(url) or url.lower() in seen:
            continue
        seen.add(url.lower())
        sources.append(create_source(str(item.get("Name") or urlparse(url).netloc), "rss", url))
    return sources


def export_opml(path: Path, sources: list[dict]) -> None:
    root = ET.Element("opml", version="2.0")
    ET.SubElement(root, "head").append(ET.Element("title"))
    root.find("head/title").text = APP_NAME
    body = ET.SubElement(root, "body")
    for source in sources:
        if source["kind"] == "rss":
            ET.SubElement(body, "outline", {"text": source["name"], "title": source["name"], "type": "rss", "xmlUrl": source["value"]})
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def contains_cjk(text: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" for char in text)


def translation_key(endpoint: str, model: str, title: str, target_language: str = "zh") -> str:
    return hashlib.sha256((endpoint + "|" + model + "|" + target_language + "|" + title).encode("utf-8")).hexdigest()


def translate_title(title: str, endpoint: str, model: str, api_key: str, proxy: str = "", target_language: str = "zh", content_type: str = "title") -> str:
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
    params: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": title},
        ],
        "max_tokens": 180,
    }
    if urlparse(endpoint).hostname == "api.deepseek.com":
        params["thinking"] = {"type": "disabled"}
        params["max_tokens"] = 256
    payload = json.dumps(params, ensure_ascii=False).encode("utf-8")
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with _opener(proxy).open(request, timeout=30) as response:
            result = json.loads(response.read(MAX_DOWNLOAD).decode("utf-8-sig"))
    except HTTPError as error:
        raise ValueError(f"接口返回 HTTP {error.code}，请检查密钥、余额或模型") from error
    choices = result.get("choices") or []
    content = str((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not content:
        raise ValueError("接口返回空译文；请检查模型输出设置")
    return content


def sort_papers(papers: list[dict]) -> list[dict]:
    return sorted(papers, key=lambda paper: (paper.get("date") or "", paper.get("title") or ""), reverse=True)


def paper_date_label(paper: dict) -> str:
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


def is_recent_publication(paper: dict, days: int, today: calendar_date | None = None) -> bool:
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


def now_label() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
