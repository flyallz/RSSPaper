"""Default state and backwards-compatible configuration migration."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import cast

from .models import AppState, Profile


def new_profile(name: str = "我的学科") -> Profile:
    return {"id": uuid.uuid4().hex, "name": name.strip() or "我的学科", "sources": []}


def default_state() -> AppState:
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
            "rank_enabled": False,
            "rank_fields": ["sci", "ssci", "sciUp", "cssci", "pku", "ccf"],
        },
        "papers": {},
        "statuses": {},
        "translations": {},
        "last_refresh": {},
        "publication_ranks": {},
    }


def validate_state(raw: object) -> AppState:
    """Migrate missing legacy fields without mutating input or changing IDs.

    Invalid nested structures are rejected at this boundary instead of failing
    later inside a widget. Unknown fields are retained for forward compatibility.
    """
    if not isinstance(raw, dict):
        raise ValueError("配置文件不是有效的对象")
    if raw.get("schema", 1) != 1:
        raise ValueError("配置文件版本不受支持，请使用与该配置匹配的应用版本")
    state = dict(default_state())
    state.update(deepcopy(raw))
    profiles = state.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("配置中的学科列表无效")
    if not profiles:
        profiles = [new_profile()]
        state["profiles"] = profiles
    profile_ids = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("配置中的学科无效")
        profile.setdefault("id", uuid.uuid4().hex)
        profile.setdefault("name", "未命名学科")
        if not isinstance(profile["id"], str) or not profile["id"] or profile["id"] in profile_ids:
            raise ValueError("学科标识为空或重复")
        profile_ids.add(profile["id"])
        if not isinstance(profile["name"], str):
            raise ValueError("学科名称无效")
        profile.setdefault("sources", [])
        if not isinstance(profile["sources"], list):
            raise ValueError("配置中的来源列表无效")
        source_ids = set()
        for source in profile["sources"]:
            if not isinstance(source, dict):
                raise ValueError("配置中的来源无效")
            if any(
                not isinstance(source.get(name), str) for name in ("id", "name", "kind", "value")
            ):
                raise ValueError("来源缺少有效的标识、名称、类型或地址")
            if not source["id"] or source["id"] in source_ids:
                raise ValueError("来源标识为空或重复")
            source_ids.add(source["id"])
            if "publication_name" in source and not isinstance(source["publication_name"], str):
                raise ValueError("正式刊名应为文本")
            source.setdefault("enabled", True)
            source.setdefault("match_all", False)
            for name in ("enabled", "match_all"):
                if not isinstance(source[name], bool):
                    raise ValueError("来源开关格式无效")
            for name in ("include_keywords", "exclude_keywords"):
                source.setdefault(name, [])
                if not isinstance(source[name], list) or any(
                    not isinstance(word, str) for word in source[name]
                ):
                    raise ValueError("来源关键词必须是字符串列表")
    if state.get("active_profile_id") not in profile_ids:
        state["active_profile_id"] = profiles[0]["id"]
    settings = state.get("settings")
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("应用设置无效")
    state["settings"] = {**default_state()["settings"], **settings}
    for name in ("proxy", "api_endpoint", "api_model"):
        if not isinstance(state["settings"][name], str):
            raise ValueError("应用设置中的接口、模型或代理无效")
    if (
        not isinstance(state["settings"]["rank_enabled"], bool)
        or not isinstance(state["settings"]["rank_fields"], list)
        or any(not isinstance(value, str) for value in state["settings"]["rank_fields"])
    ):
        raise ValueError("期刊标签设置格式无效")
    interval = state["settings"]["refresh_minutes"]
    if type(interval) is not int or not (interval == 0 or 5 <= interval <= 1440):
        raise ValueError("自动刷新间隔应为 0 或 5–1440 分钟")
    for name in ("papers", "statuses", "translations", "last_refresh"):
        if not isinstance(state.get(name), dict):
            raise ValueError(f"配置中的 {name} 格式无效")
    for papers in state["papers"].values():
        if not isinstance(papers, list):
            raise ValueError("论文缓存应为列表")
        for paper in papers:
            if not isinstance(paper, dict):
                raise ValueError("论文缓存无效")
            if any(
                not isinstance(paper.get(name), str) for name in ("id", "source_id", "title", "url")
            ):
                raise ValueError("论文缓存缺少有效的标识、来源、标题或链接")
            paper.setdefault("source_name", "")
            paper.setdefault("date", "")
            for name in (
                "source_name",
                "date",
                "abstract",
                "abstract_kind",
                "date_kind",
                "date_precision",
                "doi",
                "abstract_source",
                "abstract_retrieved_at",
                "abstract_error",
                "citation_doi",
                "citation_warning",
                "publication_name",
            ):
                if name in paper and not isinstance(paper[name], str):
                    raise ValueError("论文缓存字段应为文本")
            citations = paper.get("citations", {})
            if not isinstance(citations, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in citations.items()
            ):
                raise ValueError("引用缓存应为文本格式与内容")
    for statuses in state["statuses"].values():
        if not isinstance(statuses, dict):
            raise ValueError("来源状态应为对象")
        for status in statuses.values():
            if not isinstance(status, dict):
                raise ValueError("来源状态无效")
            if not isinstance(status.get("ok"), bool) or type(status.get("count")) is not int:
                raise ValueError("来源状态缺少有效的结果和数量")
    ranks = state.get("publication_ranks", {})
    if not isinstance(ranks, dict):
        raise ValueError("期刊标签缓存格式无效")
    for key, record in ranks.items():
        if (
            not isinstance(key, str)
            or not isinstance(record, dict)
            or any(not isinstance(record.get(field), str) for field in ("name", "retrieved_at"))
        ):
            raise ValueError("期刊标签缓存无效")
        labels = record.get("labels")
        if not isinstance(labels, list) or any(
            not isinstance(label, dict)
            or any(
                not isinstance(label.get(field), str) for field in ("key", "label", "value", "year")
            )
            for label in labels
        ):
            raise ValueError("期刊标签内容无效")
    for name in ("translations", "last_refresh"):
        if any(not isinstance(value, str) for value in state[name].values()):
            raise ValueError(f"配置中的 {name} 内容应为文本")
    return cast(AppState, state)
