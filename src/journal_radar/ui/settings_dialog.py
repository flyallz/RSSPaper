"""Settings dialog for both desktop platforms."""

from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from journal_radar.domain.validation import valid_api_endpoint, valid_http_url
from journal_radar.errors import compact_error
from journal_radar.platform.paths import data_dir
from journal_radar.platform.secrets import load_api_key
from journal_radar.storage import StateRepository

from ..domain.models import AppState
from ..platform.paths import secret_storage_description
from ..services.workspaces import WorkspaceService
from .widgets import make_button
from .workers import TranslateWorker


class SettingsDialog(QDialog):
    def __init__(
        self,
        state: AppState,
        parent: QWidget | None = None,
        repository: StateRepository | None = None,
    ):
        super().__init__(parent)
        self.repository = repository or StateRepository()
        self.workspaces = WorkspaceService(state, self.repository)
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
        intro = QLabel(
            "翻译仅在点击论文卡片时调用：中文标题译为英文，其他标题译为中文；同一译题会本地缓存。"
        )
        intro.setObjectName("pageSubtitle")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        panel = QFrame()
        panel.setObjectName("formCard")
        form = QFormLayout(panel)
        form.setContentsMargins(24, 22, 24, 22)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.endpoint = QLineEdit(self.settings.get("api_endpoint", ""))
        self.endpoint.setPlaceholderText("https://api.deepseek.com/chat/completions")
        self.model = QLineEdit(self.settings.get("api_model", "deepseek-flash"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("输入新密钥；留空则保留已保存的密钥")
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
        self.test_label = QLabel(secret_storage_description())
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
            key = self.key_edit.text().strip() or (
                "" if self.clear_key.isChecked() else load_api_key(self.key_path)
            )
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
        self.test_worker = TranslateWorker(
            "test", "Learning with technology", endpoint, model, key, self.proxy.text().strip()
        )
        self.test_worker.translated.connect(
            lambda _id, text: self.test_label.setText("测试成功：" + text)
        )
        self.test_worker.failed.connect(
            lambda _id, error: self.test_label.setText("测试失败：" + error)
        )
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
        settings = dict(
            {
                "api_endpoint": endpoint,
                "api_model": self.model.text().strip(),
                "proxy": proxy,
                "refresh_minutes": self.minutes.value(),
            }
        )
        credential = "" if self.clear_key.isChecked() else (self.key_edit.text().strip() or None)
        try:
            self.workspaces.save_settings(settings, credential)
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
