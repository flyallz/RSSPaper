"""Preview registered citations before an explicit clipboard operation."""

from copy import deepcopy

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ..adapters.citations import FORMATS, CitationResult
from ..domain.papers import normalize_doi
from ..errors import compact_error
from ..services.citations import CitationJob, apply_citation
from .widgets import make_button
from .workers import CitationWorker


class CitationDialog(QDialog):
    def __init__(self, state, profile_id, paper, repository, parent=None):
        super().__init__(parent)
        self.setWindowTitle("复制引用")
        self.resize(720, 480)
        self.setMinimumSize(640, 360)
        self.state, self.profile_id = state, profile_id
        self.paper, self.repository = deepcopy(paper), repository
        self.worker = None
        self.close_when_finished = False
        self.result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("复制引用")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        note = QLabel("默认 APA 参考文献条目（纯文本）。引用使用原文登记信息；复制前请核对。")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.format_combo = QComboBox()
        for key, label in FORMATS.items():
            self.format_combo.addItem(label, key)
        row.addWidget(self.format_combo)
        self.doi_edit = QLineEdit(paper.get("doi") or paper.get("citation_doi", ""))
        self.doi_edit.setPlaceholderText("DOI；留空时按原文标题查找唯一匹配")
        row.addWidget(self.doi_edit, 1)
        self.fetch_button = make_button("获取引用")
        row.addWidget(self.fetch_button)
        layout.addLayout(row)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        original = make_button("打开原文 ↗")
        original.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.paper["url"])))
        actions.addWidget(original)
        actions.addStretch()
        self.copy_button = make_button("复制引用", "primary")
        self.copy_button.setEnabled(False)
        actions.addWidget(self.copy_button)
        self.close_button = make_button("关闭")
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.fetch_button.clicked.connect(self.load)
        self.format_combo.currentIndexChanged.connect(self.load)
        self.doi_edit.textChanged.connect(self.invalidate)
        self.copy_button.clicked.connect(self.copy)
        self.close_button.clicked.connect(self.reject)
        QTimer.singleShot(0, self.load)

    def invalidate(self):
        self.result = None
        self.preview.clear()
        self.copy_button.setEnabled(False)

    def load(self):
        if self.close_when_finished or (self.worker and self.worker.isRunning()):
            return
        self.invalidate()
        if self.doi_edit.text().strip() and not normalize_doi(self.doi_edit.text()):
            self.status.setText("DOI 格式无效，请填写 DOI 或 https://doi.org/ 链接。")
            return
        job = CitationJob.for_paper(
            self.profile_id,
            self.paper,
            self.format_combo.currentData(),
            self.state["settings"].get("proxy", ""),
            self.doi_edit.text().strip(),
        )
        cached = self.paper.get("citations", {}).get(job.format)
        if cached and job.doi == self.paper.get("citation_doi"):
            self.show_result(
                CitationResult(job.doi, job.format, cached, self.paper.get("citation_warning", ""))
            )
            return
        self.status.setText("正在核对 DOI 并获取引用…")
        self.set_busy(True)
        self.worker = CitationWorker(job)
        self.worker.loaded.connect(self.loaded)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.query_finished)
        self.worker.start()

    def set_busy(self, busy):
        for control in (self.format_combo, self.doi_edit, self.fetch_button):
            control.setEnabled(not busy)

    def loaded(self, result):
        if self.close_when_finished or self.worker.isInterruptionRequested():
            return
        if not apply_citation(self.state, self.worker.job, result):
            self.failed("论文或来源已变化，请关闭后重新打开")
            return
        self.paper.update(
            citations=deepcopy(
                next(
                    paper["citations"]
                    for paper in self.state["papers"][self.profile_id]
                    if paper["id"] == self.paper["id"]
                )
            ),
            citation_doi=result.doi,
            citation_warning=result.warnings,
        )
        try:
            self.repository.save(self.state)
        except Exception as error:
            self.failed("引用缓存保存失败：" + compact_error(error))
            return
        self.show_result(result)

    def show_result(self, result):
        self.result = result
        self.preview.setPlainText(result.text)
        self.copy_button.setEnabled(True)
        self.status.setText(
            f"DOI：{result.doi}" + ("\n" + result.warnings if result.warnings else "")
        )

    def failed(self, text):
        if not self.close_when_finished and not (
            self.worker and self.worker.isInterruptionRequested()
        ):
            self.invalidate()
            self.status.setText(text + "。可填写或核对 DOI 后重试；未修改剪贴板。")

    def query_finished(self):
        self.set_busy(False)
        if self.close_when_finished:
            super().reject()

    def copy(self):
        if self.result:
            QApplication.clipboard().setText(self.result.text)
            self.status.setText(
                "已复制 " + FORMATS[self.result.format] + " 引用。" + self.result.warnings
            )

    def reject(self):
        self.close_when_finished = True
        if self.worker:
            self.worker.requestInterruption()
            if self.worker.isRunning():
                self.close_button.setEnabled(False)
                self.copy_button.setEnabled(False)
                self.status.setText("正在取消查询，当前网络请求退出后关闭…")
                return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.reject()
            event.ignore()
        else:
            self.reject()
            event.accept()
