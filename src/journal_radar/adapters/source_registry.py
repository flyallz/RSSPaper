"""Source adapters share transport, normalized papers and domain filtering.

To add a source: implement URL construction and parsing, register the adapter,
then add its input validation/UI label. No refresh or card changes are needed.
"""

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from ..domain.models import Paper, Source
from ..domain.sources import paper_matches_source
from ..domain.validation import normalize_issn
from .crossref import parse_crossref
from .http import read_bytes
from .rss import parse_rss


@dataclass(frozen=True)
class SourceAdapter:
    url: Callable[[Source], str]
    parse: Callable[[bytes, Source], list[Paper]]


def crossref_url(source: Source) -> str:
    issn = normalize_issn(source["value"])
    query = urlencode(
        {
            "rows": 30,
            "sort": "published",
            "order": "desc",
            "select": "DOI,title,URL,abstract,published,published-online,published-print,issued",
        }
    )
    return "https://api.crossref.org/journals/" + quote(issn) + "/works?" + query


def arxiv_url(source: Source) -> str:
    query = urlencode(
        {
            "search_query": source["value"],
            "start": 0,
            "max_results": 60,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    return "https://export.arxiv.org/api/query?" + query


SOURCE_ADAPTERS = {
    "rss": SourceAdapter(lambda source: source["value"], parse_rss),
    "crossref": SourceAdapter(crossref_url, parse_crossref),
    "arxiv": SourceAdapter(arxiv_url, parse_rss),
}


def fetch_source(source: Source, proxy: str = "") -> list[Paper]:
    adapter = SOURCE_ADAPTERS.get(source["kind"])
    if adapter is None:
        raise ValueError("未知来源类型")
    papers = adapter.parse(read_bytes(adapter.url(source), proxy), source)
    if not papers:
        raise ValueError("此来源没有可用的论文标题与链接")
    return [paper for paper in papers if paper_matches_source(paper, source)]
