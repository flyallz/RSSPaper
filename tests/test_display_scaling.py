"""Fresh Qt processes verify both platforms' layout at common display scales."""

import os
import subprocess
import sys
import tempfile
import unittest

SCALING_CHECK = r"""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton
from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.platform.paths import default_font
from journal_radar.services.translations import TranslationJob
from journal_radar.ui.main_window import MainWindow
from journal_radar.ui.settings_dialog import SettingsDialog
from journal_radar.ui.source_editor import SourceEditor
from journal_radar.ui.theme import STYLE
app = QApplication([])
app.setFont(QFont(default_font(), 10))
app.setStyleSheet(STYLE)
window = MainWindow()
source = create_source("Learning and Instruction / Network and Distributed System Security Symposium", "rss", "https://example.org/rss")
profile = window.state["profiles"][0]
profile["sources"] = [source]
paper = make_paper(source, "How can I help you learn? Incorporating emotions into learning at home and school during a prolonged crisis", "https://example.org/a", "2027-02", "month", abstract="A long abstract about education. " * 90)
window.state["papers"][profile["id"]] = [paper]
job = TranslationJob.from_settings(paper["abstract"].strip(), window.state["settings"], "abstract")
window.state["translations"][job.cache_key] = "关于教育与学习的完整摘要译文。" * 120
window.update_profile_ui()
window.resize(820, 500)
window.show()
for _ in range(10): app.processEvents()
assert window.view.paper_scroll.height() > 220
card = window.view.paper_layout.itemAt(0).widget()
for button in card.findChildren(QPushButton):
    if button.isVisible():
        assert button.x() >= 0 and button.x() + button.width() <= card.width(), button.text()
        assert button.y() + button.height() <= card.height(), button.text()
for dialog in (SettingsDialog(window.state, window), SourceEditor(source, window)):
    dialog.resize(780, 500)
    dialog.show()
    for _ in range(6): app.processEvents()
    for field in dialog.findChildren(__import__('PySide6.QtWidgets', fromlist=['QLineEdit']).QLineEdit):
        assert field.isVisible() and field.width() >= 400
    dialog.form_scroll.ensureWidgetVisible(field)
    for _ in range(6): app.processEvents()
    assert dialog.form_scroll.verticalScrollBar().value() >= 0
    for button in dialog.findChildren(QPushButton):
        if button.isVisible() and not dialog.form_scroll.isAncestorOf(button):
            assert button.y() + button.height() <= dialog.height()
    dialog.close()
window.close()
"""


class DisplayScalingTests(unittest.TestCase):
    def test_layout_at_100_150_and_200_percent(self):
        for scale in ("1", "1.5", "2"):
            with self.subTest(scale=scale), tempfile.TemporaryDirectory() as folder:
                env = {
                    **os.environ,
                    "QT_QPA_PLATFORM": "offscreen",
                    "QT_SCALE_FACTOR": scale,
                    "JOURNAL_RADAR_HOME": folder,
                }
                result = subprocess.run(
                    [sys.executable, "-c", SCALING_CHECK],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=25,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
