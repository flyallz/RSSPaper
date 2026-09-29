"""Workspace edits are committed before updating the UI's shared state."""

from collections.abc import Callable
from copy import deepcopy

from ..domain.models import AppState, Settings, Source
from ..domain.state import new_profile, validate_state
from ..platform.secrets import load_api_key, save_api_key
from ..storage import StateRepository, current_profile


class WorkspaceService:
    def __init__(self, state: AppState, repository: StateRepository):
        self.state = state
        self.repository = repository

    def _commit(self, change: Callable[[AppState], None]) -> None:
        candidate = deepcopy(self.state)
        change(candidate)
        candidate = validate_state(candidate)
        self.repository.save(candidate)
        # Keep the shared root object stable. Views must resolve profiles by ID,
        # rather than retaining mutable child dictionaries across transactions.
        self.state.clear()
        self.state.update(candidate)

    def select_profile(self, profile_id: str) -> None:
        if profile_id not in {profile["id"] for profile in self.state["profiles"]}:
            raise ValueError("学科不存在")
        self._commit(lambda state: state.update(active_profile_id=profile_id))

    def add_profile(self, name: str) -> None:
        profile = new_profile(name)

        def change(state):
            state["profiles"].append(profile)
            state["active_profile_id"] = profile["id"]

        self._commit(change)

    def rename_profile(self, name: str) -> None:
        if not name.strip():
            raise ValueError("学科名称不能为空")
        self._commit(lambda state: current_profile(state).update(name=name.strip()))

    def delete_profile(self) -> None:
        if len(self.state["profiles"]) <= 1:
            raise ValueError("至少保留一个学科")
        profile_id = self.state["active_profile_id"]

        def change(state):
            state["profiles"] = [
                profile for profile in state["profiles"] if profile["id"] != profile_id
            ]
            for field in ("papers", "statuses", "last_refresh"):
                state[field].pop(profile_id, None)
            state["active_profile_id"] = state["profiles"][0]["id"]

        self._commit(change)

    def put_source(self, source: Source, index: int | None = None) -> None:
        def change(state):
            sources = current_profile(state)["sources"]
            if index is None:
                sources.append(deepcopy(source))
            else:
                sources[index] = deepcopy(source)

        self._commit(change)

    def delete_source(self, index: int) -> None:
        def change(state):
            profile = current_profile(state)
            source = profile["sources"].pop(index)
            state["papers"][profile["id"]] = [
                paper
                for paper in state["papers"].get(profile["id"], [])
                if paper["source_id"] != source["id"]
            ]
            state["statuses"].get(profile["id"], {}).pop(source["id"], None)

        self._commit(change)

    def import_sources(self, imported: list[Source]) -> int:
        existing = {
            (source["kind"], source["value"].lower())
            for source in current_profile(self.state)["sources"]
        }
        additions = []
        for source in imported:
            key = (source["kind"], source["value"].lower())
            if key not in existing:
                additions.append(deepcopy(source))
                existing.add(key)
        if additions:
            self._commit(lambda state: current_profile(state)["sources"].extend(additions))
        return len(additions)

    def save_settings(
        self, settings: Settings, credential: str | None = None, rank_credential: str | None = None
    ) -> None:
        """None preserves the key; an empty string explicitly deletes it."""
        candidate = deepcopy(self.state)
        candidate["settings"].update(settings)
        if rank_credential is not None:
            candidate["publication_ranks"] = {}
        candidate = validate_state(candidate)
        self.repository.ensure_writable()
        changes = [
            (self.repository.folder / "api-key.bin", credential),
            (self.repository.folder / "easyscholar-key.bin", rank_credential),
        ]
        previous = [(path, load_api_key(path)) for path, key in changes if key is not None]
        try:
            for path, key in changes:
                if key is not None:
                    save_api_key(path, key)
            self.repository.save(candidate)
        except Exception:
            for path, key in previous:
                save_api_key(path, key)
            raise
        self.state.clear()
        self.state.update(candidate)
