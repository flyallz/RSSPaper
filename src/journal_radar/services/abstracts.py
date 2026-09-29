"""Immutable abstract jobs and profile-scoped cache updates."""

from dataclasses import dataclass
from datetime import UTC, datetime

from ..adapters.abstract_enrichment import fetch_complete_abstract
from ..adapters.abstracts import AbstractResult
from ..domain.models import AppState, Paper
from ..domain.papers import normalize_doi, paper_abstract_kind

ENRICHMENT_FIELDS = ("abstract", "abstract_kind", "abstract_source", "abstract_retrieved_at", "doi")


@dataclass(frozen=True)
class AbstractJob:
    profile_id: str
    paper_id: str
    title: str
    url: str
    doi: str
    proxy: str

    @classmethod
    def for_paper(cls, profile_id: str, paper: Paper, proxy: str = "") -> "AbstractJob":
        return cls(
            profile_id,
            paper["id"],
            paper["title"],
            paper["url"],
            normalize_doi(paper.get("doi", "")) or normalize_doi(paper["url"]),
            proxy,
        )

    def execute(self, cancelled=None) -> AbstractResult:
        return fetch_complete_abstract(self.doi, self.title, self.url, self.proxy, cancelled)


def apply_abstract(
    state: AppState, job: AbstractJob, result: AbstractResult | None = None, error: str = ""
) -> bool:
    # Removed profiles/sources and replaced papers must not be resurrected.
    profile = next((p for p in state["profiles"] if p["id"] == job.profile_id), None)
    if profile is None:
        return False
    source_ids = {s["id"] for s in profile["sources"] if s.get("enabled", True)}
    for paper in state["papers"].get(job.profile_id, []):
        if (paper["id"], paper["title"], paper["url"]) != (job.paper_id, job.title, job.url):
            continue
        if paper["source_id"] not in source_ids:
            return False
        if result:
            paper.update(
                abstract=result.text,
                abstract_kind=result.kind,
                abstract_source=result.source,
                abstract_retrieved_at=datetime.now(UTC).isoformat(),
                doi=result.doi or paper.get("doi", ""),
                abstract_error="",
            )
        elif paper_abstract_kind(paper) != "full":
            paper["abstract_error"] = error
        return True
    return False


def retain_enrichment(paper: Paper, previous: Paper | None) -> Paper:
    """A refresh teaser must not overwrite a successfully enriched abstract."""
    if not previous or not previous.get("abstract_retrieved_at"):
        return paper
    if (paper["title"], paper["url"]) != (previous["title"], previous["url"]):
        return paper
    if paper.get("doi") and paper["doi"] != previous.get("doi"):
        return paper
    return {**paper, **{key: previous[key] for key in ENRICHMENT_FIELDS if key in previous}}
