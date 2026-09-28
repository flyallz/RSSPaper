"""JSON-compatible contracts shared by adapters, services, storage and UI.

TypedDict keeps schema-1 files compatible. Runtime validation is performed at
the storage boundary; domain modules never import Qt or platform APIs.
"""

from typing import Literal, NotRequired, TypedDict

SourceKind = Literal["rss", "crossref", "arxiv"]
ContentType = Literal["title", "abstract"]
Language = Literal["zh", "en"]


class Source(TypedDict):
    id: str
    name: str
    kind: SourceKind
    value: str
    enabled: bool
    include_keywords: list[str]
    exclude_keywords: list[str]
    match_all: bool


class Paper(TypedDict):
    id: str
    source_id: str
    source_name: str
    title: str
    url: str
    date: str
    date_precision: NotRequired[str]
    date_kind: NotRequired[str]
    abstract: NotRequired[str]
    abstract_kind: NotRequired[str]


class Settings(TypedDict):
    proxy: str
    api_endpoint: str
    api_model: str
    refresh_minutes: int


class Profile(TypedDict):
    id: str
    name: str
    sources: list[Source]


class SourceStatus(TypedDict):
    ok: bool
    count: int
    error: str
    time: str


class AppState(TypedDict):
    schema: int
    profiles: list[Profile]
    active_profile_id: str
    settings: Settings
    papers: dict[str, list[Paper]]
    statuses: dict[str, dict[str, SourceStatus]]
    translations: dict[str, str]
    last_refresh: dict[str, str]
