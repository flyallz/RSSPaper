"""Refresh sources independently and merge results without losing failed caches."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import UTC, datetime

from ..adapters.source_registry import fetch_source
from ..domain.models import AppState, Paper, Source, SourceStatus
from ..domain.papers import sort_papers
from ..errors import compact_error
from .abstracts import retain_enrichment


def now_label() -> str:
    return datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")


def refresh_sources(
    sources: list[Source],
    proxy: str = "",
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[dict[str, list[Paper]], dict[str, SourceStatus]]:
    sources = [deepcopy(source) for source in sources if source.get("enabled", True)]
    papers: dict[str, list[Paper]] = {}
    statuses: dict[str, SourceStatus] = {}
    if not sources:
        return papers, statuses

    def fetch_unless_cancelled(source):
        if cancelled and cancelled():
            return []
        return fetch_source(source, proxy)

    with ThreadPoolExecutor(max_workers=min(6, len(sources))) as pool:
        futures = {pool.submit(fetch_unless_cancelled, source): source for source in sources}
        for index, future in enumerate(as_completed(futures), 1):
            if cancelled and cancelled():
                for pending in futures:
                    pending.cancel()
                break
            source = futures[future]
            try:
                entries = future.result()
                papers[source["id"]] = entries
                statuses[source["id"]] = {
                    "ok": True,
                    "count": len(entries),
                    "error": "",
                    "time": now_label(),
                }
            except Exception as error:
                # One unavailable source must not discard other successful results.
                statuses[source["id"]] = {
                    "ok": False,
                    "count": 0,
                    "error": compact_error(error),
                    "time": now_label(),
                }
            if progress:
                progress(f"正在刷新 {index}/{len(sources)} 个来源…")
    return papers, statuses


def apply_refresh(
    state: AppState,
    profile_id: str,
    new_papers: dict[str, list[Paper]],
    statuses: dict[str, SourceStatus],
) -> bool:
    """Apply to the requested profile, even if the active profile has changed.

    A removed profile is ignored. Successful empty results clear stale papers;
    failed sources retain their last cache, disabled/deleted sources are removed.
    """
    profile = next((profile for profile in state["profiles"] if profile["id"] == profile_id), None)
    if profile is None:
        return False
    previous = state["papers"].get(profile_id, [])
    previous_by_id = {paper["id"]: paper for paper in previous}
    combined = []
    enabled_ids = set()
    for source in profile["sources"]:
        if not source.get("enabled", True):
            continue
        enabled_ids.add(source["id"])
        entries = new_papers.get(source["id"])
        if entries is None:
            entries = [paper for paper in previous if paper.get("source_id") == source["id"]]
        combined.extend(
            retain_enrichment(paper, previous_by_id.get(paper["id"])) for paper in entries
        )
    unique = {paper["id"]: paper for paper in combined}
    state["papers"][profile_id] = sort_papers(list(unique.values()))
    state["statuses"][profile_id] = {
        key: value for key, value in statuses.items() if key in enabled_ids
    }
    state["last_refresh"][profile_id] = now_label()
    return True
