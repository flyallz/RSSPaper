"""Widgets for both desktop platforms."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


def resource_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / name


def make_button(text: str, role: str = "") -> QPushButton:
    button = QPushButton(text)
    if role:
        button.setObjectName(role)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button
