"""Read and atomically write the existing schema-1 JSON state."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .domain.models import AppState, Profile
from .domain.state import default_state, validate_state
from .platform.paths import data_dir


def load_state(folder: Path | None = None) -> AppState:
    folder = folder or data_dir()
    path = folder / "state.json"
    if not path.exists():
        return default_state()
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("配置文件不是有效的对象")
    return validate_state(raw)


def save_state(state: AppState, folder: Path | None = None) -> None:
    folder = folder or data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "state.json"
    fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def current_profile(state: AppState) -> Profile:
    return next(p for p in state["profiles"] if p["id"] == state["active_profile_id"])


class StateRepository:
    """A session owns one storage location and cannot overwrite unreadable data."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder or data_dir()
        self.read_failed = False

    def load(self) -> AppState:
        try:
            return load_state(self.folder)
        except Exception:
            self.read_failed = True
            raise

    def save(self, state: AppState) -> None:
        self.ensure_writable()
        save_state(state, self.folder)

    def ensure_writable(self) -> None:
        if self.read_failed:
            raise ValueError("原配置读取失败，已阻止覆盖；请先备份并修复 state.json 后重启应用")
