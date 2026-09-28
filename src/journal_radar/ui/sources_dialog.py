"""Sources dialog for both desktop platforms."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from journal_radar.adapters.subscriptions import export_opml, import_legacy_feeds, import_opml
from journal_radar.errors import compact_error
from journal_radar.storage import StateRepository, current_profile

from ..domain.models import AppState, Source
from ..platform.paths import legacy_feed_path
from ..services.workspaces import WorkspaceService
from .source_editor import SourceEditor
from .widgets import make_button


class SourcesDialog(QDialog):
    def __init__(
        self,
        state: AppState,
        parent: QWidget | None = None,
        repository: StateRepository | None = None,
    ):
        super().__init__(parent)
        self.repository = repository or StateRepository()
        self.state = state
        self.workspaces = WorkspaceService(state, self.repository)
        self.changed = False
        self.setWindowTitle("管理期刊来源")
        self.resize(820, 555)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel("管理期刊来源")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            f"当前学科：{self.profile['name']}　·　添加 RSS，或按 ISSN 从 Crossref 读取论文"
        )
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["期刊", "类型", "地址 / ISSN", "状态"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.doubleClicked.connect(self.edit_source)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.add_button = make_button("＋ 添加来源", "primary")
        self.edit_button = make_button("编辑")
        self.delete_button = make_button("删除", "danger")
        for button in (self.add_button, self.edit_button, self.delete_button):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        secondary = QHBoxLayout()
        self.opml_button = make_button("导入 OPML")
        self.legacy_button = make_button("导入旧版 JSON")
        self.export_button = make_button("导出 OPML")
        for button in (self.opml_button, self.legacy_button, self.export_button):
            secondary.addWidget(button)
        secondary.addStretch()
        close_button = make_button("完成")
        close_button.clicked.connect(self.accept)
        secondary.addWidget(close_button)
        layout.addLayout(secondary)
        self.add_button.clicked.connect(self.add_source)
        self.edit_button.clicked.connect(self.edit_source)
        self.delete_button.clicked.connect(self.delete_source)
        self.opml_button.clicked.connect(self.open_opml)
        self.legacy_button.clicked.connect(self.open_legacy)
        self.export_button.clicked.connect(self.save_opml)
        self.refresh_table()

    @property
    def profile(self):
        return current_profile(self.state)

    def refresh_table(self) -> None:
        sources = self.profile["sources"]
        statuses = self.state["statuses"].get(self.profile["id"], {})
        self.table.setRowCount(len(sources))
        for row, source in enumerate(sources):
            status = statuses.get(source["id"])
            label = (
                "尚未刷新"
                if not status
                else (f"成功 · {status['count']} 条" if status.get("ok") else "读取失败")
            )
            type_label = {"rss": "RSS", "crossref": "Crossref", "arxiv": "arXiv"}.get(
                source["kind"], source["kind"]
            )
            values = [source["name"], type_label, source["value"], label]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if status and not status.get("ok") and column == 3:
                    item.setToolTip(status.get("error", ""))
                self.table.setItem(row, column, item)
        self.edit_button.setEnabled(bool(sources))
        self.delete_button.setEnabled(bool(sources))

    def selected_index(self) -> int | None:
        row = self.table.currentRow()
        return row if 0 <= row < len(self.profile["sources"]) else None

    def persist(self, action: Callable[[], None]) -> bool:
        try:
            action()
        except Exception as error:
            QMessageBox.warning(self, "保存失败", compact_error(error))
            return False
        self.changed = True
        self.refresh_table()
        return True

    def add_source(self) -> None:
        dialog = SourceEditor(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_source:
            self.persist(lambda: self.workspaces.put_source(dialog.result_source))

    def edit_source(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        dialog = SourceEditor(self.profile["sources"][index], self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_source:
            self.persist(lambda: self.workspaces.put_source(dialog.result_source, index))

    def delete_source(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        source = self.profile["sources"][index]
        answer = QMessageBox.question(
            self, "删除来源", f"删除“{source['name']}”的订阅？已缓存的论文也会从列表移除。"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.persist(lambda: self.workspaces.delete_source(index))

    def add_imported(self, imported: list[Source]) -> None:
        added = self.workspaces.import_sources(imported)
        if added:
            self.changed = True
            self.refresh_table()
        QMessageBox.information(
            self, "导入完成", f"新增 {added} 个来源，跳过 {len(imported) - added} 个重复来源。"
        )

    def open_opml(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "选择 OPML 订阅文件", "", "OPML 文件 (*.opml *.xml)"
        )
        if selected:
            try:
                self.add_imported(import_opml(Path(selected)))
            except Exception as error:
                QMessageBox.warning(self, "导入失败", compact_error(error))

    def open_legacy(self) -> None:
        candidate = legacy_feed_path()
        start = str(candidate) if candidate.exists() else str(Path.home() / "Documents")
        selected, _ = QFileDialog.getOpenFileName(
            self, "选择旧版 feeds.json 或 feeds.default.json", start, "JSON 文件 (*.json)"
        )
        if selected:
            try:
                self.add_imported(import_legacy_feeds(Path(selected)))
            except Exception as error:
                QMessageBox.warning(self, "导入失败", compact_error(error))

    def save_opml(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self, "保存 OPML", f"{self.profile['name']}.opml", "OPML 文件 (*.opml)"
        )
        if selected:
            try:
                export_opml(Path(selected), self.profile["sources"])
                QMessageBox.information(
                    self, "导出完成", "已导出 RSS 来源。Crossref ISSN 来源保存在应用配置中。"
                )
            except Exception as error:
                QMessageBox.warning(self, "导出失败", compact_error(error))
