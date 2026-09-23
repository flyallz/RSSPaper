"""Universal, discipline-neutral journal reader for Windows."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from radar_core import (
    APP_NAME,
    compact_error,
    contains_cjk,
    create_source,
    current_profile,
    data_dir,
    default_state,
    export_opml,
    fetch_source,
    import_legacy_feeds,
    import_opml,
    is_recent_publication,
    load_state,
    new_profile,
    now_label,
    paper_date_label,
    save_state,
    sort_papers,
    translate_title,
    translation_key,
    valid_api_endpoint,
    valid_http_url,
)
from secret_store import load_api_key, save_api_key
from theme import STYLE


def resource_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / name


def make_button(text: str, role: str = "") -> QPushButton:
    button = QPushButton(text)
    if role:
        button.setObjectName(role)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class RefreshWorker(QThread):
    progress = Signal(str)
    loaded = Signal(object, object)

    def __init__(self, sources: list[dict], proxy: str):
        super().__init__()
        self.sources = [dict(source) for source in sources if source.get("enabled", True)]
        self.proxy = proxy

    def run(self) -> None:
        papers: dict[str, list[dict]] = {}
        statuses: dict[str, dict] = {}
        if not self.sources:
            self.loaded.emit(papers, statuses)
            return
        with ThreadPoolExecutor(max_workers=min(6, len(self.sources))) as pool:
            futures = {pool.submit(fetch_source, source, self.proxy): source for source in self.sources}
            for index, future in enumerate(as_completed(futures), 1):
                source = futures[future]
                try:
                    entries = future.result()
                    papers[source["id"]] = entries
                    statuses[source["id"]] = {"ok": True, "count": len(entries), "error": "", "time": now_label()}
                except Exception as error:
                    statuses[source["id"]] = {"ok": False, "count": 0, "error": compact_error(error), "time": now_label()}
                self.progress.emit(f"正在刷新 {index}/{len(self.sources)} 个来源…")
        self.loaded.emit(papers, statuses)


class TranslateWorker(QThread):
    translated = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, paper_id: str, title: str, endpoint: str, model: str, api_key: str, proxy: str, target_language: str = "zh", content_type: str = "title"):
        super().__init__()
        self.paper_id = paper_id
        self.title = title
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.proxy = proxy
        self.target_language = target_language
        self.content_type = content_type

    def run(self) -> None:
        try:
            self.translated.emit(self.paper_id, translate_title(self.title, self.endpoint, self.model, self.api_key, self.proxy, self.target_language, self.content_type))
        except Exception as error:
            self.failed.emit(self.paper_id, compact_error(error))


class SourceEditor(QDialog):
    def __init__(self, source: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.source = source
        self.result_source: dict | None = None
        self.setWindowTitle("编辑期刊来源" if source else "添加期刊来源")
        self.resize(780, 520)
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
        self.kind_box = QComboBox()
        self.kind_box.addItem("RSS / Atom 地址", "rss")
        self.kind_box.addItem("Crossref · ISSN", "crossref")
        self.kind_box.addItem("arXiv 主题检索", "arxiv")
        self.kind_box.setMinimumContentsLength(28)
        self.kind_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.kind_box.setView(QListView())
        self.kind_box.view().setMinimumWidth(360)
        self.value_edit = QLineEdit(source["value"] if source else "")
        self.include_edit = QLineEdit(", ".join(source.get("include_keywords", [])) if source else "")
        self.include_edit.setPlaceholderText("例如：augmented reality, learning analytics")
        self.exclude_edit = QLineEdit(", ".join(source.get("exclude_keywords", [])) if source else "")
        self.exclude_edit.setPlaceholderText("可选，例如：survey, correction")
        self.match_all = QCheckBox("必须同时包含全部关键词（默认匹配任一关键词）")
        self.match_all.setChecked(bool(source and source.get("match_all")))
        self.hint = QLabel()
        self.hint.setObjectName("notice")
        self.hint.setWordWrap(True)
        for field in (self.name_edit, self.kind_box, self.value_edit, self.include_edit, self.exclude_edit):
            field.setMinimumWidth(430)
        form.addRow("期刊名称", self.name_edit)
        form.addRow("来源类型", self.kind_box)
        form.addRow("地址 / ISSN", self.value_edit)
        form.addRow("", self.hint)
        form.addRow("二层包含关键词", self.include_edit)
        form.addRow("排除关键词", self.exclude_edit)
        form.addRow("匹配方式", self.match_all)
        layout.addWidget(panel)
        if source:
            self.kind_box.setCurrentIndex({"rss": 0, "crossref": 1, "arxiv": 2}.get(source["kind"], 0))
        self.kind_box.currentIndexChanged.connect(self.update_hint)
        self.update_hint()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
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
            self.value_edit.setPlaceholderText('例如 cs.HC，或 cat:cs.HC AND all:"augmented reality"')
            self.hint.setText("输入 arXiv 分类或检索式，按提交时间读取最新论文；可继续用下面的关键词做第二层筛选。")

    def save(self) -> None:
        try:
            result = create_source(
                self.name_edit.text(), self.kind_box.currentData(), self.value_edit.text(),
                self.include_edit.text(), self.exclude_edit.text(), self.match_all.isChecked(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "无法保存", str(error))
            return
        if self.source:
            result["id"] = self.source["id"]
            result["enabled"] = self.source.get("enabled", True)
        self.result_source = result
        self.accept()


class SourcesDialog(QDialog):
    def __init__(self, state: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.profile = current_profile(state)
        self.changed = False
        self.setWindowTitle("管理期刊来源")
        self.resize(820, 555)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel("管理期刊来源")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        subtitle = QLabel(f"当前学科：{self.profile['name']}　·　添加 RSS，或按 ISSN 从 Crossref 读取论文")
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
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
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

    def refresh_table(self) -> None:
        sources = self.profile["sources"]
        statuses = self.state["statuses"].get(self.profile["id"], {})
        self.table.setRowCount(len(sources))
        for row, source in enumerate(sources):
            status = statuses.get(source["id"])
            label = "尚未刷新" if not status else (f"成功 · {status['count']} 条" if status.get("ok") else "读取失败")
            type_label = {"rss": "RSS", "crossref": "Crossref", "arxiv": "arXiv"}.get(source["kind"], source["kind"])
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

    def persist(self) -> None:
        save_state(self.state)
        self.changed = True
        self.refresh_table()

    def add_source(self) -> None:
        dialog = SourceEditor(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_source:
            self.profile["sources"].append(dialog.result_source)
            self.persist()

    def edit_source(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        dialog = SourceEditor(self.profile["sources"][index], self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_source:
            self.profile["sources"][index] = dialog.result_source
            self.persist()

    def delete_source(self) -> None:
        index = self.selected_index()
        if index is None:
            return
        source = self.profile["sources"][index]
        answer = QMessageBox.question(self, "删除来源", f"删除“{source['name']}”的订阅？已缓存的论文也会从列表移除。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.profile["sources"].pop(index)
        self.state["papers"][self.profile["id"]] = [p for p in self.state["papers"].get(self.profile["id"], []) if p.get("source_id") != source["id"]]
        self.state["statuses"].get(self.profile["id"], {}).pop(source["id"], None)
        self.persist()

    def add_imported(self, imported: list[dict]) -> None:
        existing = {(s["kind"], s["value"].lower()) for s in self.profile["sources"]}
        added = 0
        for source in imported:
            key = (source["kind"], source["value"].lower())
            if key not in existing:
                self.profile["sources"].append(source)
                existing.add(key)
                added += 1
        if added:
            self.persist()
        QMessageBox.information(self, "导入完成", f"新增 {added} 个来源，跳过 {len(imported) - added} 个重复来源。")

    def open_opml(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "选择 OPML 订阅文件", "", "OPML 文件 (*.opml *.xml)")
        if selected:
            try:
                self.add_imported(import_opml(Path(selected)))
            except Exception as error:
                QMessageBox.warning(self, "导入失败", compact_error(error))

    def open_legacy(self) -> None:
        candidate = Path(os.environ.get("APPDATA", "")) / "EdTechRadar" / "feeds.json"
        start = str(candidate) if candidate.exists() else ""
        selected, _ = QFileDialog.getOpenFileName(self, "选择旧版 feeds.json 或 feeds.default.json", start, "JSON 文件 (*.json)")
        if selected:
            try:
                self.add_imported(import_legacy_feeds(Path(selected)))
            except Exception as error:
                QMessageBox.warning(self, "导入失败", compact_error(error))

    def save_opml(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(self, "保存 OPML", f"{self.profile['name']}.opml", "OPML 文件 (*.opml)")
        if selected:
            try:
                export_opml(Path(selected), self.profile["sources"])
                QMessageBox.information(self, "导出完成", "已导出 RSS 来源。Crossref ISSN 来源保存在应用配置中。")
            except Exception as error:
                QMessageBox.warning(self, "导出失败", compact_error(error))


class SettingsDialog(QDialog):
    def __init__(self, state: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.settings = state["settings"]
        self.key_path = data_dir() / "api-key.bin"
        self.test_worker: TranslateWorker | None = None
        self.setWindowTitle("应用设置")
        self.resize(820, 610)
        self.setMinimumWidth(740)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 23, 25, 22)
        layout.setSpacing(14)
        title = QLabel("应用设置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        intro = QLabel("翻译仅在点击论文卡片时调用：中文标题译为英文，其他标题译为中文；同一译题会本地缓存。")
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        panel = QFrame()
        panel.setObjectName("formCard")
        form = QFormLayout(panel)
        form.setContentsMargins(22, 20, 22, 20)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.endpoint = QLineEdit(self.settings.get("api_endpoint", ""))
        self.endpoint.setPlaceholderText("https://api.deepseek.com/chat/completions")
        self.model = QLineEdit(self.settings.get("api_model", "deepseek-flash"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("已保存密钥，留空表示不更改" if self.key_path.exists() else "输入 API 密钥")
        self.clear_key = QCheckBox("清除已保存的密钥")
        self.proxy = QLineEdit(self.settings.get("proxy", ""))
        self.proxy.setPlaceholderText("可选，例如 http://127.0.0.1:7890")
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 1440)
        self.minutes.setSpecialValueText("关闭自动刷新")
        self.minutes.setSingleStep(5)
        self.minutes.setSuffix(" 分钟")
        self.minutes.setValue(int(self.settings.get("refresh_minutes", 30)))
        self.minutes.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        for field in (self.endpoint, self.model, self.key_edit, self.proxy, self.minutes):
            field.setMinimumWidth(480)
        form.addRow("翻译接口完整地址", self.endpoint)
        form.addRow("模型名称", self.model)
        form.addRow("API 密钥", self.key_edit)
        form.addRow("", self.clear_key)
        form.addRow("网络代理", self.proxy)
        form.addRow("自动刷新间隔", self.minutes)
        layout.addWidget(panel)
        self.test_label = QLabel("密钥以 Windows 当前用户加密方式保存在本机；本地翻译接口可留空。")
        self.test_label.setObjectName("notice")
        self.test_label.setWordWrap(True)
        layout.addWidget(self.test_label)
        row = QHBoxLayout()
        self.test_button = make_button("测试翻译")
        self.test_button.clicked.connect(self.test_translation)
        row.addWidget(self.test_button)
        row.addStretch()
        self.save_button = make_button("保存设置", "primary")
        self.cancel_button = make_button("取消")
        self.save_button.clicked.connect(self.save)
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.cancel_button)
        row.addWidget(self.save_button)
        layout.addLayout(row)

    def test_translation(self) -> None:
        endpoint = self.endpoint.text().strip()
        model = self.model.text().strip()
        if not valid_api_endpoint(endpoint) or not model:
            QMessageBox.warning(self, "配置不完整", "请填写 HTTPS 翻译接口的完整地址和模型名称。")
            return
        try:
            key = self.key_edit.text().strip() or ("" if self.clear_key.isChecked() else load_api_key(self.key_path))
        except Exception as error:
            QMessageBox.warning(self, "密钥不可用", compact_error(error))
            return
        if not key and urlparse(endpoint).hostname not in ("localhost", "127.0.0.1", "::1"):
            QMessageBox.warning(self, "缺少密钥", "远程翻译接口需要 API 密钥，本地接口可留空。")
            return
        self.test_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.test_label.setText("正在测试翻译…")
        self.test_worker = TranslateWorker("test", "Learning with technology", endpoint, model, key, self.proxy.text().strip())
        self.test_worker.translated.connect(lambda _id, text: self.test_label.setText("测试成功：" + text))
        self.test_worker.failed.connect(lambda _id, error: self.test_label.setText("测试失败：" + error))
        self.test_worker.finished.connect(self.test_finished)
        self.test_worker.start()

    def test_finished(self) -> None:
        self.test_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def save(self) -> None:
        endpoint = self.endpoint.text().strip()
        proxy = self.proxy.text().strip()
        if endpoint and not valid_api_endpoint(endpoint):
            QMessageBox.warning(self, "地址无效", "翻译接口必须是 HTTPS，或本机 HTTP 地址。")
            return
        if proxy and not valid_http_url(proxy):
            QMessageBox.warning(self, "代理地址无效", "代理地址应以 http:// 或 https:// 开头。")
            return
        if 0 < self.minutes.value() < 5:
            QMessageBox.warning(self, "刷新间隔太短", "请选择至少 5 分钟，或设为关闭自动刷新。")
            return
        self.settings.update({"api_endpoint": endpoint, "api_model": self.model.text().strip(), "proxy": proxy, "refresh_minutes": self.minutes.value()})
        try:
            if self.clear_key.isChecked():
                save_api_key(self.key_path, "")
            elif self.key_edit.text().strip():
                save_api_key(self.key_path, self.key_edit.text().strip())
            save_state(self.state)
        except Exception as error:
            QMessageBox.warning(self, "保存失败", compact_error(error))
            return
        self.accept()

    def closeEvent(self, event) -> None:
        if self.test_worker and self.test_worker.isRunning():
            self.test_label.setText("请等待当前翻译测试完成。")
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self) -> None:
        if self.test_worker and self.test_worker.isRunning():
            self.test_label.setText("请等待当前翻译测试完成。")
            return
        super().reject()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.load_error = ""
        try:
            self.state = load_state()
        except Exception as error:
            self.state = default_state()
            self.load_error = compact_error(error)
        self.refresh_worker: RefreshWorker | None = None
        self.refresh_profile_id = ""
        self.translation_workers: dict[str, TranslateWorker] = {}
        self.card_parts: dict[str, tuple[QLabel, QPushButton]] = {}
        self.abstract_parts: dict[str, tuple[QLabel, QPushButton]] = {}
        self.visible_limit = 60
        self.setWindowTitle(APP_NAME + " · 通用版")
        icon = resource_path("assets/icon.svg")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.setMinimumSize(920, 620)
        self.resize(1190, 790)
        self.build_ui()
        self.update_profile_ui()
        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self.maybe_refresh)
        self.timer.start()
        if self.load_error:
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, "配置读取失败", "已使用临时空白工作区，原配置未覆盖。\n" + self.load_error))
        elif current_profile(self.state)["sources"] and int(self.state["settings"].get("refresh_minutes", 30)) > 0:
            QTimer.singleShot(250, self.maybe_refresh)

    def build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(21, 24, 21, 22)
        side.setSpacing(12)
        brand_row = QHBoxLayout()
        logo = QLabel()
        icon = resource_path("assets/icon.svg")
        if icon.exists():
            logo.setPixmap(QIcon(str(icon)).pixmap(47, 47))
        brand_row.addWidget(logo)
        brand = QLabel("期刊雷达")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        side.addLayout(brand_row)
        caption = QLabel("跨学科文献订阅 · Windows")
        caption.setObjectName("sidebarCaption")
        side.addWidget(caption)
        side.addSpacing(30)
        label = QLabel("当前学科")
        label.setObjectName("sidebarCaption")
        side.addWidget(label)
        self.profile_box = QComboBox()
        self.profile_box.setView(QListView())
        self.profile_box.currentIndexChanged.connect(self.change_profile)
        side.addWidget(self.profile_box)
        self.new_profile_button = make_button("＋ 新建学科", "sidebarAction")
        self.new_profile_button.clicked.connect(self.new_profile)
        side.addWidget(self.new_profile_button)
        profile_actions = QHBoxLayout()
        self.rename_button = make_button("重命名", "sidebarAction")
        self.delete_profile_button = make_button("删除", "sidebarAction")
        self.rename_button.clicked.connect(self.rename_profile)
        self.delete_profile_button.clicked.connect(self.delete_profile)
        profile_actions.addWidget(self.rename_button)
        profile_actions.addWidget(self.delete_profile_button)
        side.addLayout(profile_actions)
        side.addSpacing(22)
        self.nav_papers = make_button("近期论文", "navActive")
        self.nav_sources = make_button("管理期刊来源", "nav")
        self.nav_settings = make_button("翻译与网络设置", "nav")
        self.nav_papers.clicked.connect(lambda: self.paper_scroll.ensureVisible(0, 0))
        self.nav_sources.clicked.connect(self.open_sources)
        self.nav_settings.clicked.connect(self.open_settings)
        side.addWidget(self.nav_papers)
        side.addWidget(self.nav_sources)
        side.addWidget(self.nav_settings)
        side.addStretch()
        tip = QLabel("可添加 RSS 或 ISSN\n译文仅在点击时生成")
        tip.setObjectName("sidebarCaption")
        tip.setWordWrap(True)
        side.addWidget(tip)
        row.addWidget(sidebar)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(32, 29, 32, 24)
        main.setSpacing(17)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("把不同学科的期刊放在各自工作区，集中查看新论文。")
        self.page_subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles, 1)
        self.refresh_button = make_button("↻  刷新来源", "primary")
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        main.addLayout(header)

        stats = QHBoxLayout()
        stats.setSpacing(13)
        self.source_stat = self.make_stat("期刊来源")
        self.paper_stat = self.make_stat("缓存论文")
        self.updated_stat = self.make_stat("最近刷新")
        for frame, _value in (self.source_stat, self.paper_stat, self.updated_stat):
            stats.addWidget(frame, 1)
        main.addLayout(stats)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题或期刊名称…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_papers)
        controls.addWidget(self.search, 1)
        self.source_filter = QComboBox()
        self.source_filter.setMinimumWidth(160)
        self.source_filter.currentIndexChanged.connect(self.render_papers)
        controls.addWidget(self.source_filter)
        self.date_filter = QComboBox()
        self.date_filter.addItem("全部时间", 0)
        self.date_filter.addItem("近 7 天（精确日期）", 7)
        self.date_filter.addItem("近 30 天（精确日期）", 30)
        self.date_filter.setToolTip("来源只有期刊月份、没有具体日期的论文不会被纳入 7/30 天筛选。")
        self.date_filter.currentIndexChanged.connect(self.render_papers)
        controls.addWidget(self.date_filter)
        main.addLayout(controls)

        section_row = QHBoxLayout()
        section_title = QLabel("近期论文")
        section_title.setObjectName("sectionTitle")
        section_row.addWidget(section_title)
        section_row.addStretch()
        self.result_count = QLabel()
        self.result_count.setObjectName("pageSubtitle")
        section_row.addWidget(self.result_count)
        main.addLayout(section_row)

        self.paper_scroll = QScrollArea()
        self.paper_scroll.setWidgetResizable(True)
        self.paper_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.paper_holder = QWidget()
        self.paper_layout = QVBoxLayout(self.paper_holder)
        self.paper_layout.setContentsMargins(0, 0, 8, 0)
        self.paper_layout.setSpacing(11)
        self.paper_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.paper_scroll.setWidget(self.paper_holder)
        main.addWidget(self.paper_scroll, 1)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("notice")
        main.addWidget(self.status_label)
        row.addWidget(content, 1)

    def make_stat(self, label: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("statCard")
        column = QVBoxLayout(frame)
        column.setContentsMargins(19, 15, 19, 15)
        column.setSpacing(4)
        value = QLabel("—")
        value.setObjectName("statValue")
        caption = QLabel(label)
        caption.setObjectName("statLabel")
        column.addWidget(value)
        column.addWidget(caption)
        return frame, value

    def update_profile_ui(self) -> None:
        profile = current_profile(self.state)
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        for item in self.state["profiles"]:
            self.profile_box.addItem(item["name"], item["id"])
        self.profile_box.setCurrentIndex(next(i for i, p in enumerate(self.state["profiles"]) if p["id"] == profile["id"]))
        self.profile_box.blockSignals(False)
        self.page_title.setText(profile["name"])
        self.delete_profile_button.setEnabled(len(self.state["profiles"]) > 1)
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem("全部期刊", "")
        for source in profile["sources"]:
            self.source_filter.addItem(source["name"], source["id"])
        self.source_filter.blockSignals(False)
        self.source_stat[1].setText(str(len(profile["sources"])))
        self.paper_stat[1].setText(str(len(self.state["papers"].get(profile["id"], []))))
        self.updated_stat[1].setText(self.state["last_refresh"].get(profile["id"], "尚未刷新").split(" ")[-1])
        self.render_papers()

    def change_profile(self, index: int) -> None:
        if index < 0:
            return
        profile_id = self.profile_box.itemData(index)
        if profile_id == self.state["active_profile_id"]:
            return
        self.state["active_profile_id"] = profile_id
        save_state(self.state)
        self.search.clear()
        self.visible_limit = 60
        self.update_profile_ui()
        profile = current_profile(self.state)
        cached = self.state["papers"].get(profile["id"], [])
        if profile["sources"] and cached and not any(paper.get("abstract", "").strip() for paper in cached):
            self.status_label.setText("正在为当前学科补充摘要…")
            QTimer.singleShot(0, self.refresh)

    def new_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建学科", "学科或研究领域名称：")
        if not accepted or not name.strip():
            return
        profile = new_profile(name)
        self.state["profiles"].append(profile)
        self.state["active_profile_id"] = profile["id"]
        save_state(self.state)
        self.update_profile_ui()

    def rename_profile(self) -> None:
        profile = current_profile(self.state)
        name, accepted = QInputDialog.getText(self, "重命名学科", "学科名称：", text=profile["name"])
        if accepted and name.strip():
            profile["name"] = name.strip()
            save_state(self.state)
            self.update_profile_ui()

    def delete_profile(self) -> None:
        if len(self.state["profiles"]) <= 1:
            return
        profile = current_profile(self.state)
        answer = QMessageBox.question(self, "删除学科", f"删除“{profile['name']}”及该学科的来源和缓存论文？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.state["profiles"] = [p for p in self.state["profiles"] if p["id"] != profile["id"]]
        for name in ("papers", "statuses", "last_refresh"):
            self.state[name].pop(profile["id"], None)
        self.state["active_profile_id"] = self.state["profiles"][0]["id"]
        save_state(self.state)
        self.update_profile_ui()

    def open_sources(self) -> None:
        dialog = SourcesDialog(self.state, self)
        dialog.exec()
        if dialog.changed:
            self.update_profile_ui()
            self.refresh()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.state, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.status_label.setText("设置已保存。翻译只会在点击论文的按钮后执行。")

    def refresh(self) -> None:
        if self.refresh_worker and self.refresh_worker.isRunning():
            return
        profile = current_profile(self.state)
        sources = [s for s in profile["sources"] if s.get("enabled", True)]
        if not sources:
            self.status_label.setText("当前学科还没有来源，请先添加 RSS 或 ISSN。")
            self.open_sources()
            return
        self.refresh_profile_id = profile["id"]
        self.refresh_button.setEnabled(False)
        self.profile_box.setEnabled(False)
        self.status_label.setText(f"正在刷新 {len(sources)} 个来源…")
        self.refresh_worker = RefreshWorker(sources, self.state["settings"].get("proxy", ""))
        self.refresh_worker.progress.connect(self.status_label.setText)
        self.refresh_worker.loaded.connect(self.apply_refresh)
        self.refresh_worker.finished.connect(self.refresh_finished)
        self.refresh_worker.start()

    def apply_refresh(self, new_papers: dict, statuses: dict) -> None:
        profile_id = self.refresh_profile_id
        profile = next(p for p in self.state["profiles"] if p["id"] == profile_id)
        previous = self.state["papers"].get(profile_id, [])
        combined: list[dict] = []
        for source in profile["sources"]:
            if not source.get("enabled", True):
                continue
            if source["id"] in new_papers:
                combined.extend(new_papers[source["id"]])
            else:
                combined.extend(p for p in previous if p.get("source_id") == source["id"])
        unique: dict[str, dict] = {paper["id"]: paper for paper in combined}
        self.state["papers"][profile_id] = sort_papers(list(unique.values()))
        self.state["statuses"][profile_id] = statuses
        self.state["last_refresh"][profile_id] = now_label()
        try:
            save_state(self.state)
        except Exception as error:
            QMessageBox.warning(self, "缓存未保存", compact_error(error))
        ok = sum(1 for status in statuses.values() if status.get("ok"))
        self.status_label.setText(f"刷新完成：{ok}/{len(statuses)} 个来源可用。失败原因可在“管理期刊来源”中查看。")
        self.update_profile_ui()

    def refresh_finished(self) -> None:
        self.refresh_button.setEnabled(True)
        self.profile_box.setEnabled(True)

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

            elapsed = (datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M")).total_seconds() / 60
        except (ValueError, TypeError):
            elapsed = 10**6
        if elapsed >= interval:
            self.refresh()

    def clear_cards(self) -> None:
        self.card_parts.clear()
        self.abstract_parts.clear()
        while self.paper_layout.count():
            item = self.paper_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def render_papers(self) -> None:
        if not hasattr(self, "paper_layout"):
            return
        profile = current_profile(self.state)
        papers = self.state["papers"].get(profile["id"], [])
        query = self.search.text().strip().casefold()
        selected_source = self.source_filter.currentData() or ""
        days = self.date_filter.currentData() or 0
        visible = []
        for paper in papers:
            if selected_source and paper.get("source_id") != selected_source:
                continue
            if query and query not in (paper.get("title", "") + " " + paper.get("abstract", "") + " " + paper.get("source_name", "")).casefold():
                continue
            if days and not is_recent_publication(paper, days):
                continue
            visible.append(paper)
        self.clear_cards()
        self.result_count.setText(f"找到 {len(visible)} 条")
        if not visible:
            card = QFrame()
            card.setObjectName("emptyCard")
            column = QVBoxLayout(card)
            column.setContentsMargins(28, 42, 28, 42)
            column.setSpacing(12)
            heading = QLabel("还没有符合条件的论文" if profile["sources"] else "为这个学科添加第一本期刊")
            heading.setObjectName("sectionTitle")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail = QLabel("试着清除筛选条件，或刷新期刊来源。" if profile["sources"] else "用 RSS 地址或 ISSN 开始，也可以导入 OPML 订阅文件。")
            detail.setObjectName("pageSubtitle")
            detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            action = make_button("管理期刊来源", "primary")
            action.setFixedWidth(160)
            action.clicked.connect(self.open_sources)
            column.addWidget(heading)
            column.addWidget(detail)
            column.addWidget(action, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.paper_layout.addWidget(card)
            return
        for paper in visible[: self.visible_limit]:
            self.paper_layout.addWidget(self.make_paper_card(paper))
        if len(visible) > self.visible_limit:
            more = make_button(f"加载更多 · 还剩 {len(visible) - self.visible_limit} 条")
            more.clicked.connect(self.load_more)
            self.paper_layout.addWidget(more)

    def make_paper_card(self, paper: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("paperCard")
        column = QVBoxLayout(card)
        column.setContentsMargins(21, 18, 21, 17)
        column.setSpacing(9)
        title = QLabel(paper.get("title", ""))
        title.setObjectName("paperTitle")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(title)
        settings = self.state["settings"]
        target_language = "en" if contains_cjk(paper.get("title", "")) else "zh"
        key = translation_key(settings.get("api_endpoint", ""), settings.get("api_model", ""), paper.get("title", ""), target_language)
        translation = QLabel(self.state["translations"].get(key, ""))
        translation.setObjectName("translation")
        translation.setWordWrap(True)
        translation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        translation.setVisible(bool(translation.text()))
        column.addWidget(translation)
        abstract_text = paper.get("abstract", "").strip()
        abstract_kind = paper.get("abstract_kind") or ("fragment" if abstract_text.endswith(("...", "…")) else ("metadata" if abstract_text.lower().startswith("publication date:") else ("full" if abstract_text else "missing")))
        if abstract_text:
            collapsed = abstract_text[:360] + ("…" if len(abstract_text) > 360 else "")
            abstract = QLabel(collapsed)
            abstract.setObjectName("abstract")
            abstract.setWordWrap(True)
            abstract.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            column.addWidget(abstract)
            if abstract_kind in ("fragment", "metadata"):
                source_notice = QLabel("RSS 仅提供摘要片段" if abstract_kind == "fragment" else "RSS 仅提供出版信息，未提供论文摘要")
                source_notice.setObjectName("notice")
                column.addWidget(source_notice)
            abstract_target = "en" if contains_cjk(abstract_text) else "zh"
            abstract_key = translation_key(settings.get("api_endpoint", ""), settings.get("api_model", ""), "摘要：" + abstract_text, abstract_target)
            abstract_translation = QLabel(self.state["translations"].get(abstract_key, ""))
            abstract_translation.setObjectName("translation")
            abstract_translation.setWordWrap(True)
            abstract_translation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            abstract_translation.setVisible(bool(abstract_translation.text()))
            column.addWidget(abstract_translation)
            abstract_actions = QHBoxLayout()
            if len(abstract_text) > 360:
                toggle = make_button("展开摘要")
                toggle.setObjectName("textAction")
                toggle.clicked.connect(
                    lambda _checked=False, label=abstract, button=toggle, short=collapsed, full=abstract_text:
                    self.toggle_abstract(label, button, short, full)
                )
                abstract_actions.addWidget(toggle)
            abstract_translate_label = "摘要译为英文" if abstract_target == "en" else "摘要译为中文"
            abstract_translate = make_button("摘要已翻译" if abstract_translation.text() else abstract_translate_label)
            abstract_translate.setObjectName("textAction")
            abstract_translate.setEnabled(abstract_kind != "metadata" and not bool(abstract_translation.text()))
            if abstract_kind == "metadata":
                abstract_translate.setToolTip("当前 RSS 未提供摘要")
            abstract_translate.clicked.connect(lambda _checked=False, item=paper: self.translate_abstract(item))
            abstract_actions.addWidget(abstract_translate)
            abstract_actions.addStretch()
            column.addLayout(abstract_actions)
            self.abstract_parts[paper["id"]] = (abstract_translation, abstract_translate)
        footer = QHBoxLayout()
        date_label = paper_date_label(paper)
        meta = QLabel(f"{paper.get('source_name', '')}  ·  {date_label}")
        meta.setObjectName("paperMeta")
        footer.addWidget(meta)
        footer.addStretch()
        translate_label = "译为英文" if target_language == "en" else "译为中文"
        translate = make_button("已翻译" if translation.text() else translate_label)
        translate.setEnabled(not bool(translation.text()))
        translate.clicked.connect(lambda _checked=False, item=paper: self.translate_paper(item))
        open_button = make_button("打开原文 ↗")
        open_button.clicked.connect(lambda _checked=False, url=paper.get("url", ""): QDesktopServices.openUrl(QUrl(url)))
        footer.addWidget(translate)
        footer.addWidget(open_button)
        column.addLayout(footer)
        self.card_parts[paper["id"]] = (translation, translate)
        return card

    def toggle_abstract(self, label: QLabel, button: QPushButton, collapsed: str, full: str) -> None:
        expanded = button.text() == "收起摘要"
        label.setText(collapsed if expanded else full)
        button.setText("展开摘要" if expanded else "收起摘要")

    def load_more(self) -> None:
        self.visible_limit += 60
        self.render_papers()

    def translate_abstract(self, paper: dict) -> None:
        abstract_text = paper.get("abstract", "").strip()
        if not abstract_text:
            return
        self._translate_text(paper, abstract_text, "abstract")

    def translate_paper(self, paper: dict) -> None:
        self._translate_text(paper, paper.get("title", ""), "title")

    def _translate_text(self, paper: dict, text: str, content_type: str) -> None:
        settings = self.state["settings"]
        endpoint = settings.get("api_endpoint", "")
        model = settings.get("api_model", "")
        if not valid_api_endpoint(endpoint) or not model:
            QMessageBox.information(self, "先配置翻译", "请在“翻译与网络设置”中填写完整接口地址和模型。")
            self.open_settings()
            return
        try:
            key = load_api_key(data_dir() / "api-key.bin")
        except Exception as error:
            QMessageBox.warning(self, "密钥不可用", compact_error(error))
            return
        if not key and urlparse(endpoint).hostname not in ("localhost", "127.0.0.1", "::1"):
            QMessageBox.information(self, "先配置翻译", "远程翻译接口需要 API 密钥；本地接口可留空。")
            self.open_settings()
            return
        paper_id = paper["id"]
        target_language = "en" if contains_cjk(text) else "zh"
        worker_id = paper_id + (":abstract" if content_type == "abstract" else ":title")
        if worker_id in self.translation_workers:
            return
        parts = (self.abstract_parts if content_type == "abstract" else self.card_parts).get(paper_id)
        if parts:
            parts[1].setText("翻译中…")
            parts[1].setEnabled(False)
        worker = TranslateWorker(worker_id, text, endpoint, model, key, settings.get("proxy", ""), target_language, content_type)
        self.translation_workers[worker_id] = worker
        worker.translated.connect(lambda _id, result, item=paper, kind=content_type: self.translation_done(item, result, kind))
        worker.failed.connect(lambda _id, error, item=paper, kind=content_type: self.translation_failed(item, error, kind))
        worker.finished.connect(lambda item_id=worker_id: self.translation_workers.pop(item_id, None))
        worker.start()

    def translation_done(self, paper: dict, text: str, content_type: str = "title") -> None:
        settings = self.state["settings"]
        source_text = paper.get("abstract", "") if content_type == "abstract" else paper.get("title", "")
        target_language = "en" if contains_cjk(source_text) else "zh"
        cache_text = "摘要：" + source_text if content_type == "abstract" else source_text
        key = translation_key(settings.get("api_endpoint", ""), settings.get("api_model", ""), cache_text, target_language)
        self.state["translations"][key] = text
        try:
            save_state(self.state)
        except Exception as error:
            self.status_label.setText("译文已显示，但缓存保存失败：" + compact_error(error))
        parts = (self.abstract_parts if content_type == "abstract" else self.card_parts).get(paper["id"])
        if parts:
            parts[0].setText(text)
            parts[0].show()
            parts[1].setText("摘要已翻译" if content_type == "abstract" else "已翻译")
        self.status_label.setText("摘要译文已生成并缓存。" if content_type == "abstract" else "译题已生成并缓存。")

    def translation_failed(self, paper: dict, error: str, content_type: str = "title") -> None:
        parts = (self.abstract_parts if content_type == "abstract" else self.card_parts).get(paper["id"])
        if parts:
            source_text = paper.get("abstract", "") if content_type == "abstract" else paper.get("title", "")
            prefix = "摘要" if content_type == "abstract" else ""
            parts[1].setText(prefix + ("译为英文" if contains_cjk(source_text) else "译为中文"))
            parts[1].setEnabled(True)
        self.status_label.setText("翻译失败：" + error)
        QMessageBox.warning(self, "翻译失败", error)

    def closeEvent(self, event) -> None:
        active = (self.refresh_worker and self.refresh_worker.isRunning()) or any(worker.isRunning() for worker in self.translation_workers.values())
        if active:
            self.status_label.setText("请等待当前刷新或翻译完成后关闭窗口。")
            event.ignore()
        else:
            super().closeEvent(event)


def self_test() -> int:
    from radar_core import parse_rss

    source = create_source("示例", "rss", "https://example.org/feed.xml")
    papers = parse_rss(b"<rss><channel><item><title>Sample paper</title><link>https://example.org/paper</link></item></channel></rss>", source)
    return 0 if len(papers) == 1 and papers[0]["title"] == "Sample paper" else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--diagnose-feed" in sys.argv:
        index = sys.argv.index("--diagnose-feed")
        url = sys.argv[index + 1]
        papers = fetch_source(create_source("诊断", "rss", url))
        print(f"OK {len(papers)} {papers[0]['title']}")
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if "--gui-smoke" in sys.argv:
        QTimer.singleShot(1200, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
