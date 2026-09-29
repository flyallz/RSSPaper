"""Immutable citation requests and cache updates scoped to the original paper."""

from dataclasses import dataclass

from ..adapters.citations import CitationResult, fetch_citation
from ..domain.models import AppState, Paper
from ..domain.papers import normalize_doi


@dataclass(frozen=True)
class CitationJob:
    profile_id: str
    paper_id: str
    title: str
    url: str
    doi: str
    format: str
    proxy: str

    @classmethod
    def for_paper(cls, profile_id: str, paper: Paper, format="apa", proxy="", doi=""):
        return cls(
            profile_id,
            paper["id"],
            paper["title"],
            paper["url"],
            normalize_doi(doi or paper.get("doi", "") or paper.get("citation_doi", "")),
            format,
            proxy,
        )

    def execute(self, cancelled=None):
        return fetch_citation(self.doi, self.title, self.url, self.format, self.proxy, cancelled)


def apply_citation(state: AppState, job: CitationJob, result: CitationResult) -> bool:
    if result.format != job.format or (job.doi and job.doi != result.doi):
        return False
    profile = next((p for p in state["profiles"] if p["id"] == job.profile_id), None)
    if not profile:
        return False
    enabled = {s["id"] for s in profile["sources"] if s.get("enabled", True)}
    for paper in state["papers"].get(job.profile_id, []):
        if (paper["id"], paper["title"], paper["url"]) != (job.paper_id, job.title, job.url):
            continue
        if paper["source_id"] not in enabled or (
            paper.get("doi") and normalize_doi(paper["doi"]) != result.doi
        ):
            return False
        if paper.get("citation_doi") != result.doi:
            paper["citations"] = {}
        paper.setdefault("citations", {})[result.format] = result.text
        paper["citation_doi"] = result.doi
        paper["citation_warning"] = result.warnings
        return True
    return False


def retain_citations(paper: Paper, previous: Paper | None) -> Paper:
    if not previous or (paper["title"], paper["url"]) != (previous["title"], previous["url"]):
        return paper
    if paper.get("doi") and normalize_doi(paper["doi"]) != previous.get("citation_doi"):
        return paper
    return {
        **paper,
        **{
            key: previous[key]
            for key in ("citations", "citation_doi", "citation_warning")
            if key in previous
        },
    }
