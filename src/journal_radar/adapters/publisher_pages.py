"""Small publisher-specific HTML parsers, independent of browser sessions.

Only explicit abstract containers / citation_abstract metadata are considered.
The original title is required to match, and any supplied page DOI is checked.
No scripts are executed; imported saved pages use the same identity checks.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request

from ..config import MAX_DOWNLOAD, USER_AGENT
from ..domain.papers import abstract_kind, normalize_doi
from .abstracts import AbstractResult, _title_key
from .http import build_http_opener


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        if self.tag in ("script", "style", "noscript", "button"):
            return ""
        content = "".join(
            child.text() if isinstance(child, Node) else child for child in self.children
        )
        return content + ("\n" if self.tag in ("p", "div", "br", "h1", "h2") else "")

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if len(self.stack) > 180:
            raise ValueError("网页结构过深，已停止解析")
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in (
            "meta",
            "link",
            "img",
            "br",
            "input",
            "hr",
            "source",
            "wbr",
            "area",
            "base",
            "embed",
            "param",
            "track",
            "col",
        ):
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def publisher_name(url):
    host = (urlparse(url).hostname or "").lower()
    if host == "sciencedirect.com" or host.endswith(".sciencedirect.com"):
        return "ScienceDirect"
    if host == "cnki.net" or host.endswith(".cnki.net"):
        return "知网"
    return ""


def decode_page(payload):
    match = re.search(rb'charset\s*=\s*["\']?([\w-]+)', payload[:8192], re.I)
    charset = match[1].decode().lower() if match else "utf-8"
    if charset not in ("utf-8", "utf8", "gbk", "gb2312", "gb18030"):
        charset = "utf-8"
    try:
        return payload.decode(charset)
    except UnicodeError:
        return payload.decode("gb18030")


def _complete_candidate(value: str) -> bool:
    return abstract_kind(value) == "available" and not re.search(
        r"(?:\.\.\.|…)\s*(?:read more|show more|展开|更多|收起)\s*$", value, re.I
    )


def parse_publisher_abstract(payload, url, title, doi=""):
    publisher = publisher_name(url)
    if not publisher:
        raise ValueError("暂不支持该站点的网页摘要；目前支持 ScienceDirect 和知网")
    if len(payload) > MAX_DOWNLOAD:
        raise ValueError("网页文件过大，请保存论文详情页面")
    parser = PageParser()
    parser.feed(decode_page(payload))
    nodes = list(parser.root.walk())
    meta = {}
    for node in nodes:
        if node.tag == "meta":
            key = (node.attrs.get("name") or node.attrs.get("property") or "").lower()
            meta.setdefault(key, []).append(node.attrs.get("content") or "")
    titles = meta.get("citation_title", []) + meta.get("dc.title", [])
    titles += [node.text().strip() for node in nodes if node.tag == "h1"]
    if not any(_title_key(value) == _title_key(title) for value in titles if value.strip()):
        raise ValueError(
            "网页题名与论文不一致，或需要登录 / 浏览器验证；请打开原文后导入保存的论文网页"
        )
    page_dois = {
        normalize_doi(value) for value in meta.get("citation_doi", []) if normalize_doi(value)
    }
    expected = normalize_doi(doi)
    if expected and page_dois and page_dois != {expected}:
        raise ValueError("网页 DOI 与论文不一致，已保留原摘要")
    candidates = []
    for node in nodes:
        classes = (node.attrs.get("class") or "").split()
        ident = (node.attrs.get("id") or "").lower()
        selected = (
            publisher == "ScienceDirect"
            and "abstract" in classes
            and "abstractHighlights" not in classes
        ) or (publisher == "知网" and ident in ("chdivsummary", "abstract"))
        if not selected:
            continue
        paragraphs = [child.text() for child in node.walk() if child.tag == "p"]
        value = "\n".join(paragraphs) if paragraphs else node.text()
        value = re.sub(r"^\s*(?:Abstract|Summary|摘要)\s*[:：]?\s*", "", value, flags=re.I)
        value = "\n\n".join(" ".join(line.split()) for line in value.splitlines() if line.strip())
        if _complete_candidate(value):
            candidates.append(value)
    if not candidates:
        candidates = [
            value.strip()
            for value in meta.get("citation_abstract", [])
            if _complete_candidate(value)
        ]
    if not candidates:
        raise ValueError(
            "网页未提供可确认的完整摘要，或只提供片段；请在浏览器展开摘要后保存页面再导入"
        )
    return AbstractResult(
        max(candidates, key=len), expected or next(iter(page_dois), ""), publisher + " 论文页面"
    )


class _PublisherRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or not publisher_name(newurl):
            raise ValueError("论文页面跳转到登录或暂不支持的站点，请用浏览器打开原文")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_publisher_abstract(url, title, doi="", proxy="", cancelled=None):
    if not publisher_name(url) and urlparse(url).hostname not in ("doi.org", "dx.doi.org"):
        raise ValueError("该出版社暂未接入网页摘要适配器")
    if cancelled and cancelled():
        raise ValueError("摘要查询已取消")
    opener = build_http_opener(proxy)
    opener.add_handler(_PublisherRedirect())
    try:
        with opener.open(
            Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}), timeout=22
        ) as response:
            payload = response.read(MAX_DOWNLOAD + 1)
            final_url = response.geturl()
    except Exception:
        if cancelled and cancelled():
            raise ValueError("摘要查询已取消") from None
        raise ValueError(
            "论文网页读取失败或需要浏览器登录 / 验证；可打开原文后导入保存的网页"
        ) from None
    if cancelled and cancelled():
        raise ValueError("摘要查询已取消")
    return parse_publisher_abstract(payload, final_url, title, doi)
