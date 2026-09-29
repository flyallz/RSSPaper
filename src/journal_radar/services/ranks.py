"""Publication-level cache; user aliases and preprint subjects are not venues."""

from datetime import UTC, datetime, timedelta

from ..adapters.ranks import fetch_ranks
from ..domain.models import AppState, Paper, PublicationRank


def publication_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def cached_rank(state: AppState, name: str, fresh_only: bool = False) -> PublicationRank | None:
    record = state.get("publication_ranks", {}).get(publication_key(name))
    if record and fresh_only:
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(record["retrieved_at"])
            if age < timedelta(0) or age > timedelta(days=7 if record["labels"] else 1):
                return None
        except (ValueError, TypeError):
            return None
    return record


def query_rank(name: str, key: str, proxy: str = "", cancelled=None) -> PublicationRank:
    record = fetch_ranks(name, key, proxy, cancelled)
    record["retrieved_at"] = datetime.now(UTC).isoformat()
    return record


def store_rank(state: AppState, record: PublicationRank) -> None:
    cache = state.setdefault("publication_ranks", {})
    cache[publication_key(record["name"])] = record
    if len(cache) > 500:
        oldest = min(cache, key=lambda key: cache[key]["retrieved_at"])
        del cache[oldest]


def paper_rank_text(paper: Paper, state: AppState) -> tuple[str, str]:
    if not state["settings"].get("rank_enabled"):
        return "", ""
    record = cached_rank(state, paper.get("publication_name", ""), fresh_only=True)
    if not record:
        return "", ""
    selected = set(state["settings"].get("rank_fields", []))
    labels = [
        label
        for label in record["labels"]
        if label["key"] in selected or (label["key"].startswith("custom:") and "custom" in selected)
    ]
    short = " · ".join(f"{label['label']} {label['value']}" for label in labels[:4])
    detail = "\n".join(
        f"{label['label']}：{label['value']}（年度：{label['year'] or '接口未提供'}）"
        for label in labels
    )
    return short, f"{record['name']}\neasyScholar · 获取于 {record['retrieved_at'][:10]}\n{detail}"


def apply_rank(state: AppState, profile_id: str, snapshot: Paper, record: PublicationRank) -> bool:
    """Apply a user-confirmed venue only if the requesting paper still exists."""
    profile = next((p for p in state["profiles"] if p["id"] == profile_id), None)
    if not profile:
        return False
    enabled = {s["id"] for s in profile["sources"] if s.get("enabled", True)}
    for paper in state["papers"].get(profile_id, []):
        if (paper["id"], paper["title"], paper["url"]) == (
            snapshot["id"],
            snapshot["title"],
            snapshot["url"],
        ) and paper["source_id"] in enabled:
            paper["publication_name"] = record["name"]
            store_rank(state, record)
            return True
    return False
