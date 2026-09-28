"""Paper selection is testable without constructing desktop widgets."""

from ..domain.models import Paper
from ..domain.papers import is_recent_publication


def select_papers(
    papers: list[Paper], query: str = "", source_id: str = "", days: int = 0
) -> list[Paper]:
    query = query.strip().casefold()
    result = []
    for paper in papers:
        if source_id and paper["source_id"] != source_id:
            continue
        searchable = " ".join(
            paper.get(field, "") for field in ("title", "abstract", "source_name")
        )
        if query and query not in searchable.casefold():
            continue
        if days and not is_recent_publication(paper, days):
            continue
        result.append(paper)
    return result
