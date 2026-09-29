"""Explicit venue lookup, preview and selection of publication tags."""

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..errors import compact_error
from ..platform.secrets import load_api_key
from ..services.ranks import apply_rank, cached_rank
from .widgets import make_button
from .workers import RankWorker


class RankDialog(QDialog):
    def __init__(self, state, profile_id, paper, repository, parent=None):
        super().__init__(parent)
        self.state, self.profile_id = state, profile_id
        self.paper, self.repository = deepcopy(paper), repository
        self.worker = None
        self.cancel_when_finished = False
        self.setWindowTitle("期刊与会议标签")
        self.resize(720, 480)
        self.setMinimumSize(640, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        note = QLabel(
            "核对正式刊名或会议名后查询。arXiv 分类不是期刊，未发表的预印本不应填写期刊名。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.name_edit = QLineEdit(paper.get("publication_name", ""))
        self.name_edit.setPlaceholderText("例如 Computers & Education；可在编辑来源中设置正式刊名")
        row.addWidget(self.name_edit, 1)
        self.query_button = make_button("查询 / 更新", "primary")
        row.addWidget(self.query_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["等级体系", "等级 / 指标", "年度"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 230)
        self.table.setColumnWidth(1, 200)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.status = QLabel("数据来自 easyScholar；不提供年度的字段会明确标注。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.close_button = make_button("关闭")
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.query_button.clicked.connect(self.query)
        self.close_button.clicked.connect(self.reject)
        self.name_edit.textChanged.connect(self.clear_result)
        cached = cached_rank(state, self.name_edit.text())
        if cached:
            self.show_result(cached)

    def clear_result(self):
        self.table.setRowCount(0)
        self.status.setText("请核对名称后查询；不会使用来源别名自动匹配期刊。")

    def show_result(self, record):
        self.table.setRowCount(len(record["labels"]))
        for row, label in enumerate(record["labels"]):
            for column, value in enumerate(
                (label["label"], label["value"], label["year"] or "接口未提供")
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
        self.status.setText(
            f"easyScholar · {record['name']} · 获取于 {record['retrieved_at'][:10]}"
            + (
                "；未查到等级信息，不代表期刊没有等级。"
                if not record["labels"]
                else "；卡片显示哪些体系可在应用设置中选择。"
            )
        )

    def query(self):
        if self.worker and self.worker.isRunning():
            return
        name = self.name_edit.text().strip()
        if not name:
            self.status.setText("请填写正式期刊或会议名称。")
            return
        try:
            key = load_api_key(self.repository.folder / "easyscholar-key.bin")
        except Exception as error:
            self.status.setText(compact_error(error))
            return
        if not key or not self.state["settings"].get("rank_enabled"):
            self.status.setText("请在应用设置中启用期刊标签，并保存 easyScholar 密钥。")
            return
        self.table.setRowCount(0)
        self.status.setText("正在查询 easyScholar…")
        self.name_edit.setEnabled(False)
        self.query_button.setEnabled(False)
        self.worker = RankWorker(name, key, self.state["settings"].get("proxy", ""))
        self.worker.loaded.connect(self.loaded)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.query_finished)
        self.worker.start()

    def loaded(self, record):
        if self.cancel_when_finished or self.worker.isInterruptionRequested():
            return
        candidate = deepcopy(self.state)
        if not apply_rank(candidate, self.profile_id, self.paper, record):
            self.status.setText("论文或来源已变化，请重新打开查询。")
            return
        try:
            self.repository.save(candidate)
        except Exception as error:
            self.failed("保存失败：" + compact_error(error))
            return
        self.state.clear()
        self.state.update(candidate)
        self.show_result(record)

    def failed(self, text):
        if not self.cancel_when_finished and not self.worker.isInterruptionRequested():
            self.status.setText(text)

    def query_finished(self):
        self.name_edit.setEnabled(True)
        self.query_button.setEnabled(True)
        if self.cancel_when_finished:
            super().reject()

    def reject(self):
        self.cancel_when_finished = True
        if self.worker:
            self.worker.requestInterruption()
            if self.worker.isRunning():
                self.close_button.setEnabled(False)
                self.status.setText("正在取消查询，等待当前请求退出后关闭…")
                return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            self.reject()
            event.accept()
