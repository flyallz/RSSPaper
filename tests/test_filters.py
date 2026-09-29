"""Exercise native control signals through to the displayed paper list."""

import os
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.domain.state import new_profile
from journal_radar.ui.main_window import MainWindow


class FilterUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        environment = patch.dict(os.environ, JOURNAL_RADAR_HOME=self.folder.name)
        environment.start()
        self.addCleanup(environment.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.profile = self.window.state["profiles"][0]
        self.first = create_source("教育研究", "rss", "https://example.org/a")
        self.second = create_source("计算机期刊", "rss", "https://example.org/b")
        self.profile["sources"] = [self.first, self.second]
        today = date.today()
        self.window.state["papers"][self.profile["id"]] = [
            make_paper(
                self.first,
                "教育何为",
                "https://example.org/one",
                today.isoformat(),
                "day",
                abstract="教育摘要",
            ),
            make_paper(
                self.first,
                "历史教育论文",
                "https://example.org/two",
                (today - timedelta(days=60)).isoformat(),
                "day",
                abstract="历史摘要",
            ),
            make_paper(
                self.second,
                "Machine learning",
                "https://example.org/three",
                today.isoformat(),
                "day",
                abstract="An abstract.",
            ),
        ]
        self.window.update_profile_ui()

    def titles(self):
        layout = self.window.view.paper_layout
        return [
            label.text()
            for index in range(layout.count())
            for label in layout.itemAt(index).widget().findChildren(QLabel)
            if label.objectName() == "paperTitle"
        ]

    def test_typing_search_and_clearing_rebuilds_results(self):
        self.window.view.search.setText("教育何为")
        self.assertEqual(self.titles(), ["教育何为"])
        self.window.view.search.setText("教育何为1")
        self.assertEqual(self.titles(), [])
        self.assertEqual(self.window.view.result_count.text(), "找到 0 条")
        self.window.view.search.clear()
        self.assertEqual(len(self.titles()), 3)

    def test_source_and_date_controls_combine_with_search(self):
        view = self.window.view
        view.source_filter.setCurrentIndex(view.source_filter.findData(self.first["id"]))
        self.assertEqual(self.titles(), ["教育何为", "历史教育论文"])
        view.date_filter.setCurrentIndex(view.date_filter.findData(7))
        self.assertEqual(self.titles(), ["教育何为"])
        view.search.setText("Machine")
        self.assertEqual(self.titles(), [])
        view.source_filter.setCurrentIndex(0)
        self.assertEqual(self.titles(), ["Machine learning"])
        view.search.clear()
        self.assertEqual(self.titles(), ["教育何为", "Machine learning"])
        view.date_filter.setCurrentIndex(0)
        self.assertEqual(len(self.titles()), 3)

    def test_refresh_keeps_selected_source_and_query(self):
        view = self.window.view
        view.source_filter.setCurrentIndex(view.source_filter.findData(self.first["id"]))
        view.search.setText("教育")
        fresh = make_paper(self.second, "教育技术与计算机", "https://example.org/new", "")
        # Apply to the profile captured when the refresh worker started.
        self.window.refresh_profile_id = self.profile["id"]
        self.window.apply_refresh({self.second["id"]: [fresh]}, {})
        self.assertEqual(view.source_filter.currentData(), self.first["id"])
        self.assertEqual(view.search.text(), "教育")
        self.assertEqual(self.titles(), ["教育何为", "历史教育论文"])

    def test_removed_source_or_changed_profile_resets_invalid_source_filter(self):
        view = self.window.view
        view.source_filter.setCurrentIndex(view.source_filter.findData(self.first["id"]))
        self.profile["sources"].remove(self.first)
        self.window.update_profile_ui()
        self.assertEqual(view.source_filter.currentData(), "")
        view.source_filter.setCurrentIndex(view.source_filter.findData(self.second["id"]))
        other = new_profile("另一学科")
        self.window.state["profiles"].append(other)
        self.window.state["active_profile_id"] = other["id"]
        self.window.update_profile_ui()
        self.assertEqual(view.source_filter.currentData(), "")
