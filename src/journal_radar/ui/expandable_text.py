"""Selectable plain text with independent folding and full-content copying."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from ..adapters.translation import contains_cjk
from .widgets import make_button


class ExpandableText(QLabel):
    def __init__(self, text: str, style: str, subject: str, parent=None):
        super().__init__(parent)
        self.full_text = ""
        self.preview_limit = 360
        self.subject = subject
        self.setObjectName(style)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.toggle = make_button("展开" + subject, "textAction")
        self.toggle.setParent(self)
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self.update_text)
        self.copy_button = make_button("复制" + subject, "textAction")
        self.copy_button.setParent(self)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.full_text))
        self.setText(text)

    def setText(self, text: str) -> None:
        self.full_text = text
        self.preview_limit = 180 if contains_cjk(text) else 360
        self.update_text()
        self.toggle.setVisible(len(text) > self.preview_limit)
        self.copy_button.setVisible(bool(text))
        self.setVisible(bool(text))

    def update_text(self, _checked=False) -> None:
        expanded = self.toggle.isChecked()
        super().setText(
            self.full_text
            if expanded or len(self.full_text) <= self.preview_limit
            else self.full_text[: self.preview_limit] + "…"
        )
        self.toggle.setText(("收起" if expanded else "展开") + self.subject)
