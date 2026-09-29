"""Main window for both desktop platforms."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from journal_radar.adapters.translation import contains_cjk
from journal_radar.config import APP_NAME
from journal_radar.domain.state import default_state
from journal_radar.domain.validation import valid_api_endpoint
from journal_radar.errors import compact_error
from journal_radar.platform.paths import data_dir
from journal_radar.platform.secrets import load_api_key
from journal_radar.storage import StateRepository, current_profile

from ..adapters.abstracts import AbstractResult
from ..domain.models import AppState, ContentType, Paper, SourceStatus
from ..services import TranslationJob, apply_refresh, select_papers
from ..services.abstracts import AbstractJob, apply_abstract
from ..services.workspaces import WorkspaceService
from .main_view import MainView
from .paper_card import PaperCard
from .settings_dialog import SettingsDialog
from .sources_dialog import SourcesDialog
from .widgets import make_button, resource_path
from .workers import AbstractWorker, RefreshWorker, TranslateWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.repository = StateRepository()
        self.load_error = ""
        try:
            self.state: AppState = self.repository.load()
        except Exception as error:
            self.state = default_state()
            self.load_error = compact_error(error)
        self.workspaces = WorkspaceService(self.state, self.repository)
        self.refresh_worker: RefreshWorker | None = None
        self.refresh_profile_id = ""
        self.translation_workers: dict[str, TranslateWorker] = {}
        self.abstract_workers: dict[tuple[str, str], AbstractWorker] = {}
        self.card_parts: dict[str, tuple[QLabel, QPushButton]] = {}
        self.abstract_parts: dict[str, tuple[QLabel, QPushButton]] = {}
        self.card_cache_keys: dict[str, str] = {}
        self.visible_limit = 60
        self.setWindowTitle(APP_NAME + " · 通用版")
        icon = resource_path("assets/icon.svg")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.setMinimumSize(920, 620)
        self.resize(1190, 790)
        self.view = MainView(self)
        self.setCentralWidget(self.view)
        self.view.profile_changed.connect(self.change_profile)
        self.view.new_profile_requested.connect(self.new_profile)
        self.view.rename_profile_requested.connect(self.rename_profile)
        self.view.delete_profile_requested.connect(self.delete_profile)
        self.view.sources_requested.connect(self.open_sources)
        self.view.settings_requested.connect(self.open_settings)
        self.view.refresh_requested.connect(self.refresh)
        self.view.filters_changed.connect(self.render_papers)
        self.update_profile_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.maybe_refresh)
        self.timer.start()
        if self.load_error:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(
                    self, "配置读取失败", "已使用临时空白工作区，原配置未覆盖。\n" + self.load_error
                ),
            )
        elif (
            current_profile(self.state)["sources"]
            and int(self.state["settings"].get("refresh_minutes", 30)) > 0
        ):
            QTimer.singleShot(250, self.maybe_refresh)

    def update_profile_ui(self) -> None:
        profile = current_profile(self.state)
        self.view.profile_box.blockSignals(True)
        self.view.profile_box.clear()
        for item in self.state["profiles"]:
            self.view.profile_box.addItem(item["name"], item["id"])
        self.view.profile_box.setCurrentIndex(
            next(i for i, p in enumerate(self.state["profiles"]) if p["id"] == profile["id"])
        )
        self.view.profile_box.blockSignals(False)
        self.view.page_title.setText(profile["name"])
        self.view.delete_profile_button.setEnabled(len(self.state["profiles"]) > 1)
        self.view.source_filter.blockSignals(True)
        self.view.source_filter.clear()
        self.view.source_filter.addItem("全部期刊", "")
        for source in profile["sources"]:
            self.view.source_filter.addItem(source["name"], source["id"])
        self.view.source_filter.blockSignals(False)
        self.view.source_stat[1].setText(str(len(profile["sources"])))
        self.view.paper_stat[1].setText(str(len(self.state["papers"].get(profile["id"], []))))
        self.view.updated_stat[1].setText(
            self.state["last_refresh"].get(profile["id"], "尚未刷新").split(" ")[-1]
        )
        self.render_papers()

    def change_profile(self, index: int) -> None:
        if index < 0:
            return
        profile_id = self.view.profile_box.itemData(index)
        if profile_id == self.state["active_profile_id"]:
            return
        if not self.commit_edit(lambda: self.workspaces.select_profile(profile_id)):
            self.update_profile_ui()
            return
        self.view.search.clear()
        self.visible_limit = 60
        self.update_profile_ui()
        profile = current_profile(self.state)
        cached = self.state["papers"].get(profile["id"], [])
        if (
            profile["sources"]
            and cached
            and not any(paper.get("abstract", "").strip() for paper in cached)
        ):
            self.view.status_label.setText("正在为当前学科补充摘要…")
            QTimer.singleShot(0, self.refresh)

    def new_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建学科", "学科或研究领域名称：")
        if not accepted or not name.strip():
            return
        if not self.commit_edit(lambda: self.workspaces.add_profile(name)):
            return
        self.update_profile_ui()

    def rename_profile(self) -> None:
        profile = current_profile(self.state)
        name, accepted = QInputDialog.getText(
            self, "重命名学科", "学科名称：", text=profile["name"]
        )
        if accepted and name.strip():
            if not self.commit_edit(lambda: self.workspaces.rename_profile(name)):
                return
            self.update_profile_ui()

    def delete_profile(self) -> None:
        if len(self.state["profiles"]) <= 1:
            return
        profile = current_profile(self.state)
        answer = QMessageBox.question(
            self, "删除学科", f"删除“{profile['name']}”及该学科的来源和缓存论文？"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.commit_edit(self.workspaces.delete_profile):
            return
        self.update_profile_ui()

    def commit_edit(self, action: Callable[[], None]) -> bool:
        try:
            action()
            return True
        except Exception as error:
            QMessageBox.warning(self, "保存失败", compact_error(error))
            return False

    def open_sources(self) -> None:
        dialog = SourcesDialog(self.state, self, self.repository)
        dialog.exec()
        if dialog.changed:
            self.update_profile_ui()
            self.refresh()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.state, self, self.repository)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.render_papers()
            self.view.status_label.setText("设置已保存。翻译只会在点击论文的按钮后执行。")

    def refresh(self) -> None:
        if self.refresh_worker and self.refresh_worker.isRunning():
            return
        profile = current_profile(self.state)
        sources = [s for s in profile["sources"] if s.get("enabled", True)]
        if not sources:
            self.view.status_label.setText("当前学科还没有来源，请先添加 RSS 或 ISSN。")
            self.open_sources()
            return
        self.refresh_profile_id = profile["id"]
        self.view.refresh_button.setEnabled(False)
        self.view.profile_box.setEnabled(False)
        self.view.status_label.setText(f"正在刷新 {len(sources)} 个来源…")
        self.refresh_worker = RefreshWorker(sources, self.state["settings"].get("proxy", ""))
        self.refresh_worker.progress.connect(self.view.status_label.setText)
        self.refresh_worker.loaded.connect(self.apply_refresh)
        self.refresh_worker.finished.connect(self.refresh_finished)
        self.refresh_worker.start()

    def apply_refresh(
        self, new_papers: dict[str, list[Paper]], statuses: dict[str, SourceStatus]
    ) -> None:
        profile_id = self.refresh_profile_id
        if not apply_refresh(self.state, profile_id, new_papers, statuses):
            return
        try:
            self.repository.save(self.state)
        except Exception as error:
            QMessageBox.warning(self, "缓存未保存", compact_error(error))
        ok = sum(1 for status in statuses.values() if status.get("ok"))
        self.view.status_label.setText(
            f"刷新完成：{ok}/{len(statuses)} 个来源可用。失败原因可在“管理期刊来源”中查看。"
        )
        self.update_profile_ui()

    def refresh_finished(self) -> None:
        self.view.refresh_button.setEnabled(True)
        self.view.profile_box.setEnabled(True)

    def maybe_refresh(self) -> None:
        if self.refresh_worker and self.refresh_worker.isRunning():
            return
        interval = int(self.state["settings"].get("refresh_minutes", 30))
        if interval <= 0:
            return
        profile = current_profile(self.state)
        if not profile["sources"]:
            return
        last = self.state["last_refresh"].get(profile["id"])
        try:
            from datetime import datetime

            elapsed = (
                datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M")
            ).total_seconds() / 60
        except (ValueError, TypeError):
            elapsed = 10**6
        if elapsed >= interval:
            self.refresh()

    def clear_cards(self) -> None:
        self.card_parts.clear()
        self.abstract_parts.clear()
        self.card_cache_keys.clear()
        while self.view.paper_layout.count():
            item = self.view.paper_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_papers(self) -> None:
        if not hasattr(self, "view"):
            return
        profile = current_profile(self.state)
        papers = self.state["papers"].get(profile["id"], [])
        query = self.view.search.text().strip().casefold()
        selected_source = self.view.source_filter.currentData() or ""
        days = self.view.date_filter.currentData() or 0
        visible = select_papers(papers, query, selected_source, days)
        self.clear_cards()
        self.view.result_count.setText(f"找到 {len(visible)} 条")
        if not visible:
            card = QFrame()
            card.setObjectName("emptyCard")
            column = QVBoxLayout(card)
            column.setContentsMargins(28, 42, 28, 42)
            column.setSpacing(12)
            heading = QLabel(
                "还没有符合条件的论文" if profile["sources"] else "为这个学科添加第一本期刊"
            )
            heading.setObjectName("sectionTitle")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail = QLabel(
                "试着清除筛选条件，或刷新期刊来源。"
                if profile["sources"]
                else "用 RSS 地址或 ISSN 开始，也可以导入 OPML 订阅文件。"
            )
            detail.setObjectName("pageSubtitle")
            detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            action = make_button("管理期刊来源", "primary")
            action.setFixedWidth(160)
            action.clicked.connect(self.open_sources)
            column.addWidget(heading)
            column.addWidget(detail)
            column.addWidget(action, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.view.paper_layout.addWidget(card)
            return
        for paper in visible[: self.visible_limit]:
            self.view.paper_layout.addWidget(self.make_paper_card(paper))
        if len(visible) > self.visible_limit:
            more = make_button(f"加载更多 · 还剩 {len(visible) - self.visible_limit} 条")
            more.clicked.connect(self.load_more)
            self.view.paper_layout.addWidget(more)

    def make_paper_card(self, paper: Paper) -> PaperCard:
        card = PaperCard(paper, self.state["settings"], self.state["translations"])
        card.title_requested.connect(lambda: self.translate_paper(paper))
        card.abstract_requested.connect(lambda: self.translate_abstract(paper))
        card.enrichment_requested.connect(lambda: self.enrich_abstract(paper))
        pending = (current_profile(self.state)["id"], paper["id"]) in self.abstract_workers
        if pending and card.enrichment_button:
            card.enrichment_button.setText("正在获取摘要…")
            card.enrichment_button.setEnabled(False)
        self.card_parts[paper["id"]] = card.title_parts
        self.card_cache_keys[paper["id"] + ":title"] = TranslationJob.from_settings(
            paper["title"], self.state["settings"]
        ).cache_key
        if card.abstract_parts:
            self.abstract_parts[paper["id"]] = card.abstract_parts
            self.card_cache_keys[paper["id"] + ":abstract"] = TranslationJob.from_settings(
                paper.get("abstract", "").strip(), self.state["settings"], "abstract"
            ).cache_key
        for kind, parts in (("title", card.title_parts), ("abstract", card.abstract_parts)):
            worker = self.translation_workers.get(paper["id"] + ":" + kind)
            if parts and worker:
                same_text = worker.job.cache_key == self.card_cache_keys.get(
                    paper["id"] + ":" + kind
                )
                parts[1].setText("翻译中…" if same_text else "等待之前的翻译…")
                parts[1].setEnabled(False)
        return card

    def enrich_abstract(self, paper: Paper) -> None:
        job = AbstractJob.for_paper(
            current_profile(self.state)["id"], paper, self.state["settings"].get("proxy", "")
        )
        key = (job.profile_id, job.paper_id)
        if key in self.abstract_workers:
            return
        if len(self.abstract_workers) >= 3:
            self.view.status_label.setText("已有三个摘要查询正在进行，请稍后再试。")
            return
        worker = AbstractWorker(job)
        self.abstract_workers[key] = worker
        worker.loaded.connect(lambda result: self.abstract_done(job, result))
        worker.failed.connect(lambda error: self.abstract_done(job, error=error))
        worker.finished.connect(lambda: self.abstract_finished(key))
        self.render_papers()
        self.view.status_label.setText("正在查询摘要，现有论文仍可阅读。")
        worker.start()

    def abstract_done(
        self, job: AbstractJob, result: AbstractResult | None = None, error: str = ""
    ) -> None:
        if not apply_abstract(self.state, job, result, error):
            return
        save_error = ""
        try:
            self.repository.save(self.state)
        except Exception as failure:
            save_error = compact_error(failure)
        if current_profile(self.state)["id"] == job.profile_id:
            self.render_papers()
            self.view.status_label.setText(
                "摘要结果未保存：" + save_error
                if save_error
                else ("完整摘要已获取并缓存，可展开或翻译。" if result else "摘要未补全：" + error)
            )

    def abstract_finished(self, key: tuple[str, str]) -> None:
        self.abstract_workers.pop(key, None)
        if current_profile(self.state)["id"] == key[0]:
            self.render_papers()

    def load_more(self) -> None:
        self.visible_limit += 60
        self.render_papers()

    def translate_abstract(self, paper: Paper) -> None:
        abstract_text = paper.get("abstract", "").strip()
        if not abstract_text:
            return
        self._translate_text(paper, abstract_text, "abstract")

    def translate_paper(self, paper: Paper) -> None:
        self._translate_text(paper, paper.get("title", ""), "title")

    def _translate_text(self, paper: Paper, text: str, content_type: ContentType) -> None:
        settings = self.state["settings"]
        endpoint = settings.get("api_endpoint", "")
        model = settings.get("api_model", "")
        if not valid_api_endpoint(endpoint) or not model:
            QMessageBox.information(
                self, "先配置翻译", "请在“翻译与网络设置”中填写完整接口地址和模型。"
            )
            self.open_settings()
            return
        try:
            key = load_api_key(data_dir() / "api-key.bin")
        except Exception as error:
            QMessageBox.warning(self, "密钥不可用", compact_error(error))
            return
        if not key and urlparse(endpoint).hostname not in ("localhost", "127.0.0.1", "::1"):
            QMessageBox.information(
                self, "先配置翻译", "远程翻译接口需要 API 密钥；本地接口可留空。"
            )
            self.open_settings()
            return
        paper_id = paper["id"]
        target_language = "en" if contains_cjk(text) else "zh"
        worker_id = paper_id + (":abstract" if content_type == "abstract" else ":title")
        if worker_id in self.translation_workers:
            return
        parts = (self.abstract_parts if content_type == "abstract" else self.card_parts).get(
            paper_id
        )
        if parts:
            parts[1].setText("翻译中…")
            parts[1].setEnabled(False)
        worker = TranslateWorker(
            worker_id,
            text,
            endpoint,
            model,
            key,
            settings.get("proxy", ""),
            target_language,
            content_type,
        )
        self.translation_workers[worker_id] = worker
        worker.translated.connect(
            lambda _id, result, item=paper, job=worker.job: self.translation_done(item, result, job)
        )
        worker.failed.connect(
            lambda _id, error, item=paper, kind=content_type: self.translation_failed(
                item, error, kind
            )
        )
        worker.finished.connect(lambda item_id=worker_id: self.translation_finished(item_id))
        worker.start()

    def translation_finished(self, worker_id: str) -> None:
        self.translation_workers.pop(worker_id, None)
        self.render_papers()

    def translation_done(self, paper: Paper, text: str, job: TranslationJob) -> None:
        content_type = job.content_type
        self.state["translations"][job.cache_key] = text
        save_error = ""
        try:
            self.repository.save(self.state)
        except Exception as error:
            save_error = compact_error(error)
        current_job = TranslationJob.from_settings(job.text, self.state["settings"], content_type)
        parts = (self.abstract_parts if content_type == "abstract" else self.card_parts).get(
            paper["id"]
        )
        displayed_key = self.card_cache_keys.get(paper["id"] + ":" + content_type)
        if parts and current_job.cache_key == job.cache_key and displayed_key == job.cache_key:
            parts[0].setText(text)
            parts[0].show()
            parts[1].setText("摘要已翻译" if content_type == "abstract" else "已翻译")
        elif parts:
            self.render_papers()
        self.view.status_label.setText(
            "译文已生成，但缓存保存失败：" + save_error
            if save_error
            else ("摘要译文已生成并缓存。" if content_type == "abstract" else "译题已生成并缓存。")
        )

    def translation_failed(
        self, paper: Paper, error: str, content_type: ContentType = "title"
    ) -> None:
        parts = (self.abstract_parts if content_type == "abstract" else self.card_parts).get(
            paper["id"]
        )
        if parts:
            source_text = (
                paper.get("abstract", "") if content_type == "abstract" else paper.get("title", "")
            )
            prefix = "摘要" if content_type == "abstract" else ""
            parts[1].setText(prefix + ("译为英文" if contains_cjk(source_text) else "译为中文"))
            parts[1].setEnabled(True)
        self.view.status_label.setText("翻译失败：" + error)
        QMessageBox.warning(self, "翻译失败", error)

    def closeEvent(self, event) -> None:
        active = (
            (self.refresh_worker and self.refresh_worker.isRunning())
            or any(worker.isRunning() for worker in self.translation_workers.values())
            or any(worker.isRunning() for worker in self.abstract_workers.values())
        )
        if active:
            self.view.status_label.setText("请等待当前刷新、摘要获取或翻译完成后关闭窗口。")
            event.ignore()
        else:
            super().closeEvent(event)
