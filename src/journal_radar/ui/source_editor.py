"""Source editor for both desktop platforms."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from journal_radar.domain.sources import create_source


class SourceEditor(QDialog):
    def __init__(self, source: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.source = source
        self.result_source: dict | None = None
        self.setWindowTitle("编辑期刊来源" if source else "添加期刊来源")
        available = self.screen().availableGeometry()
        self.resize(min(780, available.width()), min(520, available.height()))
        self.setMinimumSize(720, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        title = QLabel("期刊来源")
        title.setObjectName("sectionTitle")
        title.setFixedHeight(42)
        layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignTop)
        panel = QFrame()
        panel.setObjectName("formCard")
        form = QFormLayout(panel)
        form.setContentsMargins(22, 20, 22, 20)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.name_edit = QLineEdit(source["name"] if source else "")
        self.name_edit.setPlaceholderText("例如：Nature / 中国科学")
        self.publication_edit = QLineEdit(source.get("publication_name", "") if source else "")
        self.publication_edit.setPlaceholderText(
            "可选：期刊或会议正式全名，用于等级查询；不要填 arXiv 分类"
        )
        self.kind_box = QComboBox()
        self.kind_box.addItem("RSS / Atom 地址", "rss")
        self.kind_box.addItem("Crossref · ISSN", "crossref")
        self.kind_box.addItem("arXiv 主题检索", "arxiv")
        self.kind_box.setMinimumContentsLength(28)
        self.kind_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.kind_box.setView(QListView())
        self.kind_box.view().setMinimumWidth(360)
        self.value_edit = QLineEdit(source["value"] if source else "")
        self.include_edit = QLineEdit(
            ", ".join(source.get("include_keywords", [])) if source else ""
        )
        self.include_edit.setPlaceholderText("例如：augmented reality, learning analytics")
        self.exclude_edit = QLineEdit(
            ", ".join(source.get("exclude_keywords", [])) if source else ""
        )
        self.exclude_edit.setPlaceholderText("可选，例如：survey, correction")
        self.match_all = QCheckBox("必须同时包含全部关键词（默认匹配任一关键词）")
        self.match_all.setChecked(bool(source and source.get("match_all")))
        self.hint = QLabel()
        self.hint.setObjectName("notice")
        self.hint.setWordWrap(True)
        for field in (
            self.name_edit,
            self.publication_edit,
            self.kind_box,
            self.value_edit,
            self.include_edit,
            self.exclude_edit,
        ):
            field.setMinimumWidth(430)
        form.addRow("期刊名称", self.name_edit)
        form.addRow("正式刊名 / 会议名", self.publication_edit)
        form.addRow("来源类型", self.kind_box)
        form.addRow("地址 / ISSN", self.value_edit)
        form.addRow("", self.hint)
        form.addRow("二层包含关键词", self.include_edit)
        form.addRow("排除关键词", self.exclude_edit)
        form.addRow("匹配方式", self.match_all)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_scroll.setWidget(panel)
        layout.addWidget(self.form_scroll, 1)
        if source:
            self.kind_box.setCurrentIndex(
                {"rss": 0, "crossref": 1, "arxiv": 2}.get(source["kind"], 0)
            )
        self.kind_box.currentIndexChanged.connect(self.update_hint)
        self.update_hint()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存来源")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_hint(self) -> None:
        if self.kind_box.currentData() == "rss":
            self.value_edit.setPlaceholderText("https://example.org/journal/feed")
            self.hint.setText("先读取 RSS / Atom，再用下面的关键词筛选标题和摘要。")
        elif self.kind_box.currentData() == "crossref":
            self.value_edit.setPlaceholderText("例如 0360-1315")
            self.hint.setText("只需期刊 ISSN；通过 Crossref 获取近期论文，无须 API 密钥。")
        else:
            self.value_edit.setPlaceholderText(
                '例如 cs.HC，或 cat:cs.HC AND all:"augmented reality"'
            )
            self.hint.setText(
                "输入 arXiv 分类或检索式，按提交时间读取最新论文；可继续用下面的关键词做第二层筛选。"
            )

    def save(self) -> None:
        try:
            result = create_source(
                self.name_edit.text(),
                self.kind_box.currentData(),
                self.value_edit.text(),
                self.include_edit.text(),
                self.exclude_edit.text(),
                self.match_all.isChecked(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "无法保存", str(error))
            return
        if self.source:
            result["id"] = self.source["id"]
            result["enabled"] = self.source.get("enabled", True)
        result["publication_name"] = self.publication_edit.text().strip()
        self.result_source = result
        self.accept()
